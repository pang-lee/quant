import asyncio, os, time, json, threading, datetime, pytz
from collections import defaultdict
from data import DatasourceFactory
from strategy import Strategy
import pandas as pd
from db.redis import get_redis_connection, create_consumer_group, set_redis_consumer
from utils.file import update_settings
from dotenv import load_dotenv
load_dotenv()

isDev = os.getenv('IS_DEV', 'false').lower() in ('true', '1', 'yes')
if isDev:
    code = 'TMFR1'
    dev_redis_key= f"dev_{code}_stream"

# -------------- 資料行情訂閱 --------------------
def run_data_sources(symbols):
    # 過濾掉空陣列的 key
    filtered_symbols = {k: v for k, v in symbols.items() if v}

    # 如果是測試開發
    if isDev:
        # 啟動執行緒來處理 Shioaji 訂閱
        thread = threading.Thread(target=read_from_csv)
        thread.daemon = True
        thread.start()

    # 實盤行情資料
    else:
        set_redis_consumer(filtered_symbols)
        
        # 提取需要訂閱的項目
        shioaji_subscription = []

        # 提取有效的 datasource 並生成數據源
        for key, items in filtered_symbols.items():
            for item in items:
                datasource_type = item['params'].get('datasource')
                simulation = item['params'].get('simulation')
                symbol_codes = item.get('code', [])

                # 為每個 code 建立數據源
                for symbol_code in symbol_codes:
                    if datasource_type == "shioaji":
                        shioaji_subscription.append((key, symbol_code, simulation))
                    elif datasource_type == "fugle":
                        # Fugle 使用 WebSocket 處理
                        handle_fugle_websocket(key, symbol_code, simulation)
                        
        if shioaji_subscription:
            unique_subscriptions = {}
            for key, symbol_code, simulation in shioaji_subscription:
                identifier = (key, symbol_code, simulation)
                unique_subscriptions[identifier] = (key, symbol_code, simulation)

            # 啟動執行緒來處理 Shioaji 訂閱
            thread = threading.Thread(target=handle_shioaji_subscription, args=(unique_subscriptions,))
            thread.daemon = True
            thread.start()

def read_from_csv():
    redis_cli = get_redis_connection()
    df = pd.read_csv(f"./data/test/{code}.csv")

    # 將時間戳轉換為 datetime 格式
    df['ts'] = pd.to_datetime(df['ts'])
        
    # 使用 groupby 來按秒分組
    df = df.groupby(df['ts'].dt.floor('s')).agg({
        'close': 'last', 
        'volume': 'sum', 
        'bid_price': lambda x: tuple(sorted(x)), 
        'bid_volume': 'sum', 
        'ask_price': lambda x: tuple(sorted(x)), 
        'ask_volume': 'sum', 
        'tick_type': lambda x: DatasourceFactory.analyze_tick_types(x, type='pandas')
    }).reset_index()

    df.set_index('ts', inplace=True)
        
    # 按秒分組並模擬每秒處理一次資料
    for i in range(0, len(df)):
        row = df.iloc[i]
        
        redis_cli.xadd(dev_redis_key, {
            "ts": row.name.strftime('%Y-%m-%d %H:%M:%S'),
            "close": float(row["close"]),  # 轉換為原生 float
            "volume": int(row["volume"]),  # 轉換為原生 int
            "bid_price": json.dumps([float(x) for x in row["bid_price"]]),  # tuple 轉換並轉 float
            "bid_volume": int(row["bid_volume"]), 
            "ask_price": json.dumps([float(x) for x in row["ask_price"]]),
            "ask_volume": int(row["ask_volume"]),
            "tick_type": json.dumps(row["tick_type"]),  # dict 轉為 JSON 字符串
            'code': code
        })
        
        time.sleep(1)
    
def handle_shioaji_subscription(subscriptions):
    # 先對訂閱列表進行去重，依據 (key, symbol_code, simulation) tuple 唯一標識
    for key, symbol_code, simulation in subscriptions.values():
        print(f"訂閱 Shioaji 行情數據: {symbol_code} (key: {key}, 模擬: {simulation})")
        DatasourceFactory.create_datasource("ShioajiDataSource", key, symbol_code, simulation)

    while True: # Shioaji 訂閱
        time.sleep(1)  # 控制訂閱頻率

