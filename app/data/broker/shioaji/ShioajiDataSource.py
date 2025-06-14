import json, pytz
from datetime import datetime, time
from data.broker.abc.AbstractDatasource import AbstractDatasource
from shioaji import TickFOPv1, TickSTKv1, Exchange, BidAskFOPv1, BidAskSTKv1
from decimal import Decimal
import shioaji as sj
from utils.log import get_module_logger
from dotenv import load_dotenv
load_dotenv()

class ShioajiDataSource(AbstractDatasource):
    def __init__(self, brokers):
        super().__init__()
        self.api = brokers['shioaji'].api
        self.log = get_module_logger('data/shioaji_data')
        self.subscribe_product = None
        self._init_callbacks()

    def _init_callbacks(self):
        """初始化報價回調"""
        try:
            self.code_mapping = {}  # 交易所代號 (e.g., MXFR5) -> 原始代號 (e.g., TMFR1)
            self.api.quote.set_on_tick_fop_v1_callback(self.process_future_tick)
            self.api.quote.set_on_bidask_fop_v1_callback(self.process_future_bidask)
            self.api.quote.set_on_tick_stk_v1_callback(self.process_stock_tick)
            self.api.quote.set_on_bidask_stk_v1_callback(self.process_stock_bidask)
            self.log.info("Shioaji callbacks 設定完成")
        except Exception as e:
            self.log.error(f"callbacks 設定失敗: {e}")

    def reinit_api(self, client):
        """從外部重新初始化單例的 api"""
        try:
            self.log.info("ShioajiDataSource - 重新設定shioaji連線")
            self.api = client.api
            self._init_callbacks()  # 重新設定 callbacks
            self.fetch_market_data(self.subscribe_product)
            self.log.info("ShioajiDataSource - 新shioaji連線完成")
        except Exception as e:
            self.log.error(f"ShioajiDataSource - 重新設定Shioaji失敗: {e}")

    def night_filter(self):
        # 獲取當前時間（考慮時區）
        current_time = datetime.now(pytz.timezone("Asia/Taipei")).time()
        afternoon_2pm = time(14, 0)  # 下午 2:00
        morning_6am = time(6, 0)    # 清晨 6:00
    
        # 檢查是否在晚上範圍（當天 14:00 到隔天 06:00）
        if current_time >= afternoon_2pm or current_time < morning_6am:
            return True
        return False

    def fetch_market_data(self, product):
        if not self.subscribe_product:
            self.subscribe_product = product

        if self.night_filter(): # 如果當前時間超過下午2點，過濾掉第三個參數 (night) 為 False 的項目
            filtered_product = [item for item in self.subscribe_product if item[2] is True]
            self.log.info(f"當前時間已進入夜盤, 當前要訂閱的商品列表: {filtered_product}")
        else: # 如果未超過下午2點，保留原始 List
            filtered_product = self.subscribe_product
            self.log.info(f"當前時間為日盤時段, 當前要訂閱的商品列表: {filtered_product}")

        for item in filtered_product:
            symbol, code, _ = item
            self.subscribe(symbol=symbol, code=code)
            
        try:
            usage = self.api.usage()
            self.log.info(f"剩餘可用API: {usage}\n")
        except TimeoutError as e:
            self.log.warning(f"無法獲得 API 使用量: {e}\n")

        return

    def subscribe(self, symbol, code):
        try:
            if symbol == 'stock':
                self.subscribe_stock(code)
            elif symbol == 'index':
                self.subscribe_index(code)
            elif symbol == 'future':
                self.subscribe_future(code)
            elif symbol == 'option':
                self.subscribe_option(code)

        except Exception as e:
            self.log.error(f"訂閱 {symbol}: {code} 失敗: {e}")

    # ---------------------------- 行情訂閱 ----------------------------
    def subscribe_stock(self, code):
        try:
            # 儲存交易所代號到原始代號的映射
            contract = self.api.Contracts.Stocks[code]
            self.code_mapping[contract.code] = code

            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )
            
            self.api.quote.subscribe(
                contract,
                quote_type = sj.constant.QuoteType.BidAsk,
                version = sj.constant.QuoteVersion.v1
            )
            
            return
        except Exception as e:
            self.log.error(f'The Error occur in subscribe stock: {e}')

    def subscribe_index(self, code):
        try:
            self.api.quote.subscribe(
                self.api.Contracts.Indexs.TSE[code],
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )
            self.log.info(f"Subscribed to index: {code['code']} in shioaji client")
        except Exception as e:
            self.log.error(f'The Error occur in subscribe index: {e}')
        
    def subscribe_future(self, code):
        try:
            # 儲存交易所代號到原始代號的映射
            contract = self.api.Contracts.Futures[code]
            self.code_mapping[contract.target_code] = code
            
            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )

            self.api.quote.subscribe(
                contract,
                quote_type=sj.constant.QuoteType.BidAsk,
                version=sj.constant.QuoteVersion.v1
            )
        
            return
        except Exception as e:
            self.log.error(f"The Error occur in subscribe future: {e}")
        
    def subscribe_option(self, code):
        try:
            self.api.quote.subscribe(
                self.api.Contracts.Options[code],
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )
            self.log.info(f"Subscribed to option: {code} in shioaji client")
        except Exception as e:
            self.log.error(f'The Error occur in subscribe option: {e}')
        
    def process_stock_tick(self, exchange: Exchange, tick: TickSTKv1):
        code = self.code_mapping.get(tick.code, tick.code)
        
        if tick.simtrade == True or tick.suspend == True:
            self.log.info(f"股票資料(tick)為試搓{tick.simtrade}或停牌{tick.suspend}: {code}")
            return

        # XADD: 新增一個 Stream 條目
        return self.redis.xadd(f'shioaji_stock_{code}_stream', {
            'ts': tick.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保 datetime 轉為 ISO 格式的字符串
            'code': code,
            'open': str(tick.open) if isinstance(tick.open, Decimal) else tick.open,
            'close': str(tick.close) if isinstance(tick.close, Decimal) else tick.close,
            'high': str(tick.high) if isinstance(tick.high, Decimal) else tick.high,
            'low': str(tick.low) if isinstance(tick.low, Decimal) else tick.low,
            'volume': tick.volume,
            'total_volume': tick.total_volume,
            'amount': str(tick.amount) if isinstance(tick.amount, Decimal) else tick.amount,
            'total_amount': str(tick.total_amount) if isinstance(tick.total_amount, Decimal) else tick.total_amount,
            'tick_type': tick.tick_type,
            'chg_type': tick.chg_type,
            'price_chg': str(tick.price_chg) if isinstance(tick.price_chg, Decimal) else tick.price_chg,
            'percent_chg': round(float(tick.pct_chg), 2),  # 確保百分比是浮點數並保留兩位小數
            'simtrade': tick.simtrade,
            'suspend': tick.suspend,
            'intraday_odd': tick.intraday_odd,
            'bid_side_total_vol': tick.bid_side_total_vol,
            'ask_side_total_vol': tick.ask_side_total_vol,
            'bid_side_total_cnt': tick.bid_side_total_cnt,
            'ask_side_total_cnt': tick.ask_side_total_cnt,
            'closing_oddlot_shares': tick.closing_oddlot_shares,
            'fixed_trade_vol': tick.fixed_trade_vol
        })
        
    def process_stock_bidask(self, exchange:Exchange, bidask:BidAskSTKv1):
        code = self.code_mapping.get(bidask.code, bidask.code)
        
        if bidask.simtrade == True or bidask.suspend == True:
            self.log.info(f"股票五檔(bidask)資料為試搓{bidask.simtrade}或停牌{bidask.suspend}: {code}")
            return
 
        # 轉換數據格式，確保 Decimal 數據存儲時是字符串
        bid_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.bid_price]
        bid_volumes = [volume for volume in bidask.bid_volume]
        diff_bid_vols = [diff for diff in bidask.diff_bid_vol]

        ask_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.ask_price]
        ask_volumes = [volume for volume in bidask.ask_volume]
        diff_ask_vols = [diff for diff in bidask.diff_ask_vol]

        # 存入 Redis Stream
        return self.redis.xadd(f'shioaji_stock_{code}_bidask_stream', {
            'ts': bidask.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保格式
            'code': code,
            'exchange': str(exchange),
            'bid_prices': json.dumps(bid_prices),  # JSON 字符串存儲
            'bid_volumes': json.dumps(bid_volumes),
            'diff_bid_vols': json.dumps(diff_bid_vols),  # 委買變化量
            'ask_prices': json.dumps(ask_prices),
            'ask_volumes': json.dumps(ask_volumes),
            'diff_ask_vols': json.dumps(diff_ask_vols),  # 委賣變化量
            'suspend': bidask.suspend,  # 停牌資訊
            'simtrade': bidask.simtrade,  # 是否為模擬交易
            'intraday_odd': bidask.intraday_odd  # 是否為盤中零股交易
        })
    
    def process_future_tick(self, exchange: Exchange, tick: TickFOPv1):
        code = self.code_mapping.get(tick.code, tick.code)

        if tick.simtrade == True:
            self.log.info(f"期貨資料(tick)為試搓{tick.simtrade}: {code}")
            return

        # XADD: 新增一個 Stream 條目
        return self.redis.xadd(f'shioaji_future_{code}_stream', {
            'ts': tick.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保 datetime 轉為 ISO 格式的字符串
            'code': code,
            'open': str(tick.open) if isinstance(tick.open, Decimal) else tick.open,
            'close': str(tick.close) if isinstance(tick.close, Decimal) else tick.close,
            'high': str(tick.high) if isinstance(tick.high, Decimal) else tick.high,
            'low': str(tick.low) if isinstance(tick.low, Decimal) else tick.low,
            'volume': tick.volume,
            'total_volume': tick.total_volume,
            'amount': str(tick.amount) if isinstance(tick.amount, Decimal) else tick.amount,
            'total_amount': str(tick.total_amount) if isinstance(tick.total_amount, Decimal) else tick.total_amount,
            'tick_type': tick.tick_type,
            'chg_type': tick.chg_type,
            'price_chg': str(tick.price_chg) if isinstance(tick.price_chg, Decimal) else tick.price_chg,
            'percent_chg': round(float(tick.pct_chg), 2),  # 確保百分比是浮點數並保留兩位小數
            'simtrade': tick.simtrade,
            'ask_side_total_vol': tick.ask_side_total_vol,
            'bid_side_total_vol': tick.bid_side_total_vol,
            'avg_price': str(tick.avg_price) if isinstance(tick.avg_price, Decimal) else tick.avg_price,
            'underlying_price': str(tick.underlying_price) if isinstance(tick.underlying_price, Decimal) else tick.underlying_price
        })

    def process_future_bidask(self, exchange:Exchange, bidask:BidAskFOPv1):
        code = self.code_mapping.get(bidask.code, bidask.code)

        if bidask.simtrade == True:
            self.log.info(f"期貨五檔(bidask)資料為試搓{bidask.simtrade}: {code}")
            return

        # 轉換數據格式，確保 Decimal 數據存儲時是字符串
        bid_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.bid_price]
        bid_volumes = [volume for volume in bidask.bid_volume]
        diff_bid_vols = [diff for diff in bidask.diff_bid_vol]

        ask_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.ask_price]
        ask_volumes = [volume for volume in bidask.ask_volume]
        diff_ask_vols = [diff for diff in bidask.diff_ask_vol]

        # 存入 Redis Stream
        return self.redis.xadd(f'shioaji_future_{code}_bidask_stream', {
            'ts': bidask.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保格式
            'code': code,
            'bid_total_vol': bidask.bid_total_vol,  # 委買總量
            'ask_total_vol': bidask.ask_total_vol,  # 委賣總量
            'bid_prices': json.dumps(bid_prices),  # 存 JSON 字符串
            'bid_volumes': json.dumps(bid_volumes),
            'diff_bid_vols': json.dumps(diff_bid_vols),  # 委買變化量
            'ask_prices': json.dumps(ask_prices),
            'ask_volumes': json.dumps(ask_volumes),
            'diff_ask_vols': json.dumps(diff_ask_vols),  # 委賣變化量
            'first_derived_bid_price': str(bidask.first_derived_bid_price) if isinstance(bidask.first_derived_bid_price, Decimal) else bidask.first_derived_bid_price,
            'first_derived_ask_price': str(bidask.first_derived_ask_price) if isinstance(bidask.first_derived_ask_price, Decimal) else bidask.first_derived_ask_price,
            'first_derived_bid_vol': bidask.first_derived_bid_vol,
            'first_derived_ask_vol': bidask.first_derived_ask_vol,
            'underlying_price': str(bidask.underlying_price) if isinstance(bidask.underlying_price, Decimal) else bidask.underlying_price,
            'simtrade': bidask.simtrade,  # 是否為模擬交易
        })
