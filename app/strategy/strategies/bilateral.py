from .abc.AbstractStrategy import AbstractStrategy
from datetime import datetime, time
import json, ast

class Bilateral(AbstractStrategy):
    def __init__(self, datas, item, symbol, k=3600):
        super().__init__(datas, item, symbol, 'oscillation_profit_ratio1', 'oscillation_stop_ratio1', k)
        self.last_k_ts = None if super().get_from_redis(f"last_k_ts_{self.item['code'][0]}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_ts_{self.item['code'][0]}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
        self.total_bid_volume = 0
        self.total_ask_volume = 0
        self.k_data = []

    def load_k(self):
        k_amount = self.lrange_of_redis(self.redis_k_key, -self.params['long_window'], -1)
        
        if len(k_amount) < self.params['long_window']:
            return 0
        
        # 只取最近 long_window 根 K 棒
        recent_k_amount = k_amount[-self.params['long_window']:]
        
        # 將 JSON 字串轉換為資料結構
        self.k_data = [json.loads(record) for record in recent_k_amount]

        latest_k_ts = datetime.strptime(self.k_data[-1]['ts'], "%Y-%m-%d %H:%M:%S")
        
        if self.last_k_ts is None:
            return super().save_to_redis(f"last_k_ts_{self.item['code'][0]}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')  # 存入 Redis
            
        if not self.params['monitor'] and latest_k_ts != self.last_k_ts:
            super().save_to_redis(f"last_k_ts_{self.item['code'][0]}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')
            return self.load_calculations(self.k_data)
        
        if latest_k_ts != self.last_k_ts:
            return super().save_to_redis(f"last_k_ts_{self.item['code'][0]}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')
        
    def check_price(self):
        sr_value = super().get_from_redis(f"{self.item['strategy']}_{json.dumps(self.item['code'])}_sr")

        # 檢查 sr_value 是否為 None 或空值
        if not sr_value:
            self.log.error(f"從 Redis 取不到壓力支撐的相關資訊, 將重設監控狀態")
            self.entry('quit', **{
                'title': '無法獲得支撐壓力的數值, 不再監控',
                'capital': capital
            })

            return self.order
        
        code = self.item['code'][0]
        # 檢查 tick 是否有資料
        if self.last_data['tick'] and len(self.last_data['tick']) > 0:
            stock_price1 = float(self.last_data['tick'][0]['close'])
        else:
            self.log.error(f"{code}沒有取得最新的tick或bid_ask資料: {self.last_data}")
            self.nothing_order()
            return self.order
        
        data_time = datetime.strptime(self.last_data['ts'], "%Y-%m-%d %H:%M:%S")
        trading_periods = [
            (time(8, 45), time(13, 44)),# 上午时段：8:45 - 13:45
            (time(15, 0), time(23, 59, 59)), # 下午到隔日凌晨时段：15:00 至次日 5:00
            (time(0, 0), time(4, 59)) #（需拆解为两段）
        ]
        
        sr_value['support'] = ast.literal_eval(sr_value['support'])
        sr_value['resistance'] = ast.literal_eval(sr_value['resistance'])
        strategy_order_info = self.execute_position_control('check').get(code, {})

        self.log.info(f"準備檢查進場條件")

        # 判斷是否有未完成的訂單或有倉位
        has_pending_orders = 'pending_orders' in strategy_order_info and bool(strategy_order_info['pending_orders'])
        has_position = 'position' in strategy_order_info and 'symbol' in strategy_order_info['position'] and 'quantity' in strategy_order_info['position']
        
        if not has_pending_orders and not has_position: # 如果當前沒有訂單也沒有倉位, 判斷價格是否接近支撐與壓力, 接近則進場
            self.log.info("當前沒有任何訂單與倉位, 準備檢查是否適合進場")
            capital = strategy_order_info.get('position', {}).get('capital', self.params['capital'])
            
            if self.force_close(data_time, trading_periods): # 無艙位但是超時, 不再監控價格
                self.log(f"監控逾時, 不再監控價格")
                self.entry('quit', **{
                    'title': '超出交易時間, 不再監控震盪價格變化',
                    'capital': capital
                })
                
                return self.order

            if self.check_price_over_sr(stock_price1, sr_value['support'], sr_value['resistance']): # 判斷價格是否超出壓力支撐位
                self.log.info(f"當前價位超出支撐壓力, 重設監控狀況")
                self.entry(True, **{
                    'modify': 'over_sr',
                    'support': sr_value['support'],
                    'resistance': sr_value['resistance'],
                    'capital': capital
                })
                
                return self.order
            
            if sr_value['resistance'][0] <= stock_price1 <= sr_value['resistance'][1]: # 遇到壓力空
                self.log.info(f"當前價位接近壓力, 準備進場空")
                self.entry(-1, **{
                    'code': code,
                    'current_price': stock_price1,
                    'support': sr_value['support'],
                    'resistance': sr_value['resistance'],
                    'capital': capital
                })
                 
                return self.order

            elif sr_value['support'][0] <= stock_price1 <= sr_value['support'][1]: # 遇到支撐多
                self.log.info(f"當前價位接近支撐, 準備進場多")
                self.entry(1, **{
                    'code': code,
                    'current_price': stock_price1,
                    'support': sr_value['support'],
                    'resistance': sr_value['resistance'],
                    'capital': capital
                })
                
                return self.order
             
        else: # 如果當前有倉位, 判斷價格是否接近支撐與壓力, 接近則平倉再反向進場
            self.log.info("當前有倉位, 準備檢查是否平倉")
            position_data = strategy_order_info['position']
            
            if not position_data:
                self.log.warning("當前被判定為有倉位, 但卻無法獲得倉位資料, 可能有訂單還沒成交")
                self.nothing_order()
                return self.order
            
            position = position_data.get('position', 0)
            take_profit = position_data.get('profit')
            stop_loss = position_data.get('loss')
            origin_price = position_data.get('origin')
            capital = position_data.get('capital')

            if position > 0: # 當前多倉
                self.log.info("當前倉位是多倉")
                if self.force_close(data_time, trading_periods): # 判斷是否超時平倉
                    self.log.info(f"當前時間已超時平倉, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 止盈:{take_profit}, 止損:{stop_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(4, **{
                        'code': code,
                        'current_price': stock_price1,
                        'title': '多倉超時平倉通知(尚未下單)',
                        'description': f"{self.split_code_to_str(self.item['code'])} 多倉超時平倉",
                        'pl': round(((stock_price1 - origin_price) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital,
                        'monitor': False
                    })
                    
                    return self.order
            
                if stock_price1 <= stop_loss:  # 觸發止損(多倉賣出)
                    self.log.info(f"當前多倉位止損, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 止盈:{take_profit}, 止損:{stop_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(2, **{
                        'code': code,
                        'current_price': stock_price1,
                        'pl': round(((stock_price1 - origin_price) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    return self.order
                
                elif stock_price1 >= take_profit:  # 觸發止盈動態更新價位
                    new_profit, new_loss = self.execute_position_control('calculate', **{'action': 'long', 'current_price': stock_price1})  # 重設止盈止損
                    self.entry(5, **{
                        'code': code,
                        'profit': new_profit,
                        'loss': new_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    strategy_order_info['position']['profit'] = new_profit
                    strategy_order_info['position']['loss'] = new_loss
                    strategy_order_info['position']['origin'] = stock_price1
                    
                    # 新止盈價位回寫redis
                    self.execute_position_control('set', **{
                        'key': self.position_redis_key,
                        'data': {f'{code}': strategy_order_info}
                    })
                    
                    self.log.info(f"當前多倉位動態價格更新, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 舊止盈:{take_profit}, 舊止損:{stop_loss}, 新止盈:{new_profit}, 新止損:{new_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    return self.order
                
                elif sr_value['resistance'][0] <= stock_price1 <= sr_value['resistance'][1]:  # 接近壓力位平倉
                    self.log.info(f"當前多倉接近壓力平倉在做空, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(4, **{
                        'code': code,
                        'current_price': stock_price1,
                        'title': '多倉平倉通知(尚未下單)',
                        'description': f"{self.split_code_to_str(self.item['code'])} 多倉接近壓力平倉",
                        'pl': round(((stock_price1 - origin_price) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    self.entry(-1, **{ # 平倉單後再建立空單
                        'code': code,
                        'current_price': stock_price1,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    return self.order
                    
            elif position < 0: # 當前空倉
                self.log.info("當前倉位是空倉")
                if self.force_close(data_time, trading_periods): # 判斷是否超時平倉
                    self.log.info(f"當前時間已超時平倉, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 止盈:{take_profit}, 止損:{stop_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(-4, **{
                        'code': code,
                        'current_price': stock_price1,
                        'title': '空倉超時平倉通知(尚未下單)',
                        'description': f"{self.split_code_to_str(self.item['code'])} 空倉超時平倉",
                        'pl': round(((origin_price - stock_price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital,
                        "monitor": False
                    })
                    
                    return self.order
                
                if stock_price1 >= stop_loss:  # 觸發止損(空倉買回)
                    self.log.info(f"當前空倉位止損, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 止盈:{take_profit}, 止損:{stop_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(-2, **{
                        'code': code,
                        'current_price': stock_price1, 
                        'pl': round(((origin_price - stock_price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    return self.order
                
                elif stock_price1 <= take_profit:  # 觸發止盈動態更新價位
                    new_profit, new_loss = self.execute_position_control('calculate', **{'action': 'short', 'current_price': stock_price1})  # 重設止盈止損
                    self.entry(-5, **{
                        'code': code,
                        'profit': new_profit,
                        'loss': new_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    strategy_order_info['position']['profit'] = new_profit
                    strategy_order_info['position']['loss'] = new_loss
                    strategy_order_info['position']['origin'] = stock_price1
                    
                    # 新止盈價位回寫redis
                    self.execute_position_control('set', **{
                        'key': self.position_redis_key,
                        'data': {f'{code}': strategy_order_info}
                    })
                    
                    self.log.info(f"當前空倉位動態價格更新, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 舊止盈:{take_profit}, 舊止損:{stop_loss}, 新止盈:{new_profit}, 新止損:{new_loss}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    return self.order
                
                elif sr_value['support'][0] <= stock_price1 <= sr_value['support'][1]:  # 接近支撐位平倉
                    self.log.info(f"當前空倉接近支撐平倉在做多, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 原始價格:{origin_price}, 當前價格:{stock_price1}")
                    self.entry(-4, **{
                        'code': code,
                        'current_price': stock_price1,
                        'title': '空倉平倉通知(尚未下單)',
                        'description': f"{self.split_code_to_str(self.item['code'])} 空倉接近支撐平倉",
                        'pl': round(((origin_price - stock_price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price * self.params['tax1']) + (stock_price1 * self.params['tax1']))), 2),
                        'profit': take_profit,
                        'loss': stop_loss,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    self.entry(1, **{ # 平倉單後再建立多單
                        'code': code,
                        'current_price': stock_price1,
                        'support': sr_value['support'],
                        'resistance': sr_value['resistance'],
                        'capital': capital
                    })
                    
                    return self.order
                
        # 沒碰到支撐壓力, 也沒止盈止損, 繼續監控        
        self.nothing_order()
        self.log.info(f"當前沒有任何條件觸發繼續監控, 倉位:{has_position}, 訂單:{has_pending_orders}, 支撐位:{sr_value['support']}, 壓力位:{sr_value['resistance']}, 當前價格:{stock_price1}") 
        return self.order
    
    def check_price_over_sr(self, current_price, support, resistance):        
        self.log.info(f"檢查價格是否超出支撐壓力, 當前價格: {current_price}, 支撐: {support}, 壓力: {resistance}")
        
        # 如果價格低於支撐位的下限或高於壓力位的上限，則回傳True
        if current_price < support[0] or current_price > resistance[1]:
            return True
        return False

    def check_bid_ask_slippage(self, data):
        if not data['bidask']: # 如果 bidask 列表为空，直接返回 False 或进行其他适当的处理
            self.log.info("bidask 列表为空")
            return False
        
        # 解析 bid_prices 和 ask_prices，转为数值列表        
        bid_ask = data['bidask'][0]
        bid_prices = [float(price) for price in bid_ask['bid_prices']]
        ask_prices = [float(price) for price in bid_ask['ask_prices']]
        
        # 计算最高委买和最低委卖价格
        max_bid_price = max(bid_prices)
        min_ask_price = min(ask_prices)
        spread = min_ask_price - max_bid_price
        
        # 获取委买与委卖总量
        self.total_bid_volume = int(bid_ask['bid_total_vol'])
        self.total_ask_volume = int(bid_ask['ask_total_vol'])

        # 判断是否符合滑价条件
        if spread > self.params['bid_ask_slippage']:
            self.log.info(f"委買委賣價差spread: {spread}, 價差過大不進行交易")
            return False

        return True
    
    def check_long_bid_ask(self):
        if self.total_ask_volume < self.params['min_bid_ask_volume']:  # 賣方成交量不足
            self.log.info("當前賣方成交量不足, 避免流動性不足不交易")
            return False
        
        return True

    def check_short_bid_ask(self):
        if self.total_bid_volume < self.params['min_bid_ask_volume']:  # 買方成交量不足
            self.log.info("當前買方成交量不足, 避免流動性不足不交易")
            return False
        
        return True
            
    def entry(self, action=False, support=None, resistance=None, **params):
        if action is False: # 不交易
            self.nothing_order()
            return self.order
        
        if action == 'quit': # 超時無倉位, 不再監控價格
            publish = {
                'title': params.get('title'),
                'description': f"{self.split_code_to_str(self.item['code'])} 不進行監控",
                'footer': f'{self.symbol}',
                'color': 0x00FF7F,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前資產': params.get('capital', 0)
                }
            }
            
            return self.order.extend([(self.symbol, self.item, True, {'monitor': False}, publish, order)])
        
        # ---------------- 先判斷倉位狀態 ----------------
        if action == 2: # 止損多倉
            publish = {
                'title': '多倉止損通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 多倉止損",
                'footer': f'{self.symbol}',
                'color': 0xFF0000,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '原先止盈': params.get('profit'),
                    '原先止損': params.get('loss'),
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '預估盈虧': params.get('pl'),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'),
                quantity=self.item['params']['shares_per_trade1'],
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, 2, {'monitor': False}, publish, order)])
                
        elif action == -2: # 止損空倉
            publish = {
                'title': '空倉止損通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 空倉止損",
                'footer': f'{self.symbol}',
                'color': 0xFF0000,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '原先止盈': params.get('profit'),
                    '原先止損': params.get('loss'),
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '預估盈虧': params.get('pl'),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=self.item['params']['shares_per_trade1'], 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, -2, {'monitor': False}, publish, order)])

        elif action == 5: # 多倉動態止盈止損更新
            publish = {
                'title': '多倉動態倉位更新(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 多倉新價格",
                'footer': f'{self.symbol}',
                'color': 0x4682B4,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': self.last_data['tick'][0]['close'],
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '新止盈': params.get('profit'),
                    '新止損': params.get('loss'),
                    '當前資產': params.get('capital')
                }
            }
            
            return self.order.extend([(self.symbol, self.item, 5, {}, publish, {})])
            
        elif action == -5: # 空倉動態止盈止損更新
            publish = {
                'title': '空倉動態倉位更新(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 空倉新價格",
                'footer': f'{self.symbol}',
                'color': 0x4682B4,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': self.last_data['tick'][0]['close'],
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '新止盈': params.get('profit'),
                    '新止損': params.get('loss'),
                    '當前資產': params.get('capital')
                }
            }
            
            return self.order.extend([(self.symbol, self.item, -5, {}, publish, {})])

        elif action == 4: # 多倉平倉
            publish = {
                'title': params.get('title'),
                'description': params.get('description'),
                'footer': f'{self.symbol}',
                'color': 0x32CD32,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '止盈': params.get('profit'),
                    '止損': params.get('loss'),
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '預估盈虧': params.get('pl'),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=self.item['params']['shares_per_trade1'], 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            if params.get('monitor') is False: 
                return self.order.extend([(self.symbol, self.item, 4, {'monitor': params.get('monitor')}, publish, order)])
            
            return self.order.extend([(self.symbol, self.item, 4, {}, publish, order)])

        elif action == -4: # 空倉平倉
            publish = {
                'title': params.get('title'),
                'description': params.get('description'),
                'footer': f'{self.symbol}',
                'color': 0x32CD32,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '止盈': params.get('profit'),
                    '止損': params.get('loss'),
                    '支撐': support,
                    '壓力': resistance,
                    '數量': self.item['params']['shares_per_trade1'],
                    '預估盈虧': params.get('pl'),
                    '當前資產': params.get('capital') + params.get('pl')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=self.item['params']['shares_per_trade1'], 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            if params.get('monitor') is False:
                return self.order.extend([(self.symbol, self.item, -4, {'monitor': params.get('monitor')}, publish, order)])
            
            return self.order.extend([(self.symbol, self.item, -4, {}, publish, order)])

        # --------------- 在檢查是否有監控進場 --------------
        if not self.params['monitor']: # 沒有監控則將支撐壓力存入 redis
            super().save_to_redis(f"{self.item['strategy']}_{json.dumps(self.item['code'])}_sr", {'support': support, 'resistance': resistance}, type='set')

        if not self.check_bid_ask_slippage(self.last_data): # 可能滑價不交易
            return self.nothing_order()

        if action is True: # 進入震盪監控或離開監控
            if params.get('modify') == 'over_sr': # 價格超出支撐壓力位, 不監控
                publish = {
                    'title': '價格超出支撐壓力區間',
                    'description': f"{self.split_code_to_str(self.item['code'])} 不進行監控",
                    'footer': f'{self.symbol}',
                    'color': 0x00FF7F,
                    'notify_params': {
                        '時間': self.last_data['ts'],
                        "策略": self.item['strategy'],
                        '當前點數': self.last_data['tick'][0]['close'],
                        '數量': self.item['params']['shares_per_trade1'],
                        '支撐': support,
                        '壓力': resistance,
                        '當前資產': params.get('capital', 0)
                    }
                }
                
                return self.order.extend([(self.symbol, self.item, True, {'monitor': False}, publish, {})])

            else: # 價格在區間壓力內, 進行監控
                position_data = self.execute_position_control('check').get(self.item['code'], {})
                capital = position_data.get('position', {}).get('capital', self.params['capital'])

                publish = {
                    'title': '監控價格通知',
                    'description': f"{self.split_code_to_str(self.item['code'])} 進入震盪監控",
                    'footer': f'{self.symbol}',
                    'color': 0x00FF7F,
                    'notify_params': {
                        '時間': self.last_data['ts'],
                        "策略": self.item['strategy'],
                        '當前點數': self.last_data['tick'][0]['close'],
                        '數量': self.item['params']['shares_per_trade1'],
                        '支撐': support,
                        '壓力': resistance,
                        '止損': self.item['params']['oscillation_stop_ratio1'],
                        '止盈': self.item['params']['oscillation_profit_ratio1'],
                        '當前資產': capital
                    }
                }

                return self.order.extend([(self.symbol, self.item, True, {'monitor': True}, publish, {})])

        elif action == 1: # 接近支撐做多
            if not self.check_long_bid_ask(): # 賣方掛單量不足
                return self.nothing_order()

            publish = {
                'title': '可進場通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 震盪接近支撐做多",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': self.item['params']['shares_per_trade1'],
                    '進場類型': '多',
                    '支撐': support,
                    '壓力': resistance,
                    '止損點數': self.item['params']['oscillation_stop_ratio1'],
                    '止盈點數': self.item['params']['oscillation_profit_ratio1'],
                    '當前資產': params.get('capital')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=self.item['params']['shares_per_trade1'], 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, 1, {'monitor': True}, publish, order)])

        elif action == -1: # 接近壓力做空
            if not self.check_short_bid_ask(): # 買方掛單量不足
                return self.nothing_order()

            publish = {
                'title': '可進場通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 震盪接近壓力做空",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '時間': self.last_data['ts'],
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': self.item['params']['shares_per_trade1'],
                    '進場類型': '空',
                    '支撐': support,
                    '壓力': resistance,
                    '止損點數': self.item['params']['oscillation_stop_ratio1'],
                    '止盈點數': self.item['params']['oscillation_profit_ratio1'],
                    '當前資產': params.get('capital')
                }
            }
            
            order = self.create_order(
                code=params.get('code'), 
                quantity=self.item['params']['shares_per_trade1'], 
                price=params.get('current_price'), 
                symbol=self.symbol, 
                broker=self.params['broker'], 
                comm_tax={'comm': self.params['commission1'], 'tax': self.params['tax1'], 'tick_size': self.params['tick_size1']},
                capital=params.get('capital')
            )
            
            return self.order.extend([(self.symbol, self.item, -1, {'monitor': True}, publish, order)])
    
    def execute(self):
        try:
            self.log.info(f"當前監控為: {self.params['monitor']}, 即將進行運算")
            if self.params['monitor']: # 已經進入震盪, 價格監控找機會進場
                self.log.info(f"當前進入價格監控")

                self.load_k()
                self.check_price()
                
                self.log.info(f"計算完畢, 結果為: {self.order}\n\n")
                return self.order

            self.load_k()
            if not self.calculate:
                self.log.info(f"當前時間沒更新, 不進行策略運算")
                self.nothing_order()
                return self.order

            bool_results = []
            tuple_results = []

            for calculation in self.calculate:
                result = calculation.execute()

                if isinstance(result, bool):
                    bool_results.append(result)  # 保存 bool 类型的结果
                elif isinstance(result, tuple):
                    tuple_results.append(result)  # 保存 tuple 类型的结果

            self.log.info(f"當前尚未進入監控, 檢查計算分析結果(bool判斷: {bool_results}), (vpfr判斷: {tuple_results})")
            
            if all(bool_results) and tuple_results[0][0] is not False: # 條件判斷可下單
                for result_tuple in tuple_results:
                    action, support, resistance = result_tuple

                    self.entry(action, support, resistance)
                    return self.order

            else: # 條件都沒過甚麼都不做
                self.nothing_order()
                return self.order
        
        except Exception as e:
            self.log.error(f"Bilateral執行策略出錯: {e}")
            self.nothing_order()
            return self.order
