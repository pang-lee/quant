from data.broker.load import load_datasources
import threading, os, time
from distutils.util import strtobool
from db.redis import set_redis_consumer
from collections import defaultdict
import pandas as pd

class DatasourceFactory:
    _datasource_classes = None  # 存放資料源類別字典
    _datasources_loaded = False  # 標記是否已加載資料源
    _datasource_instance = {} # 存放資料源實例

    @staticmethod
    def _ensure_datasources_loaded():
        """確保只加載資料源一次"""
        if not DatasourceFactory._datasources_loaded:
            DatasourceFactory._datasource_classes = load_datasources()
            DatasourceFactory._datasources_loaded = True

    @staticmethod
    def create_datasource(name, product, brokers):
        if name not in DatasourceFactory._datasource_classes:
            raise ValueError(f"Unknown datasource: {name}")

        # 創建資料源實例並調用方法
        datasource_class = DatasourceFactory._datasource_classes[name]
        datasoruce_instance = datasource_class(brokers)
        DatasourceFactory._datasource_instance[name] = datasoruce_instance
        return datasoruce_instance.fetch_market_data(product)

    # -------------- 資料行情訂閱 --------------------
    @staticmethod
    def run_data_sources(symbols, brokers):
        # 過濾掉空陣列的 key
        filtered_symbols = {k: v for k, v in symbols.items() if v}

        # 實盤行情資料
        set_redis_consumer(filtered_symbols)
        DatasourceFactory._ensure_datasources_loaded()
        
        # 提取需要訂閱的項目
        shioaji_subscription = []
        # 提取有效的 datasource 並生成數據源
        for key, items in filtered_symbols.items():
            for item in items:
                datasource_type = item['params'].get('datasource', None)
                symbol_codes = item.get('code', [])
                night = item['params'].get('night', False)

                if not datasource_type:
                    raise ValueError(f"{item}: 缺少 datasource 參數")

                # 為每個 code 建立數據源
                for symbol_code in symbol_codes:
                    if datasource_type == "shioaji":
                        shioaji_subscription.append((key, symbol_code, night))

                    else:# 其他數據源處理邏輯, 這裡需要根據實際需求實現其他數據源的處理邏輯
                        pass

        if shioaji_subscription: # 啟動執行緒來處理 Shioaji 訂閱
            thread = threading.Thread(target=DatasourceFactory.handle_shioaji_subscription, args=(list(set(shioaji_subscription)), brokers))
            thread.daemon = True
            thread.start()

        return DatasourceFactory._datasource_instance

    # -------------- 永豐行情訂閱 --------------------
    @staticmethod
    def handle_shioaji_subscription(subscriptions, brokers):
        print(f"訂閱 Shioaji 行情數據: {subscriptions}\n當前模擬模式: {bool(strtobool(os.getenv('IS_DEV', 'true')))}")

        # 參數(資料來源, 訂閱商品, 是否為模擬單)
        DatasourceFactory.create_datasource("ShioajiDataSource", subscriptions, brokers)

        while True: # Shioaji 訂閱
            time.sleep(1)

    @staticmethod
    def aggregate_ticks_by_second(tick_data):
        """
        實際運行交易的實盤中, 將 tick_data 依照相同秒數進行合併，回傳合併後的 tick 資料
        """
        tick_buffer = defaultdict(list)

        # 整理 tick_data，依照 timestamp 分組
        for tick in tick_data:
            ts = pd.to_datetime(tick['ts']).floor('s')  # 轉換為秒級別時間戳
            tick_buffer[ts].append(tick)

        aggregated_ticks = []

        for ts, ticks in tick_buffer.items():
            aggregated_tick = {
                'ts': ts.strftime('%Y-%m-%d %H:%M:%S'),
                'code': ticks[0]['code'],  # 假設相同秒數內都是相同 code
                'close': ticks[-1]['close'],  # 取最後一筆 close
                'high': max(t['high'] for t in ticks),
                'low': min(t['low'] for t in ticks),
                'volume': sum(int(t['volume']) for t in ticks),
                'bid_price': tuple(sorted(set(t['bid_side_total_vol'] for t in ticks if t['bid_side_total_vol'] != 0))),
                'bid_volume': sum(int(t['bid_side_total_vol']) for t in ticks),
                'ask_price': tuple(sorted(set(t['ask_side_total_vol'] for t in ticks if t['ask_side_total_vol'] != 0))),
                'ask_volume': sum(int(t['ask_side_total_vol']) for t in ticks),
                'tick_type': DatasourceFactory.analyze_tick_types([t['tick_type'] for t in ticks], type='list')  # 計算 tick_type
            }

            aggregated_ticks.append(aggregated_tick)

        return aggregated_ticks
        
    @staticmethod
    def analyze_tick_types(tick_types, type='list'):
        """
        分析該秒內的成交類型分布
        :param tick_types: Series, 該秒內的 tick_type 列表
        :return: dict, 包括內盤、外盤成交數量及主要成交方向
        """
        if type == "pandas":
            tick_types = tick_types.tolist()  # 轉換為列表（回測用 Pandas）
        
        outer_trades = tick_types.count(1)  # 外盤成交數量
        inner_trades = tick_types.count(-1)  # 內盤成交數量
        net_trades = outer_trades - inner_trades  # 淨成交量
        dominant = "外盤" if net_trades > 0 else "內盤" if net_trades < 0 else "均衡"
        return {
            "outer_trades": outer_trades,
            "inner_trades": inner_trades,
            "dominant": dominant
        }
    
    @staticmethod
    def calculate_ohlcv_from_data(data):
        # 計算 OHLCV
        ohlcv = {}
        ohlcv['ts'] = data[0]['ts']
        ohlcv['open'] = data[0]['close']  # 開盤價
        ohlcv['close'] = data[-1]['close']  # 收盤價
        ohlcv['high'] = max(record['close'] for record in data)  # 最高價
        ohlcv['low'] = min(record['close'] for record in data)  # 最低價
        ohlcv['volume'] = sum(int(record['volume']) for record in data)  # 成交量
        return ohlcv