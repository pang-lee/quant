from .abc.AbstractStrategy import AbstractStrategy
from datetime import datetime, time, timedelta
import pandas as pd
from utils.k import convert_ohlcv
import json

class Tmfrsmc(AbstractStrategy):
    def __init__(self, datas, item, symbol):
        super().__init__(datas, item, symbol, 'profit_ratio1', 'stop_ratio1')
        self.last_1min_k = None if super().get_from_redis(f"last_k_1min_{self.item['code'][0]}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_1min_{self.item['code'][0]}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
        self.current_position1 = None
        
        # k棒VWAP計算時間窗口
        self.window_series = [
            {'timeframe_window': self.params['window_4h'], 'timeframe': '4hr'},
            {'timeframe_window': self.params['window_15m'], 'timeframe': '15min'},
            {'timeframe_window': self.params['window_5m'], 'timeframe': '5min'}
        ]
        self.tuple_results = []
        
    def load_k(self):
        k_amount = self.lrange_of_redis(self.redis_k_key, 0, -1)  # 取出所有資料

        if not k_amount:  # 如果 Redis 沒有資料，返回 0
            self.log.info("當前redis無法取得k_amount")
            return (False)

        # 將 JSON 字串轉為 Python 物件
        self.k_data = [json.loads(record) for record in k_amount]
        start_time = (self.current_time - timedelta(days=1)).replace(hour=8, minute=45, second=0, microsecond=0)
        
        # 轉換為 Pandas DataFrame
        k_df = pd.DataFrame(self.k_data)

        # 將 'ts' 欄位轉為 datetime 格式，並確保時區一致
        k_df['ts'] = pd.to_datetime(k_df['ts']).dt.tz_localize(self.tz)
        
        # 過濾時間範圍：從昨天 08:45 到當前時刻
        k_df = k_df[(k_df['ts'] >= start_time) & (k_df['ts'] <= self.current_time)]

        # 如果沒有符合時間範圍的資料，返回 0
        if k_df.empty:
            self.log.info("當前取出的k棒資料, 無法過濾出近期一天的K棒")
            return (False)
        
        k_df.set_index('ts', inplace=True)
        latest_k_ts = k_df.index[-1].to_pydatetime()
        
        if self.last_1min_k is None:
            return super().save_to_redis(f"last_k_1min_{self.item['code'][0]}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')

        if latest_k_ts != self.last_1min_k:
            super().save_to_redis(f"last_k_1min_{self.item['code'][0]}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')
        
            data1 = convert_ohlcv(k_df, self.params['k_time_long'])
            data2 = convert_ohlcv(k_df, self.params['k_time_middle'])
            data3 = convert_ohlcv(k_df, self.params['k_time_short'])
            
            return (data1, data2, data3)
        
        return (False)

    def check_position(self):
        code1 = self.item['code'][0]
        strategy_order_info = self.execute_position_control('check') or {}
        self.current_position1 = strategy_order_info.get(code1, {})

        # 判斷是否有未完成的訂單或有倉位
        has_pending_orders1 = 'pending_orders' in self.current_position1 and bool(self.current_position1['pending_orders'])
        has_position1 = 'position' in self.current_position1 and 'symbol' in self.current_position1['position'] and 'quantity' in self.current_position1['position']
        has_any_activity1 = has_pending_orders1 or has_position1

        # 輸出詳細狀態
        self.log.info("倉位檢查結果")
        self.log.info(f"Position1 ({code1}): 有無未完成訂單: {has_pending_orders1}, 有無持倉: {has_position1}")

        return has_any_activity1
    
    def check_exit_conditions(self):
        """檢查止損/止盈條件"""
        pos1_dict = self.current_position1.get('position', {})
        position1 = int(pos1_dict.get('position', 0))
        take_profit1, stop_loss1 = int(pos1_dict.get('profit', 0)), int(pos1_dict.get('loss', 0))
        origin_price1, capital1 = int(pos1_dict.get('origin', 0)), int(pos1_dict.get('capital', self.params['capital1']))
        
        code1 = self.item['code'][0]
        ts1 = self.last_data['ts']
        price1 = float(self.last_data['tick'][0]['close'])
        data_time = datetime.strptime(ts1, "%Y-%m-%d %H:%M:%S")
        trading_periods = [
            (time(8, 45), time(13, 44)),# 上午时段：8:45 - 13:45
            (time(15, 0), time(23, 59, 59)), # 下午到隔日凌晨时段：15:00 至次日 5:00
            (time(0, 0), time(4, 59)) #（需拆解为两段）
        ]

        if position1 > 0: # 多倉
            pl1 = round(((price1 - origin_price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price1 * self.params['tax1']) + (price1 * self.params['tax1']))), 2)
            
            if self.force_close(data_time, trading_periods): # 判斷是否超時平倉
                self.log.info(f"當前商品{code1}已經超時要平倉, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '多倉超時平倉通知(尚未下單)',
                    'description': f"SMC多倉平倉 {code1} 賣出",
                    'pl': pl1,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                return self.order
            
            elif price1 <= stop_loss1:  # 觸發止損(多倉賣出)
                self.log.info(f"當前多倉位止損, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.entry(2, **{
                    'code': code1,
                    'current_price': price1,
                    'pl': pl1,
                    'share_per_trade': self.params['share_per_trade1'],
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'capital': capital1
                })
                    
                return self.order
            
            elif price1 >= take_profit1:  # 觸發止盈動態更新價位
                new_profit, new_loss = self.execute_position_control('calculate', **{'action': 'long', 'current_price': price1})  # 重設止盈止損
                self.entry(5, **{
                    'code': code1,
                    'ts': ts1,
                    'share_per_trade': self.params['share_per_trade1'],
                    'current_price': price1,
                    'profit': new_profit,
                    'loss': new_loss,
                    'capital': capital1
                })

                strategy_order_info['position']['profit'] = new_profit
                strategy_order_info['position']['loss'] = new_loss
                strategy_order_info['position']['origin'] = stock_price1

                # 新止盈價位回寫redis
                self.execute_position_control('set', **{
                    'key': self.position_redis_key,
                    'data': {f'{code1}': strategy_order_info}
                })
                    
                self.log.info(f"當前多倉位動態價格更新, 舊止盈:{take_profit1}, 舊止損:{stop_loss1}, 新止盈:{new_profit}, 新止損:{new_loss}, 原始價格:{origin_price1}, 當前價格:{price1}")
                return self.order

        elif position1 < 0: # 空倉
            pl1 = round(((origin_price1 - price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price1 * self.params['tax1']) + (price1 * self.params['tax1']))), 2)
            
            if self.force_close(data_time, trading_periods):
                self.log.info(f"當前商品{code1}已經超時要平倉, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(-4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '多倉超時平倉通知(尚未下單)',
                    'description': f"SMC多倉平倉 {code1} 賣出",
                    'pl': pl1,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                return self.order
            
            elif price1 >= stop_loss1:  # 觸發止損(空倉買回)
                self.log.info(f"當前空倉位止損, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.entry(-2, **{
                    'code': code1,
                    'current_price': price1,
                    'pl': pl1,
                    'share_per_trade': self.params['share_per_trade1'],
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'capital': capital1
                })

                return self.order

            elif price1 <= take_profit1:  # 觸發止盈動態更新價位
                new_profit, new_loss = self.execute_position_control('calculate', **{'action': 'short', 'current_price': price1})  # 重設止盈止損
                self.entry(-5, **{
                    'code': code1,
                    'ts': ts1,
                    'share_per_trade': self.params['share_per_trade1'],
                    'current_price': price1,
                    'profit': new_profit,
                    'loss': new_loss,
                    'capital': capital1
                })
                    
                strategy_order_info['position']['profit'] = new_profit
                strategy_order_info['position']['loss'] = new_loss
                strategy_order_info['position']['origin'] = stock_price1
                    
                # 新止盈價位回寫redis
                self.execute_position_control('set', **{
                    'key': self.position_redis_key,
                    'data': {f'{code1}': strategy_order_info}
                })

                self.log.info(f"當前空倉位動態價格更新, 舊止盈:{take_profit1}, 舊止損:{stop_loss1}, 新止盈:{new_profit}, 新止損:{new_loss}, 原始價格:{origin_price1}, 當前價格:{price1}")
                return self.order

        self.log.info("當前甚麼也沒觸發(調價, 止損, 平倉), 等待下一次檢查")
        return False

    def publish_order(self, action, **params):
        if action == 1: # 多單
            publish = {
                'title': '可進場通知(尚未下單)',
                'description': f"SMC進場: {params.get('code')}做多",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '代號': params.get('code'),
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '數量': params.get('share_per_trade'),
                    '當前點數': params.get('current_price'),
                    'OB價位高低點': f"Top: {self.params['ob_top']} ~ Bottom: {self.params['ob_bottom']}",
                    '4HR方向VWAP價位': f"{self.params['direction']}/{params.get('4hr_vwap')}",
                    '15分K收盤價/VWAP價位': f"{params.get('15min_close')}/{params.get('15min_vwap')}",
                    '5分K收盤價/VWAP價位': f"{params.get('5min_close')}/{params.get('5min_vwap')}",
                    '5分K/VWAP標準差(2倍)': params.get('5min_std'),
                    '進場類型': '多',
                    '動態止盈點數': params.get('profit_ratio'),
                    '止損點數': params.get('stop_ratio'),
                    '當前資產': params.get('capital')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=params.get('share_per_trade'), 
                price=params.get('current_price'),
                symbol=self.symbol,
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, 1, {}, publish, order)])

        elif action == -1: # 空單
            publish = {
                'title': '可進場通知(尚未下單)',
                'description': f"SMC進場: {params.get('code')}做空",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '代號': params.get('code'),
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': params.get('share_per_trade'),
                    '當前點數': params.get('current_price'),
                    'OB價位高低點': f"Top: {self.params['ob_top']} ~ Bottom: {self.params['ob_bottom']}",
                    '4HR方向VWAP價位': f"{self.params['direction']}/{params.get('4hr_vwap')}",
                    '15分K收盤價/VWAP價位': f"{params.get('15min_close')}/{params.get('15min_vwap')}",
                    '5分K收盤價/VWAP價位': f"{params.get('5min_close')}/{params.get('5min_vwap')}",
                    '5分K/VWAP標準差(2倍)': params.get('5min_std'),
                    '進場類型': '空',
                    '動態止盈點數': params.get('profit_ratio'),
                    '止損點數': params.get('stop_ratio'),
                    '當前資產': params.get('capital')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=params.get('share_per_trade'), 
                price=params.get('current_price'),
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, -1, {}, publish, order)])

        elif action == 4: # 多倉平倉
            publish = {
                'title': params.get('title'),
                'description': params.get('description'),
                'footer': f'{self.symbol}',
                'color': 0x32CD32,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '止盈': params.get('profit'),
                    '止損': params.get('loss'),
                    '數量': params.get('share_per_trade'),
                    '預估盈虧': round(params.get('pl'), 2),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=params.get('share_per_trade'), 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, 4, {}, publish, order)])

        elif action == -4: # 空倉平倉
            publish = {
                'title': params.get('title'),
                'description': params.get('description'),
                'footer': f'{self.symbol}',
                'color': 0x32CD32,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '止盈': params.get('profit'),
                    '止損': params.get('loss'),
                    '數量': params.get('share_per_trade'),
                    '預估盈虧': round(params.get('pl'), 2),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=params.get('share_per_trade'), 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, -4, {}, publish, order)])
        
        if action == 2: # 止損多倉
            publish = {
                'title': '多倉止損通知(尚未下單)',
                'description': f"SMC多倉止損: {params.get('code')}賣出",
                'footer': f'{self.symbol}',
                'color': 0xFF0000,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '原先止盈': params.get('profit'),
                    '原先止損': params.get('loss'),
                    '數量': params.get('share_per_trade'),
                    '預估盈虧': round(params.get('pl'), 2),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'),
                quantity=params.get('share_per_trade'),
                price=params.get('current_price'),
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, 2, {'monitor': False}, publish, order)])

        elif action == -2: # 止損空倉
            publish = {
                'title': '空倉止損通知(尚未下單)',
                'description': f"SMC空倉止損: {params.get('code')}買回",
                'footer': f'{self.symbol}',
                'color': 0xFF0000,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '原先止盈': params.get('profit'),
                    '原先止損': params.get('loss'),
                    '數量': params.get('share_per_trade'),
                    '預估盈虧': round(params.get('pl'), 2),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=params.get('share_per_trade'), 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': params.get('comm'), 'tax': params.get('tax'), 'tick_size': params.get('tick_size')},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, -2, {'monitor': False}, publish, order)])
        
        elif action == 5: # 多倉動態止盈止損更新
            publish = {
                'title': '多倉動態倉位更新(尚未下單)',
                'description': f"SMC多倉新價格: {params.get('code')}",
                'footer': f'{self.symbol}',
                'color': 0x4682B4,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': params.get('share_per_trade'),
                    '新止盈': params.get('profit'),
                    '新止損': params.get('loss'),
                    '當前資產': params.get('capital')
                }
            }
            
            return self.order.extend([(self.symbol, self.item, 5, {}, publish, {})])

        elif action == -5: # 空倉動態止盈止損更新
            publish = {
                'title': '空倉動態倉位更新(尚未下單)',
                'description': f"SMC空倉新價格: {params.get('code')}",
                'footer': f'{self.symbol}',
                'color': 0x4682B4,
                'notify_params': {
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': params.get('share_per_trade'),
                    '新止盈': params.get('profit'),
                    '新止損': params.get('loss'),
                    '當前資產': params.get('capital')
                }
            }
            
            return self.order.extend([(self.symbol, self.item, -5, {}, publish, {})])

    def entry(self, action):
        if action == 0: # 無交易
            self.log.info("當前無任何交易訊號")
            self.nothing_order()
            return self.order
        
        code1 = self.item['code'][0]
        ts1 = self.last_data['ts']
        price1 = float(self.last_data['tick'][0]['close'])
        capital1 = int(self.current_position1.get('position', {}).get('capital', self.params['capital1']))
        
        # 取得 timeframe 為 '4hr', '15min', '5min' 的字典
        time_4hr_data = next((item for item in self.tuple_results if item['timeframe'] == '4hr'), None)['result']
        time_15min_data = next((item for item in self.tuple_results if item['timeframe'] == '15min'), None)['result']
        time_5min_data = next((item for item in self.tuple_results if item['timeframe'] == '5min'), None)['result']
        
        if action == 1: # 做多
            self.log.info(f"當前{code1}做多: 大時間方向({self.params['direction']}), 15分({time_15min_data['close']})與5分({time_5min_data['close']})價格, 回落OB:(Top: {self.params['ob_top']}, Bottom: {self.params['ob_bottom']}")
            self.log.info(f"4HR/VWAP:{time_4hr_data['vwap']}, 15min/VWAP:{time_15min_data['vwap']}, 5min/VWAP:{time_5min_data['vwap']}, 當前收盤價都在VWAP之上")
            self.log.info(f"且當前的5分價格{time_5min_data['close']}在2倍標準差內, 5min/VWAP_STD(Upper: {time_5min_data['vwap_upper_2std']}, Lower: {time_5min_data['vwap_lower_2std']})")
            
            self.publish_order(1, **{
                'code': code1,
                'ts': ts1,
                'current_price': price1,
                '4hr_vwap': time_4hr_data['vwap'],
                '15min_close': time_15min_data['close'],
                '15min_vwap': time_15min_data['vwap'],
                '5min_close': time_5min_data['close'],
                '5min_vwap': time_5min_data['vwap'],
                '5min_std': f"(Upper: {time_5min_data['vwap_upper_2std']}, Lower: {time_5min_data['vwap_lower_2std']})",
                'profit_ratio': self.params['profit_ratio1'],
                'stop_ratio': self.params['stop_ratio1'],
                'comm': self.params['commission1'],
                'tax': self.params['tax1'],
                'tick_size': self.params['tick_size1'],
                'share_per_trade': self.params['share_per_trade1'],
                'capital': capital1
            })
            
        elif action == -1: # 做空
            self.log.info(f"當前{code1}做空: 大時間方向({self.params['direction']}), 15分({time_15min_data['close']})與5分({time_5min_data['close']}價格, 回落OB:(Top: {self.params['ob_top']}, Bottom: {self.params['ob_bottom']}")
            self.log.info(f"4HR/VWAP:{time_4hr_data['vwap']}, 15min/VWAP:{time_15min_data['vwap']}, 5min/VWAP:{time_5min_data['vwap']}, 當前收盤價都在VWAP之下")
            self.log.info(f"且當前的5分價格{time_5min_data['close']}在2倍標準差內, 5min/VWAP_STD(Upper: {time_5min_data['vwap_upper_2std']}, Lower: {time_5min_data['vwap_lower_2std']})")
            
            self.publish_order(-1, **{
                'code': code1,
                'ts': ts1,
                'current_price': price1,
                '4hr_vwap': time_4hr_data['vwap'],
                '15min_close': time_15min_data['close'],
                '15min_vwap': time_15min_data['vwap'],
                '5min_close': time_5min_data['close'],
                '5min_vwap': time_5min_data['vwap'],
                '5min_std': f"(Upper: {time_5min_data['vwap_upper_2std']}, Lower: {time_5min_data['vwap_lower_2std']})",
                'profit_ratio': self.params['profit_ratio1'],
                'stop_ratio': self.params['stop_ratio1'],
                'comm': self.params['commission1'],
                'tax': self.params['tax1'],
                'tick_size': self.params['tick_size1'],
                'share_per_trade': self.params['share_per_trade1'],
                'capital': capital1
            })
            
        return self.order

    def execute(self):
        try:
            if not self.params['monitor'] or self.params['direction'] == 0: # SMC判定不監控
                self.log.info(f"當前監控為False: {self.params['monitor']} 或 大時間無方向: {self.params['direction']}")
                self.nothing_order()
                return self.order
            
            result_k = self.load_k()

            if result_k[0] is False: # 判斷 load_k 的返回值
                self.log.info("load_k 返回 False, 不進行運算")
                self.nothing_order()
                return self.order
            
            # 將三種資料的運算添加
            self.load_calculations(result_k[0])
            self.load_calculations(result_k[1])
            self.load_calculations(result_k[2])

            if not self.calculate:
                self.nothing_order()
                return self.order
            
            # 進行策略計算
            for idx, calculation in enumerate(self.calculate):
                result = calculation.execute(**self.window_series[idx])
                self.tuple_results.append({'timeframe': self.window_series[idx]['timeframe'], 'result': result})  # 保存 tuple 类型的结果
            
            # 提取所有 result 的第一個元素
            first_elements = [res['result'][0] for res in self.tuple_results]
            self.log.info(f"運算完畢結果, 僅提取第一個數值來看交易行為: {first_elements}")
            
            if any(elem is False for elem in first_elements): # 判斷是否有任何 False
                action = 0
            elif all(elem == 1 for elem in first_elements): # 判斷是否所有元素為 1
                action = 1
            elif all(elem == -1 for elem in first_elements): # 判斷是否所有元素為 -1
                action = -1
            else: # 其他情況
                action = 0

            if self.check_position(): # 已持倉: 檢查是否需要平倉
                self.check_exit_conditions()
            else: # 未持倉: 根據結果決定是否進場
                self.entry(action)

            self.log.info("本次計算結束\n\n")
            return self.order

        except Exception as e:
            self.log.error(f"TMFR_SMC執行策略出錯: {e}")
            self.nothing_order()
            return self.order
    