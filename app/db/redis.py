import os, json, redis, pytz, ast, shutil
import pandas as pd
from datetime import timedelta, datetime, time
from pathlib import Path
from utils.log import get_module_logger
from utils.k import convert_ohlcv
from utils.file import open_json_file
import shioaji as sj
from dotenv import load_dotenv
load_dotenv()

log = get_module_logger('redis')
_redis_instance = None  # 用於存儲 Redis 單例實例

def get_redis_connection():
    global _redis_instance
    if _redis_instance is None:  # 如果尚未創建連線，則創建
        if os.getenv('REDIS_HOST') in ['redis', '127.0.0.1']:
            _redis_instance = redis.StrictRedis(host=os.getenv('REDIS_HOST'), port=os.getenv('REDIS_PORT'), decode_responses=True)
        else:
            _redis_instance = redis.RedisCluster(
                host=os.getenv("REDIS_HOST"),
                port=os.getenv("REDIS_PORT"),
                decode_responses=True,
                skip_full_coverage_check=True,
                readonly_mode=True  # 可選：讀取分擔到從節點
            )
        
    return _redis_instance  # 返回已存在的連線實例

# 判斷是否需要 night 過濾（下午 2:00 後）
def night_filter(current_time):
    afternoon_2pm = time(14, 0)  # 下午 2:00
    morning_6am = time(6, 0)    # 清晨 6:00
    
    # 檢查是否在晚上範圍（當天 14:00 到隔天 06:00）
    if current_time >= afternoon_2pm or current_time < morning_6am:
        return True
    return False

def set_redis_consumer(item, redis_cli=None):
    if redis_cli is None:
        redis_cli = get_redis_connection()
    
    log.info("即將創建redis的consumer_gruop去讀取redis_stream")
    
    # 獲取當前時間（考慮時區）
    current_time = datetime.now(pytz.timezone("Asia/Taipei")).time()

    for symbol in item.keys():
        for sub_item in item[symbol]:
            
            # 應用 night 過濾（僅在下午 2:00 後）
            if night_filter(current_time) and not sub_item.get("params", {}).get("night", False):
                log.info(f"跳過 strategy: {sub_item['strategy']}，night 未設定或為 False")
                continue
            
            for code in sub_item['code']:
                log.info(f"當前創建的stream為: {code}")
                data_redis_key = f"{sub_item['params']['broker']}_{symbol}_{code}_stream"
                data_group_name = f"{sub_item['params']['broker']}_{symbol}_{code}_{sub_item['strategy']}_group"
                bidask_redis_key = f"{sub_item['params']['broker']}_{symbol}_{code}_bidask_stream"
                bidask_group_name = f"{sub_item['params']['broker']}_{symbol}_{code}_{sub_item['strategy']}_group"
                
                create_consumer_group(redis_cli, data_redis_key, group=data_group_name)
                create_consumer_group(redis_cli, bidask_redis_key, group=bidask_group_name)
                
                log.info(f"當前 {code} 已經創建完畢, 將創建下一個\n")
    
    return

def create_consumer_group(redis_cli, stream_key, group):
    try:
        log.info(f"創建consumer_gruop中: {stream_key} / {group}")
        redis_cli.xgroup_create(stream_key, group, id="$", mkstream=True)
    except redis.exceptions.ResponseError as e:
        # 如果錯誤訊息包含 'BUSYGROUP'，就表示該組已經存在
        if "BUSYGROUP" in str(e):
            log.info("當前的consumer_gruop已經存在")
            pass  # 忽略錯誤，繼續執行
        else:
            raise  # 其他錯誤則重新拋出
        