def handle_fugle_websocket(key, symbol_code, simulation):
    print(f"訂閱 Fugle WebSocket 行情數據: {symbol_code} (key: {key}, 模擬: {simulation})")
    data_source = DatasourceFactory.create_datasource("fugle", key, symbol_code, simulation)

# -------------- 訊號計算與下單 ---------------------

# 訊號計算與判斷（CPU 密集型任務）
def check_signal(symbol, item, log):
    redis_cli = get_redis_connection()
    data_list = {}

    if isDev: # 測試環境僅使用單一stream與單一資料進行讀取(dev_redis_key)
        for code in item['code']:
            group_name = f"{item['params']['broker']}_{symbol}_{code}_group"
            consumer_name = f"consumer_{item['params']['broker']}_{symbol}_{code}"
            
            create_consumer_group(redis_cli, dev_redis_key, group=group_name)
            data = redis_cli.xreadgroup(group_name, consumer_name, streams={dev_redis_key: '>'}, block=1000, count=10)
            
            if data:
                data_list[code] = (message[1] for _, messages in data for message in messages)
                
    else: # 如果是正式環境, 依照symbol和code來所生成的獨立stream進行讀取(EX: stock_2330_stream), conusmer和gruop也要一個個對應        
        log.info(f"開始檢查訊號: {symbol}, \n計算商品: {item}")
        try:
            for code in item['code']:
                data_redis_key = f"{item['params']['broker']}_{symbol}_{code}_stream"
                data_group_name = f"{item['params']['broker']}_{symbol}_{code}_{item['strategy']}_group"
                data_consumer_name = f"consumer_{item['params']['broker']}_{symbol}_{code}_{item['strategy']}"

                bidask_redis_key = f"{item['params']['broker']}_{symbol}_{code}_bidask_stream"
                bidask_group_name = f"{item['params']['broker']}_{symbol}_{code}_{item['strategy']}_group"
                bidask_consumer_name = f"consumer_{item['params']['broker']}_{symbol}_{code}_{item['strategy']}_bidask"

                data = redis_cli.xreadgroup(data_group_name, data_consumer_name, streams={data_redis_key: '>'}, block=1000, count=10)
                bid_ask = redis_cli.xreadgroup(bidask_group_name, bidask_consumer_name, streams={bidask_redis_key: '>'}, block=1000, count=10)

                if data:
                    # 提取 tick 和 bidask 數據
                    tick_data = [message[1] for _, messages in data for message in messages]
                    bidask_data = [message[1] for _, messages in bid_ask for message in messages]

                    # 清理 bidask_data 中的字串化列表
                    for bd in bidask_data:
                        bd['bid_prices'] = json.loads(bd['bid_prices'])
                        bd['bid_volumes'] = json.loads(bd['bid_volumes'])
                        bd['diff_bid_vols'] = json.loads(bd['diff_bid_vols'])
                        bd['ask_prices'] = json.loads(bd['ask_prices'])
                        bd['ask_volumes'] = json.loads(bd['ask_volumes'])
                        bd['diff_ask_vols'] = json.loads(bd['diff_ask_vols'])

                    # 按秒聚合 tick_data
                    aggregated_ticks = DatasourceFactory.aggregate_ticks_by_second(tick_data)

                    # 按完整時間戳排序（含微秒）
                    aggregated_ticks.sort(key=lambda x: x["ts"])
                    bidask_data.sort(key=lambda x: x["ts"])

                    # 將聚合後的 tick_data 和 bidask_data 按秒合併
                    grouped = defaultdict(lambda: {"tick": [], "bidask": []})
                    for rec in aggregated_ticks:
                        ts_key = rec["ts"].split('.')[0]  # 去除微秒部分
                        grouped[ts_key]["tick"].append(rec)
                    for rec in bidask_data:
                        ts_key = rec["ts"].split('.')[0]
                        grouped[ts_key]["bidask"].append(rec)

                    # 為當前 code 創建獨立的數據列表
                    code_data = []
                    for ts, data_dict in grouped.items():
                        code_data.append({
                            "ts": ts,
                            "tick": data_dict["tick"],
                            "bidask": data_dict["bidask"]
                        })

                    # 將當前 code 的數據加入 data_list
                    data_list[code] = code_data

            if not data_list: # 如果沒有數據, 則返回預設的結構, 等待下一次
                log.info(f"\n當前data_list沒有從redis的stream中獲得任何資料, 等待下一次檢查\n")
                return [(symbol, item, False, {}, {}, {})]
            
            # 可以傳入多筆{data1: [], data2: []}
            result = Strategy(symbol, item, data_list).execute()
            log.info(f"當前策略回傳結果: {result}")

            # 回傳結果 [(symbol, item, 下單行為(詳情看AbstractStrategy), {}修改參數, {}推播內容, {}訂單參數)...]
            return result
    
        except Exception as e:
            log.error(f"當前check_siganl出錯: {e}")
            return [(symbol, item, False, {}, {}, {})]

