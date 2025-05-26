from .abc.AbstractStrategy import AbstractStrategy
from datetime import datetime, time
import json

class Tmfrsmc(AbstractStrategy):
    def __init__(self, datas, item, symbol):
        super().__init__(datas, item, symbol, 'profit_ratio1', 'stop_ratio1')
        self.last_4hr_k = None if super().get_from_redis(f"last_k_4hr_{self.item['code'][0]}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_4hr_{self.item['code'][0]}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
        self.last_15min_k = None if super().get_from_redis(f"last_k_15min_{self.item['code'][0]}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_15min_{self.item['code'][0]}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
        self.last_5min_k = None if super().get_from_redis(f"last_k_5min_{self.item['code'][0]}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_5min_{self.item['code'][0]}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
        self.current_position1 = None
        self.k_4h, self.k_15min, self.k_5min = [], [], []

    def load_k(self):
        # 從self.redis_k_key中讀取1分K, 並組合成大時間級別K, 而後放入相對應的Key中,
        # 接著使用self.lrange_of_redis取得每個時間的K棒資料
        
        k_4hr_amount = self.lrange_of_redis(self.redis_k_key, -self.params['z_window'], -1)
        k_15min_amount = self.lrange_of_redis(self.redis_k_key, -self.params['z_window'], -1)
        k_5min_amount = self.lrange_of_redis(self.redis_k_key, -self.params['z_window'], -1)

        if len(k_4hr_amount) < self.params['window_4h'] and len(k_15min_amount) < self.params['window_15m'] and len(k_5min_amount) < self.params['window_5m']:
            return 0

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
    
    def check_exit_conditions(self, action):
        """檢查止損/止盈條件"""
        pass
    
    def publish_order(self, action, **params):
        if action == 1: # 多單
            publish = {
                'title': '可進場通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 統計偏離均值: {params.get('code')}做多",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '代號': params.get('code'),
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': params.get('share_per_trade'),
                    '進場類型': '多',
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
                'description': f"{self.split_code_to_str(self.item['code'])} 統計偏離均值: {params.get('code')}做空",
                'footer': f'{self.symbol}',
                'color': 0x8B4513,
                'notify_params': {
                    '代號': params.get('code'),
                    '時間': params.get('ts'),
                    "策略": self.item['strategy'],
                    '當前點數': params.get('current_price'),
                    '數量': params.get('share_per_trade'),
                    '進場類型': '空',
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
                    '總盈虧': round(params.get('pl_total'), 2),
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
                    '總盈虧': round(params.get('pl_total'), 2),
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
                'description': f"{self.split_code_to_str(self.item['code'])} 多倉止損: {params.get('code')}賣出",
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
                    '總盈虧': round(params.get('pl_total'), 2),
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
            
            return self.order.extend([(self.symbol, self.item, 2, {}, publish, order)])
                
        elif action == -2: # 止損空倉
            publish = {
                'title': '空倉止損通知(尚未下單)',
                'description': f"{self.split_code_to_str(self.item['code'])} 空倉止損: {params.get('code')}買回",
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
                    '總盈虧': round(params.get('pl_total'), 2),
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
            
            return self.order.extend([(self.symbol, self.item, -2, {}, publish, order)])

    def entry(self):
        pass
    
    def execute(self):
        try:
            self.nothing_order()
            return self.order

            self.load_k()

            if not self.calculate:
                self.nothing_order()
                return self.order

        except Exception as e:
            self.log.error(f"TMFR_SMC執行策略出錯: {e}")
            self.nothing_order()
            return self.order
    