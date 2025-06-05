from abc import ABC, abstractmethod
from db.redis import get_redis_connection
from data.DatasourceFactory import DatasourceFactory
from position.load import load_position_controls
from datetime import datetime, timedelta
import pandas as pd
from utils.log import get_module_logger
import importlib, json, pytz, uuid

class AbstractStrategy(ABC):
    def __init__(self, datas, item, symbol, profit_stop, stop_loss, tick_size=0, k=60):
        self.redis = get_redis_connection()
        self.interval = k // 60 # Convert to "minutes"
        self.item = item
        self.data = datas
        self.log = get_module_logger(f"strategy/{self.item['strategy']}")

        if not self.data:
            self.log.info("當前策略沒有獲得資料, 將不做任何行為, 等待下一次的策略循環")

        self.symbol = symbol
        self.params = item['params']
        self.redis_k_key = ''
        self.insert_data()

        # 處理 profit_stop 參數
        if profit_stop == 0:
            self.profit_stop = 0
        elif isinstance(profit_stop, list):
            self.profit_stop = dict(zip(self.item['code'], [self.params[param] for param in profit_stop]))
        else:
            self.profit_stop = self.params[profit_stop]

        # 處理 stop_loss 參數
        if stop_loss == 0:
            self.stop_loss = 0
        elif isinstance(stop_loss, list):
            self.stop_loss = dict(zip(self.item['code'], [self.params[param] for param in stop_loss]))
        else:
            self.stop_loss = self.params[stop_loss]

        # 處理 tick_size 參數
        if tick_size == 0:
            self.tick_size = 0
        elif isinstance(tick_size, list):
            # 检查列表中是否有字典, 做股期或配對交易可以使用(list of dict => [{tick_size: tick_size1, levearge: levearge1, symbol: 股票or期貨, ...}]) => 可能是股票期貨, 或者有槓桿的商品
            has_dict = any(isinstance(d, dict) for d in tick_size)
            
            if not has_dict: # 單純獲得tick_size列表 [tick_size1, tick_size2, ...], 將組合出 => {cod1: self.params['tick_size1'], code2: self.params['tick_size2']...}
                self.tick_size = dict(zip(self.item['code'], [self.params[param] for param in tick_size]))
                
            else: # 如果列表中包含字典，提取每个字典中的 'tick_size', 'leverage', ...etc, 并与 self.item['code'] 配对 => 詳細舉例請參考 AbstractPositionControl -> calculate_take_profit或calculate_stop_loss
                self.tick_size = {
                    code: {
                        'tick_size': self.params[d['tick_size']],
                        'leverage': self.params[d['leverage']],
                        'symbol': d.get('symbol', 'index') # 添加要交易的商品, 默認預設為index, 如果配對交易其中一邊為股票則添加stock
                    } for code, d in zip(self.item['code'], tick_size)
                }
        else:
            self.tick_size = self.params[tick_size]

        self.calculate = []
        self.order = [] # 組裝訂單
        self.last_data = self.get_last_ts_data()
        self.position_controls = load_position_controls()  # 加載所有艙位控制
        self.position_redis_key = f"{self.symbol}:{self.item['strategy']}:{self.process_redis_key()}"
        self.analyze_redis_key = f"{self.symbol}:{self.item['strategy']}:{self.process_redis_key()}_analyze"
        self.build_position_control()
        self.tz = pytz.timezone(f"{self.params['tz']}")
        self.current_time = datetime.now(tz=self.tz)

    def process_redis_key(self):
        # 檢查 self.item['code'] 是否為列表
        if not isinstance(self.item['code'], list):
            self.log.error(f"self.item['code'] 不是列表: {type(self.item['code'])}, 值: {self.item['code']}")
            raise ValueError("self.item['code'] 必須是列表")

        # 檢查列表是否為空
        if not self.item['code']:
            self.log.error("self.item['code'] 是空列表")
            raise ValueError("self.item['code'] 不能為空列表")

        # 根據元素數量處理
        if len(self.item['code']) == 1:
            processed_key = self.item['code'][0]  # 單元素直接返回，例如 "TMFR"
        else:
            processed_key = "_".join(self.item['code'])  # 多元素用下劃線連接，例如 "MXFR1_TMFR1"

        return processed_key

    def insert_data(self):
        redis_k_keys = {}  # 用來收集每個 code 對應的 redis_k_key

        for code, records in self.data.items():  # key 是 'TMFR1'，records 是列表
            redis_calculate_key = f"{code}_{self.item['strategy']}_calculate"
            redis_k = f"{code}_{self.item['strategy']}_{self.interval}k"
            
            # 儲存每個 code 對應的 redis_k_key
            redis_k_keys[code] = redis_k

            # 遍歷每筆記錄
            for record in records:
                # 提取 tick 數據
                ticks = record.get('tick', [])  # 使用 get 避免 KeyError，默認為空列表
                if ticks:  # 如果 tick 不為空
                    for tick in ticks:
                        # 將單個 tick 記錄存入 Redis
                        self.save_to_redis(redis_calculate_key, tick)
                        # 計算 OHLCV
                        self.calculate_ohlcv(redis_calculate_key, redis_k)

        # 根據資料種類的數量決定 self.redis_k_key 是字串還是陣列
        if len(redis_k_keys) == 1:
            self.redis_k_key = list(redis_k_keys.values())[0] # 只有一個 code 時，設為單一字串
        else:
            self.redis_k_key = redis_k_keys  # 多個 code 時，設為陣列

        return

    def get_from_redis(self, redis_key):
        data = self.redis.hgetall(redis_key)

        # 如果返回的資料是空字典，代表該 key 不存在
        if not data:
            self.log.info(f"當前從redis取不到資料, Redis Key: {redis_key}")
            return None
        
        def convert_value(v):
            if isinstance(v, bytes):
                v = v.decode()
            if v == "True":
                return True
            if v == "False":
                return False
            return v

        return {k.decode() if isinstance(k, bytes) else k: convert_value(v) for k, v in data.items()}

    def pop_from_redis(self, redis_key):
        existing_data = self.redis.rpop(redis_key)
        order_list = json.loads(existing_data) if existing_data else None
        return order_list
    
    def len_of_redis(self, redis_key):
        return self.redis.llen(redis_key)
    
    def lrange_of_redis(self, redis_key, start, end):
        return self.redis.lrange(redis_key, start, end)
    
    def ltrim_of_redis(self, redis_key, start, end):
        return self.redis.ltrim(redis_key, start, end)
    
    def save_to_redis(self, redis_key, dict_data, type='list'):
        if type == 'list':
            self.redis.rpush(redis_key, json.dumps(dict_data))
        elif type== 'set':
            self.redis.hset(redis_key, mapping={key: str(value) for key, value in dict_data.items()})

    def clear_redis_list(self, redis_key):
        return self.redis.delete(redis_key)
    
    def calculate_ohlcv(self, redis_calculate_key, redis_k_key):
        # 從 Redis 獲取數據
        data = self.lrange_of_redis(redis_calculate_key, 0, -1)
        if not data:
            return

        # 解析數據
        recent_data = [json.loads(record) for record in data]

        # 按 K 線窗口分組
        kline_windows = {}  # 格式: {k_start: [records]}
        for record in recent_data:
            record_ts = datetime.strptime(record['ts'], "%Y-%m-%d %H:%M:%S")
            # 計算所屬的 K 線窗口起始時間
            k_start = self.get_kline_window_start(record_ts)
            if k_start not in kline_windows:
                kline_windows[k_start] = []
            kline_windows[k_start].append(record)

        # 獲取當前時間（假設以最後一筆數據的時間為基準）
        last_ts = datetime.strptime(recent_data[-1]['ts'], "%Y-%m-%d %H:%M:%S")
        current_time = last_ts

        # 找出所有已完成的時間窗口
        completed_windows = []
        for k_start in kline_windows.keys():
            window_end = k_start + timedelta(minutes=self.interval) - timedelta(seconds=1)  # 窗口結束時間
            if window_end <= current_time:
                completed_windows.append(k_start)

        # 計算並存儲已完成的 K 線
        for k_start in completed_windows:
            records = kline_windows[k_start]
            if records:
                ohlcv = DatasourceFactory.calculate_ohlcv_from_data(records)
            else:
                # 若無數據，沿用前一根 K 線的收盤價
                ohlcv = self.use_previous_ohlcv(redis_k_key)

            self.store_ohlcv_to_redis(ohlcv, redis_k_key)

        # 從 Redis 中移除已處理的數據（只保留未完成窗口的數據）
        data_to_keep = []
        for record in recent_data:
            record_ts = datetime.strptime(record['ts'], "%Y-%m-%d %H:%M:%S")
            k_start = self.get_kline_window_start(record_ts)
            if k_start not in completed_windows:
                data_to_keep.append(record)

        # 清空並重新寫入未處理的數據
        self.clear_redis_list(redis_calculate_key)
        for record in data_to_keep:
            self.save_to_redis(redis_calculate_key, record)

    def get_kline_window_start(self, record_ts):
        """
        根據 record_ts 和 self.interval 計算所屬的 K 線窗口起始時間。
        """
        # 計算窗口起始時間
        interval_minutes = self.interval
        window_start_minute = (record_ts.minute // interval_minutes) * interval_minutes
        k_start = record_ts.replace(minute=window_start_minute, second=0, microsecond=0)
        return k_start

    def store_ohlcv_to_redis(self, ohlcv, redis_k_key):        
        # 將 OHLCV 存入 Redis
        return self.save_to_redis(redis_k_key, ohlcv)
           
    def use_previous_ohlcv(self, redis_k_key):
        # 取出最後一根 K 線資料作為基礎
        previous_data = self.lrange_of_redis(redis_k_key, -1, -1)
    
        if previous_data:
            ohlcv = json.loads(previous_data[0])
            # 將成交量設為 0
            ohlcv["volume"] = 0
            return ohlcv
    
        # 若沒有前一根 K 線資料，返回預設空數據
        return {"ts": 0, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
    
    def load_calculations(self, data):
        calculation_types = self.item['calculation']
        
        for calc_type in calculation_types:
            try:
                # 动态生成模块与类名：模块小写，类名大写
                module_name = calc_type.lower()  # 確保文件名小寫
                class_name = calc_type.capitalize()  # 確保類名符合駝峰命名

                module = importlib.import_module(f'strategy.calculation.{module_name}')
                calculation_class = getattr(module, class_name)

                if isinstance(data, pd.DataFrame): # 檢查 data 是否為 Pandas DataFrame, 如果已經是 DataFrame，直接傳遞
                    calculation_instance = calculation_class(self.params, data, f"strategy/{self.item['strategy']}")
                else:
                    calculation_instance = calculation_class(self.params, pd.DataFrame(data), f"strategy/{self.item['strategy']}")

                self.calculate.append(calculation_instance)
            except ImportError:
                raise ValueError(f"Calculation type '{calc_type}' 不存在.")
            except AttributeError:
                raise ValueError(f"Calculation class '{calc_type.capitalize()}' 沒有找到 '{calc_type}'.")

    def get_last_ts_data(self):
        if not self.data:
            return {}
        
        code = self.item['code']
        result = {}

        # code 總是陣列格式，例如 ['2317', '2330']
        codes = code if isinstance(code, list) else [code]

        # 遍歷所有 code
        for c in codes:
            # 確保 c 是字符串
            c = str(c)

            # 從 self.data 中獲取該 code 的資料
            # self.data 是字典，鍵是 code，值是該 code 的資料列表
            code_data = self.data.get(c, [])

            if code_data:
                # 按時間戳從新到舊排序
                sorted_data = sorted(
                    code_data, 
                    key=lambda x: datetime.strptime(x['ts'], '%Y-%m-%d %H:%M:%S'), 
                    reverse=True
                )

                # 分別找出有 tick 和 bidask 的最新數據
                latest_tick = None
                latest_bidask = None

                for entry in sorted_data:
                    if not latest_tick and entry.get('tick') and entry['tick']:
                        latest_tick = entry['tick']
                    if not latest_bidask and entry.get('bidask') and entry['bidask']:
                        latest_bidask = entry['bidask']
                    if latest_tick and latest_bidask:
                        break

                # 組合結果
                result[c] = {
                    'ts': sorted_data[0]['ts'],  # 使用最新時間戳
                    'tick': latest_tick if latest_tick else [],
                    'bidask': latest_bidask if latest_bidask else []
                }

        # 如果只有一個 code，返回該 code 的結果；否則返回整個字典
        return result[codes[0]] if len(codes) == 1 else result

    def build_position_control(self):
        self.position_controls = self.position_controls[self.params['position_type']](take_profit=self.profit_stop, stop_loss=self.stop_loss, tick_size=self.tick_size, symbol=self.symbol, redis_key=self.position_redis_key)
        return

    def execute_position_control(self, type, **params):
        if hasattr(self, 'position_controls'):
            self.log.info(f"當前策略倉位為: {self.params['position_type']}")
            position_data = self.position_controls.execute(type, **params)
            if not position_data: return {}
            return position_data
        else:
            self.log.error("尚未定義倉位控制")

    def nothing_order(self): # 什麼都不做(沒下單, 也沒要推播)
        self.order.extend([(self.symbol, self.item, False, {}, {}, {})])
        return self.order

    def split_code_to_str(self, code):
        return ", ".join(code)

    def create_order(self, code, quantity, price, symbol, broker, order_type=None, comm_tax=None, capital=None, pl=None, trade_id=None):
        return {
            'code': code,
            'quantity': quantity,
            'price': price,
            'symbol': symbol,
            'broker': broker,
            'order_type': order_type or ({'order_type': "IOC", 'price_type': "MKT", 'order_lot': "Common"} if symbol == 'stock' else {'order_type': "IOC", 'price_type': "MKT", 'octype': "Auto"}),
            'position_key': self.position_redis_key,
            'analyze_key': self.analyze_redis_key,
            'commission_tax': comm_tax or {'comm': 0, 'tax': 0, 'tick_size': 0, 'levearge': 0, 'trading_symbol': self.symbol},
            'capital': (capital or 10000),
            'strategy': self.item['strategy'],
            'position_type': {
                'class_name': self.params['position_type'],
                'params': {
                    'take_profit': self.profit_stop,
                    'stop_loss': self.stop_loss,
                    'tick_size': self.tick_size,
                    'symbol': self.symbol,
                    'redis_key': self.position_redis_key
                }
            },
            'profit': (pl or {'profit': 0, 'loss': 0})['profit'],
            'loss': (pl or {'profit': 0, 'loss': 0})['loss'],
            'trade_id': trade_id or str(uuid.uuid4())
        }

    def force_close(self, data_time, trading_periods): # 強制平倉, 搭配參數(資料時間, [預計平倉時間])
        check_t = data_time.time()
        for period_start, period_end in trading_periods:
            if period_start <= period_end:# 普通時段（不跨日）
                if period_start <= check_t <= period_end:
                    return False  # 在交易時段內 → 不觸發平倉
            else:# 跨日時段（如 15:00-次日5:00）
                if check_t >= period_start or check_t <= period_end:
                    return False  # 在交易時段內 → 不觸發平倉
        return True  # 非交易時段 → 觸發平倉

    @abstractmethod
    def execute(self):
        """執行艙位控制的邏輯: 回傳參數
            1.是否下單(
                0: 取消單
                1:多(Buy), -1:空(Sell), 
                2:多倉止損(Sell), -2:空倉止損(Buy),
                3:多倉止盈(Sell), -3:空倉止盈(Buy),
                4:多倉平倉(Sell), -4:空倉平倉(Buy),
                5:動態多倉改價, -5:動態空倉改價
                True:監控價額與自定義行為
            )
            2.修改商品參數(setting.json的params)
            3.DC推播內容
            4.訂單參數(
                code: 代號,
                quantity': 數量,
                price': 價格,
                symbol': 商品種類(stock, future..),
                broker': 卷商,
                order_type': 訂單類型,
                position_key: Redis key
            )
        """
        pass
    
    @abstractmethod
    def entry(self):
        """抽象方法，生成訊號, 推播訊息"""
        pass