# 下單（I/O 密集型任務）symbol: 商品種類, item: 商品代號詳情, result_type: 下多空單, order_params: 訂單參數(止盈止損價)
def place_order(order_params, brokers, result_type, broker_lock, order_status, strategy_lock, pending_task, log):
    # 從 order_params 中提取 broker, stratgey
    broker_name = order_params.get('broker')
    key = order_params.get('symbol')
    strategy = order_params.get('strategy')
    
    if not strategy:
        log.error("order_params 中缺少 strategy")
        return False
        
    if not broker_name or broker_name not in brokers:
        log.error(f"無效的 broker 名稱: {broker_name}")
        return False
    
    lock_key = f"{key}:{strategy}"
    strategy_lock = strategy_lock.get(lock_key)
    if not strategy_lock:
        log.error(f"未找到 {lock_key} 的策略鎖")
        return False

    # 获取该券商的专用锁
    b_lock = broker_lock.get(broker_name)
    if not b_lock:
        log.error(f"券商锁未配置: {broker_name}")
        return False

    try:
        with strategy_lock:  # 控制同一策略的下單順序
            # 檢查當前狀態，避免重複下單
            if order_status.get(lock_key, 'completed') == 'pending':
                log.info(f"{lock_key} 已在下單中，跳過")
                return False

            order_status[lock_key] = 'pending'
            log.info(f"設置 {lock_key} 訂單狀態為 'pending'")
            log.info(f"{broker_name}, 下單行為: {result_type}, 下單: {order_params}")
            
            with b_lock:  # 券商鎖控制並發
                result = brokers[broker_name].place_order(order_params, result_type)
                if result:
                    order_status[lock_key] = 'completed'
                    log.info(f"下單成功: {lock_key}, 狀態更新為 'completed'")
                else:
                    order_status[lock_key] = 'failed'
                    log.error(f"下單失敗: {broker_name} => {lock_key}")

                # 更新 pending_task
                pending_task[strategy] = max(pending_task.get(strategy, 0) - 1, 0)
                if pending_task[strategy] == 0 and all(status == 'completed' for k, status in order_status.items() if strategy in k):
                    log.info(f"策略 {strategy} 所有訂單已完成，可以進入下一次計算")
                
                return result
            
    except Exception as e:
        log.error(f"{broker_name} 下單發生錯誤: {e}")
        with strategy_lock:
            order_status[lock_key] = 'failed'
            pending_task[strategy] = max(pending_task.get(strategy, 0) - 1, 0)
        return False

# -------------- 主程序 ---------------------

# 解析 stop_time 的輔助函數
def parse_stop_time(stop_time_list):
    stop_time_ranges = []
    
    for time_range in stop_time_list:
        start_str, end_str = time_range.split('-')
        start_time = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
        stop_time_ranges.append((start_time, end_time))

    return stop_time_ranges

# 檢查當前時間是否在停止時間段內
def is_in_stop_time(current_time, stop_time_ranges):
    for start_time, end_time in stop_time_ranges:
        if start_time <= current_time <= end_time:
            return True
    return False