async def clear_redis(lock, output_dir="data/preserve"):
    """
    定時清理redis任務:
    param中cross_day為True, 策略會跨天(跨夜盤, 波段..等) => 會將倉位資料清理後重新放回redis中
    如果是當沖或者步跨天的交易cross_day為false之後, 倉位資料將會保存並不添加回redis

    param中night為True, 策略會夜盤執行 => 夜磐時會進行資料清理, 將整理後的k棒依照時間放回redis
    如果是日盤但跨天策略, night為False且cross_day為True, 清晨會將策略的K棒資料填回redis
    """
    redis_conn = get_redis_connection()
    
    with lock: # 讀取setting.json
        items = {k: v for k, v in open_json_file()['items'].items() if v}
    
    # 確保基礎輸出目錄存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 保留與丟棄資料
    preserved_prefixes = ['future:', 'stock:', 'option:']
    preserved_suffixes = []
    deprecated = []
    
    # 遍历所有商品类别（如 'future', 'stock' 等）, 檢查cross_day確定是否跨天(波段, 夜盤..等)
    for category_key, category_items in items.items():
        # 遍历该类别下的每个商品条目
        for item in category_items:
            # 检查 params 是否存在且包含 cross_day 字段，且其值为 False (當沖策略, 不跨時間跨天計算)
            if item.get('params', {}).get('cross_day', False) is False:
                # 将符合条件的策略加入 deprecated
                deprecated.append(item['strategy'])
    
    log.info(f"當前 cross_day 為 False 或未設定, 不會保留的策略: {deprecated}")
    
    # -----------------  輔助函數 ------------------
    def history_refetch(refetch_list):
        api = sj.Shioaji()
        api.login(
            api_key=os.getenv('DATA_KEY'),
            secret_key=os.getenv('DATA_SECRET'),
            fetch_contract=False,
        )
        api.fetch_contracts(contract_download=True)
        
        # 計算 end 和 begin 日期
        end = datetime.now(tz=pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d')  # 當前日期，例如 '2025-04-15'
        begin = (datetime.now(tz=pytz.timezone('Asia/Taipei')) - timedelta(days=14)).strftime('%Y-%m-%d')  # 當前日期減 14 天
        
        for item in refetch_list:
            log.info(f'剩餘可用API: {api.usage()}')
            
            code = item['code']
            timeframe = item['timeframe']
            full_key = item['full_key']
            item_key = item.get('item_key', 'unknown')
            output_path = item['output_path']  # 例如 data/preserve/future/TMFR1_bilateral_1k

            try:
                # 根據 item_key 選擇合約類型
                if item_key == 'stock':
                    contract = api.Contracts.Stocks[code]
                elif item_key == 'future':
                    contract = api.Contracts.Futures[code]
                else:
                    log.error(f"未知的 item_key：{item_key}，跳過 {full_key}")
                    continue
                
                log.info(f"獲取k棒資料中:{code}")
                
                # 調用 API 獲取歷史 K 棒資料
                kbars = api.kbars(
                    contract=contract,
                    start=begin,  # 例如 '2025-04-14'
                    end=end,      # 例如 '2025-04-14'
                )

                # 轉為 DataFrame
                df = pd.DataFrame({**kbars})
                
                log.info(f"k棒獲取完畢: {df.tail(5)}")
                
                # 確保 ts 欄位為 datetime，並設置為索引
                df['ts'] = pd.to_datetime(df['ts'])
                df.set_index('ts', inplace=True)
                
                # 將 OHLCV 欄位名稱改為小寫
                df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
                
                k_df = convert_ohlcv(df, timeframe)

                # 儲存到 CSV，使用 output_path（資料夾名稱為 full_key）
                file_path = os.path.join(output_path, 'kbars.csv')
                os.makedirs(output_path, exist_ok=True)  # 確保資料夾存在
                k_df.to_csv(file_path, index=False)

                log.info(f"處理 {full_key} 從 {begin} 到 {end} 時間週期 {timeframe} 分鐘")
                log.info(f"資料存入 {file_path}\n")

            except Exception as e:
                log.error(f"獲取 {full_key}（{timeframe} 分鐘）歷史行情失敗：{e}\n")
                continue
            
        return

    def save_data(data, strategy, key, output_dir):
        # 構建目錄結構：data/preserve/{strategy}/{key}
        key_dir = os.path.join(output_dir, strategy, key)
        os.makedirs(key_dir, exist_ok=True)
        
        # 對於 hash 表資料，存為 JSON
        file_path = os.path.join(key_dir, f"data.json")
        
        # 判斷 key 屬於哪個保留位置
        processed_data = None
        matched_prefix = None
        matched_suffix = None
        
        # 1. 檢查是否匹配前綴
        for prefix in preserved_prefixes:
            if key.startswith(prefix):
                matched_prefix = prefix
                break
            
        # 2. 檢查是否匹配後綴
        for suffix in preserved_suffixes:
            if key.endswith(suffix):
                matched_suffix = suffix
                break

        # 根據匹配結果處理資料
        if matched_prefix: # 前綴匹配的處理邏輯 (可擴展)
            if matched_prefix in ['future:', 'stock:', 'option:']: # 針對 future:, stock:, option: 的處理邏輯（可擴展）
                log.info(f"處理 {matched_prefix} 資料：{key}")
                # 臨時使用 datetime 轉換，後續可替換
                processed_data = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}
                
                # 檢查檔案是否存在，若存在則讀取並合併
                final_data = processed_data
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            existing_data = json.load(f)
                        # 合併邏輯：更新現有資料（新資料覆蓋同名鍵）
                        if isinstance(existing_data, dict) and isinstance(processed_data, dict):
                            existing_data.update(processed_data)
                            final_data = existing_data
                        else:
                            log.warning(f"現有資料 {file_path} 或新資料格式不符，無法合併，直接使用新資料")
                            final_data = processed_data
                    except json.JSONDecodeError as e:
                        log.error(f"讀取現有檔案 {file_path} 失敗：{e}，使用新資料")
                        final_data = processed_data
                    except Exception as e:
                        log.error(f"處理現有檔案 {file_path} 失敗：{e}，使用新資料")
                        final_data = processed_data

                # 寫入合併後的資料
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(final_data, f, ensure_ascii=False, indent=4)
                    log.info(f"將資料 {key} 合併儲存至 {file_path}\n")
                except Exception as e:
                    log.error(f"儲存資料 {key} 失敗：{e}")
                    raise

        elif matched_suffix: # 後綴匹配的處理邏輯（可擴展）
            log.info(f"處理後綴 {matched_suffix} 資料：{key}")
            processed_data = data  # 暫時直接儲存，等待具體邏輯
            # 示例：假設後綴 '_data' 需要轉換為特定格式
            # if matched_suffix == '_data':
            #     processed_data = {'data_field': str(data)}
            # elif matched_suffix == '_info':
            #     processed_data = {'info': data.get('info'), 'time': v.isoformat() if isinstance(v, datetime) else v}
            
        else: # 無前綴或後綴匹配，記錄警告並使用原始 data
            log.warning(f"未知的 key 格式（無前綴或後綴匹配）：{key}，直接儲存未處理資料")
            processed_data = data
        
            # 存為 JSON
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=4)

                log.info(f"無前綴或後綴匹配 {key} 使用原始資料存儲至 {file_path}\n")
            except Exception as e:
                log.error(f"儲存資料 {key} 失敗：{e}")
                raise

    def parse_value(v):
        """
        模擬 get_position 的值解析邏輯，並處理時間戳格式
        """
        # 處理 bytes
        if isinstance(v, bytes):
            v = v.decode('utf-8')
        
        # 模擬 get_position 的邏輯
        if isinstance(v, str):
            # 嘗試 ast.literal_eval
            try:
                return ast.literal_eval(v)
            except (ValueError, SyntaxError):
                # 檢查是否為浮點數
                if '.' in v:
                    try:
                        return float(v)
                    except ValueError:
                        pass
                # 檢查是否為整數
                elif v.isdigit():
                    return int(v)
                # 保留原始字串
                return v
        return v
    
    def clean_k_folders(output_dir):
        """
        刪除 output_dir 下所有子目錄中以 'K' 或 'k' 結尾的資料夾及其內容。

        Args:
            output_dir (str): 根目錄路徑，例如 '/data/preserve'
        """
        # 確保 output_dir 存在
        if not os.path.exists(output_dir):
            log.error(f"目錄 {output_dir} 不存在")
            return

        # 遍歷 output_dir 下的所有子目錄
        for root, dirs, _ in os.walk(output_dir, topdown=False):
            for dir_name in dirs:
                # 檢查資料夾名稱是否以 'K' 或 'k' 結尾
                if dir_name.lower().endswith('k'):
                    folder_path = os.path.join(root, dir_name)
                    try:
                        # 刪除資料夾及其所有內容
                        shutil.rmtree(folder_path)
                        log.info(f"已刪除資料夾: {folder_path}")
                    except Exception as e:
                        log.error(f"刪除資料夾 {folder_path} 時發生錯誤: {e}")
        
        return

    def fetch_data(output_dir):
        clean_k_folders(output_dir)
        result = []
        seen_pairs = set()  # 去重 (code, strategy, timeframe)
        current_time = datetime.now(pytz.timezone("Asia/Taipei")).time()

        for item_key, item_list in items.items():
            for item in item_list:
                params = item.get("params", {})

                # 應用 night 過濾（僅在下午 2:00 後）
                if night_filter(current_time) and not params.get("night", False):
                    log.info(f"當前判斷是否要列入重新獲取的清單, 跳過 strategy: {item['strategy']}，night 未設定或為 False")
                    continue
                
                k_time = params.get('K_time', 1)
                for code in item['code']:
                    # 去重
                    pair = (code, item['strategy'], k_time)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    # 添加到結果，包含完整鍵
                    result.append({
                        'code': code,
                        'strategy': item['strategy'],
                        'timeframe': k_time,
                        'full_key': f"{code}_{item['strategy']}_{k_time}k"  # 拼接原始key，例如 MXFR1_statarb1_60k
                    })

        # 驗證 code 和 strategy 是否在 cross_day=True 的 items 中
        valid_result = []
        for pair in result:
            code = pair['code']
            strategy = pair['strategy']
            full_key = pair['full_key']
            
            # 檢查 items 中是否有匹配的 code 和 strategy 且 cross_day=True
            is_valid = False
            for item_key, item_list in items.items():
                for item in item_list:
                    if (isinstance(item.get('params'), dict) and 
                        item['params'].get('cross_day') is True and
                        code in item.get('code', []) and 
                        item.get('strategy') == strategy):
                        is_valid = True
                        pair['item_key'] = item_key  # 儲存商品類型（例如 'future'）
                        pair['output_path'] = os.path.join(output_dir, strategy, full_key)
                        break
                    
                if is_valid:
                    break
                
            if is_valid:
                valid_result.append(pair)
                
            else:
                log.warning(f"code {code} 和 strategy {strategy} 未找到對應的 cross_day=True item")

        return valid_result # 返回 [{'code': 'TMFR1', 'strategy': 'bilateral', 'timeframe': '1', 'full_key': 'TMFR1_bilateral_1k', 'item_key': 'future', 'output_path': 'data/preserve/future/TMFR1_bilateral_1k'}, ...]
    
    def reinsert_data(output_dir):
        for root, _, files in os.walk(output_dir):
            # 提取當前目錄名稱作為 Redis 鍵
            path_parts = Path(root).parts
            # 確保路徑深度足夠（至少是 data/preserve/子目錄）
            if len(path_parts) < 3:
                continue  # 跳過根目錄（例如 data/preserve 本身）
        
            redis_key = path_parts[-1]  # 當前子目錄名稱（策略名稱，例如 daytrade 或 bilateral）
        
            # 如果 redis_key 在 deprecated 中，跳過整個目錄
            if redis_key in deprecated:
                log.info(f"跳過 deprecated 的目錄: {root} (策略: {redis_key})\n")
                continue

            for file_name in files:
                # 獲取完整的文件路徑
                file_path = os.path.join(root, file_name)
                
                try:
                    # 根據文件擴展名處理
                    file_ext = os.path.splitext(file_name)[1].lower()

                    if file_ext == '.json':
                        # 處理 JSON 文件
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                        # 檢查是否只有一筆資料且鍵為 'ts'
                        if isinstance(data, dict) and len(data) == 1 and 'ts' in data:
                            formatted_ts = datetime.strptime(data['ts'], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
                            redis_conn.hset(redis_key, mapping={'ts': formatted_ts})
                            log.info(f"成功處理 JSON 文件: {file_path}, 鍵: {redis_key}, ts 轉為 {formatted_ts} 存入 Hash")

                        else: # 非單一筆資料, 為倉位資料(參考set_position, set_analyze)
                            for key, key_data in data.items():
                                # 處理字典結構 => (倉位資料)
                                if isinstance(key_data, dict):
                                    clean_data = {}
                                    exclude_keys = {'pending_orders', 'completed_orders', 'arrived_deals', 'update_position', 'clear_position'}

                                    # 過濾 exclude_keys 和 deal:/order: 鍵
                                    clean_data[key] = {
                                        k: v for k, v in key_data.items()
                                        if k not in exclude_keys and not k.startswith(('order:', 'deal:'))
                                    }
                                    
                                    # 確保字典中的值被轉換為 Redis 支援的類型（例如 string 或 bytes）
                                    redis_data = {k: str(v) if not isinstance(v, (str, bytes)) else v for k, v in clean_data.items()}

                                    redis_conn.hset(redis_key, mapping=redis_data)

                                # 處理陣列結構 => (交易分析資料)
                                elif isinstance(key_data, list):
                                    # 將值序列化為 JSON 字符串
                                    serialized_value = json.dumps(key_data, ensure_ascii=False)
                                    # 使用 hset 命令將字段和值存入 Redis 哈希表
                                    redis_conn.hset(redis_key, key, serialized_value)

                    elif file_ext == '.csv':
                        # 處理 CSV 文件
                        df = pd.read_csv(file_path)
                        # 將 CSV 轉為字典列表（每行一個字典）
                        records = df.to_dict(orient='records')

                        # 將每行記錄存入 Redis List
                        for record in records:
                            redis_conn.rpush(redis_key, json.dumps(record))
                            
                        log.info(f"成功處理 CSV 文件: {file_path}, 鍵: {redis_key}, 存入 Redis List，記錄數: {len(records)}")

                    else:
                        log.info(f"不支持的文件格式: {file_path}，跳過")

                except json.JSONDecodeError:
                    log.error(f"文件 {file_path} JSON 解析錯誤")
                except pd.errors.ParserError:
                    log.error(f"文件 {file_path} CSV 解析錯誤")
                except Exception as e:
                    log.error(f"處理文件 {file_path} 時發生錯誤: {str(e)}")
        
        return            

    def scan_all_key():
        all_keys = []
        
        if os.getenv('REDIS_HOST') in ['redis', '127.0.0.1']:
            log.info("當前Redis單機模式")
            for key in redis_conn.scan_iter():
                all_keys.append(key if isinstance(key, str) else key.decode('utf-8'))
        else:
            log.info("當前Redis集群模式")
            nodes = redis_conn.get_nodes()
            for node in nodes:
                node_conn = redis_conn.get_redis_connection(node)
                node_info = node_conn.info('replication')
                if node_info.get('role') == 'master':
                    for key in node_conn.scan_iter():
                        all_keys.append(key if isinstance(key, str) else key.decode('utf-8'))

        log.info(f"所有的redis_key:{all_keys}")     
        return all_keys
                        
    # -----------------  清理資料主程序 ------------------
    # 儲存保留的鍵和重新獲取歷史資料
    preserved_data = {}

    log.info(f"所有的redis_key:{redis_conn.scan_iter()}")

    # 掃描所有 Redis 鍵
    for key in scan_all_key():
        # 確保 key 是字符串
        if isinstance(key, bytes):
            key = key.decode('utf-8')

        # 檢查是否需要保留
        should_preserve = (
            any(key.startswith(prefix) for prefix in preserved_prefixes) or
            any(key.endswith(suffix) for suffix in preserved_suffixes)
        )

        # should_preserve(hash表) => 例: 倉位資料, K棒資料(須按時間捨棄部分)
        if should_preserve:
            # 獲取鍵對應的資料
            key_type = redis_conn.type(key)
            if isinstance(key_type, bytes):
                key_type = key_type.decode('utf-8')

            if key_type == 'hash': # Redis中的哈希表
                # 處理 hash 表
                data = redis_conn.hgetall(key)
                processed_data = {}
                
                for k, v in data.items():
                    # 處理鍵
                    k = k.decode('utf-8') if isinstance(k, bytes) else k
                    # 解析值
                    processed_data[k] = parse_value(v)
                
                data = processed_data

            else: # 處理其他類型的資料
                value = redis_conn.get(key)
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                data = json.loads(value)
            
            preserved_data[key] = data
    
    # 按 strategy 分類並儲存
    for key, data in preserved_data.items():
        strategy = 'unknown'  # 預設值

        # 檢查是否以 preserved_prefixes 中的前綴開頭
        for prefix in preserved_prefixes:
            if key.startswith(prefix):
                # 根據前綴選擇分隔符
                strategy = key.split(':')[1] # 其他前綴（future:, stock:, option:）使用 : 分割
                break
            
        if not strategy:
            strategy = 'unknown'  # 防止 strategy 為空

        save_data(data, strategy, key, output_dir)

    # 重新獲得部分歷史行情資料
    refetch_list = fetch_data(output_dir)
    history_refetch(refetch_list)
    
    # 清空 Redis 資料庫
    try:
        redis_conn.flushall()
        log.info("成功清空當前 Redis 資料庫, 將重新添加redis的consumer_gruop")

        set_redis_consumer(items, redis_conn)
        log.info("成功重新創建並添加有night參數的consumer_gruop")
        
    except Exception as e:
        log.error(f"清空 Redis 資料庫失敗：{e}")
        raise
    
    # 重新添加行情資料
    reinsert_data(output_dir)
    
    log.info("本次的調用結束, 等待下一次調用\n\n")
    return
