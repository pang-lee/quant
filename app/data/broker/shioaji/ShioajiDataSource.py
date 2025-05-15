import json
from data.broker.abc.AbstractDatasource import AbstractDatasource
from broker.broker.shioaji.verify.shioaji import get_shioaji_instance
from shioaji import TickFOPv1, TickSTKv1, Exchange, BidAskFOPv1, BidAskSTKv1
from decimal import Decimal
import shioaji as sj
from utils.log import get_module_logger
from dotenv import load_dotenv
load_dotenv()

class ShioajiDataSource(AbstractDatasource):
    def __init__(self, simulation=True):
        super().__init__()
        self.api = get_shioaji_instance(simulation=simulation)
        self.log = get_module_logger('data/shioaji_data')

    def fetch_market_data(self, symbol, code):
        self.subscribe(symbol=symbol, code=code)
        try:
            usage = self.api.usage()
            self.log.info(f"剩餘可用API: {usage}")
        except TimeoutError as e:
            self.log.warning(f"無法獲得 API 使用量: {e}")

    def subscribe(self, symbol, code):
        if symbol == 'stock':
            self.subscribe_stock(code)
        elif symbol == 'index':
            self.subscribe_index(code)
        elif symbol == 'future':
            self.subscribe_future(code)
        elif symbol == 'option':
            self.subscribe_option(code)
        
    # ---------------------------- 行情訂閱 ----------------------------
    def subscribe_stock(self, code):
        try:
            self.api.quote.subscribe(
                self.api.Contracts.Stocks[code],
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )
            
            self.api.quote.subscribe(
                self.api.Contracts.Stocks[code],
                quote_type = sj.constant.QuoteType.BidAsk,
                version = sj.constant.QuoteVersion.v1
            )
        
            self.log.info(f"Subscribed to stock: {code} in shioaji client")
            
            self.api.quote.set_on_bidask_stk_v1_callback(
                lambda exchange, tick: self.process_stock_bidask(exchange, tick)
            )
            
            return self.api.quote.set_on_tick_stk_v1_callback(
                lambda exchange, tick: self.process_stock_tick(exchange, tick)
            )
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
            self.api.quote.subscribe(
                self.api.Contracts.Futures[code],
                quote_type=sj.constant.QuoteType.Tick,
                version=sj.constant.QuoteVersion.v1
            )
            
            self.api.quote.subscribe(
                self.api.Contracts.Futures[code],
                quote_type = sj.constant.QuoteType.BidAsk,
                version = sj.constant.QuoteVersion.v1
            )

            self.log.info(f"Subscribed to future: {code} in shioaji client")
                        
            self.api.quote.set_on_bidask_fop_v1_callback(
                lambda exchange, tick: self.process_future_bidask(exchange, tick, code)
            )
            
            return self.api.quote.set_on_tick_fop_v1_callback(
                lambda exchange, tick: self.process_future_tick(exchange, tick, code)
            )
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
        if tick.simtrade == True or tick.suspend == True:
            self.log.info(f"股票資料為試搓{tick.simtrade}或停牌{tick.suspend}: {tick.code}")
            return
        
        # XADD: 新增一個 Stream 條目
        return self.redis.xadd(f'shioaji_stock_{tick.code}_stream', {
            'ts': tick.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保 datetime 轉為 ISO 格式的字符串
            'code': tick.code,
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
        if bidask.simtrade == True or bidask.suspend == True:
            self.log.info(f"股票五檔資料為試搓{bidask.simtrade}或停牌{bidask.suspend}: {bidask.code}")
            return

        # 轉換數據格式，確保 Decimal 數據存儲時是字符串
        bid_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.bid_price]
        bid_volumes = [volume for volume in bidask.bid_volume]
        diff_bid_vols = [diff for diff in bidask.diff_bid_vol]

        ask_prices = [str(price) if isinstance(price, Decimal) else price for price in bidask.ask_price]
        ask_volumes = [volume for volume in bidask.ask_volume]
        diff_ask_vols = [diff for diff in bidask.diff_ask_vol]

        # 存入 Redis Stream
        return self.redis.xadd(f'shioaji_stock_{bidask.code}_bidask_stream', {
            'ts': bidask.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保格式
            'code': bidask.code,
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
    
    def process_future_tick(self, exchange: Exchange, tick: TickFOPv1, code):
        if tick.simtrade == True:
            self.log.info(f"期貨資料為試搓{tick.simtrade}: {code}")
            return
        
        # XADD: 新增一個 Stream 條目
        return self.redis.xadd(f'shioaji_future_{code}_stream', {
            'ts': tick.datetime.strftime('%Y-%m-%d %H:%M:%S'),  # 確保 datetime 轉為 ISO 格式的字符串
            'code': tick.code,
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

    def process_future_bidask(self, exchange:Exchange, bidask:BidAskFOPv1, code):
        if bidask.simtrade == True:
            self.log.info(f"期貨五檔資料為試搓{bidask.simtrade}: {bidask.code}")
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
            'code': bidask.code,
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