# 主程序(遍歷商品列表並提交訊號計算和下單任務)
async def process_item(items, queue, process_pool, thread_pool, brokers, p_lock, broker_lock, order_status, strategy_lock, pending_task, log):
    # 獲取當前時間（考慮時區）
    current_time = datetime.datetime.now(pytz.timezone("Asia/Taipei")).time()

    # 過濾掉訂單未完成的策略
    stock_codes = {}
    for symbol, item_list in items.items():
        filtered_item_list = []
        for item in item_list:
            strategy = item.get('strategy')
            if not strategy:
                log.warning(f"Item 中缺少 strategy: {item}")
                continue
            
            # 檢查該策略的訂單狀態和未完成任務數量
            current_status = order_status.get(strategy, 'completed')
            pending_count = pending_task.get(strategy, 0)
            if current_status != 'completed' or pending_count > 0:
                log.info(f"跳過 strategy: {strategy}，狀態: {current_status}, 未完成訂單數: {pending_count}")
                continue

            # 解析並檢查 stop_time
            stop_time_list = item.get('params', {}).get('stop_time', [])
            if stop_time_list:
                stop_time_ranges = parse_stop_time(stop_time_list)
                if is_in_stop_time(current_time, stop_time_ranges):
                    log.info(f"跳過 strategy: {strategy}，當前時間 {current_time} 在停止時間段內: {stop_time_list}")
                    continue

            filtered_item_list.append(item)
        
        if filtered_item_list:
            stock_codes[symbol] = filtered_item_list

    log.info(f'過濾後可運行策略種類: {len(stock_codes)}, \n策略:{stock_codes}')
    if not stock_codes:
        log.info("無可執行的策略，執行下一次 process_item")
        return
    
    loop = asyncio.get_event_loop()
    
    # 提交訊號計算任務到進程池
    tasks = [
        loop.run_in_executor(process_pool, check_signal, symbol, item, log)
        for symbol, item_list in stock_codes.items()
        for item in item_list
    ]
    
    # 逐個處理訊號計算結果並提交下單任務到線程池
    for future in asyncio.as_completed(tasks):
        try:
            future_results = await future
            
            # 遍歷所有的結果
            for future_result in future_results:
                symbol, item, result_type, modify_params, notify_params, order_params = future_result
                log.info(f"\n計算訊號: {symbol}, \n相關資訊: {item}, \n下單行為: {result_type}, \n修改參數: {modify_params}, \n推播內容: {notify_params}, \n訂單參數: {order_params}")

                # 判斷是否為下單訊號(1: 多, -1: 空, ...)
                if not isinstance(result_type, bool):
                    strategy = order_params.get('strategy')
                    
                    # 如果是動態改倉位(5: 多倉改價, -5: 空倉改價), 僅進行通知
                    if result_type not in [5, -5]:
                        loop.run_in_executor(thread_pool, place_order, order_params, brokers, result_type, broker_lock, order_status, strategy_lock, pending_task, log)
                        
                        # 更新 pending_task
                        with p_lock:  # 使用進程鎖保護多進程共享變量
                            pending_task[strategy] = pending_task.get(strategy, 0) + 1
                        
                        log.info(f"當前{strategy}有{pending_task[strategy]}個訂單尚未完成")
                    
                    if modify_params:
                        with p_lock:
                            update_settings(symbol, item['code'], item['strategy'], modify_params)
                            log.info(f"更新參數: {symbol}, {item['code']}, {item['strategy']}, {modify_params}")

                    if notify_params:
                        await queue.put(('signal', [notify_params]))

                    continue

                # 非數值訊號True(自定義行為)
                elif result_type:
                    # 修改策略數據
                    if modify_params:    
                        with p_lock:
                            update_settings(symbol, item['code'], item['strategy'], modify_params)
                            log.info(f"更新參數: {symbol}, {item['code']}, {item['strategy']}, {modify_params}")

                    if notify_params:
                        await queue.put(('signal', [notify_params]))

                    continue
                
                # 如果收到回傳False, 甚麼都不做
                elif not result_type:
                    continue
        except Exception as e:
            log.error(f"程式運行出現錯誤, 或許未得到回傳: {e}")
                
    log.info("完成計算, 等待下次計算\n\n")
    return