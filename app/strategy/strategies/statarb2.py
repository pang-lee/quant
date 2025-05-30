from .abc.AbstractStrategy import AbstractStrategy
from utils.technical_indicator import rsi
import pandas as pd
from datetime import datetime, time
import json

class Statarb2(AbstractStrategy):
    def __init__(self, datas, item, symbol, k=300):
        super().__init__(datas, item, symbol, 0, ['stop_ratio1', 'stop_ratio2'], k)
        self.code_mapping = {'FXFR1': 'A', 'ZFFR1': 'B'}
        self.current_position1 = None
        self.current_position2 = None
        self.k_data = []

    def load_k(self):
        df_dict = {}
        ts_comparison = []  # 用於儲存每個 code 的 last_k_ts 和 latest_k_ts 比較結果

        for code in self.item['code']:
            last_k_ts = None if super().get_from_redis(f"last_k_{code}_{self.item['strategy']}") is None else datetime.strptime(super().get_from_redis(f"last_k_{code}_{self.item['strategy']}")['ts'], "%Y-%m-%d %H:%M:%S")
            
            # 根據 code 查找對應的 redis_k_key
            redis_k_key = self.redis_k_key.get(code) if isinstance(self.redis_k_key, dict) else self.redis_k_key
            if not redis_k_key:
                self.log.info(f"找不到對應的 redis_k_key: {code}")
                continue  # 如果找不到對應的 redis_k_key，跳過該 code
            
            k_amount = self.lrange_of_redis(redis_k_key, -self.params['k_lookback'], -1)

            if len(k_amount) < self.params['k_lookback']:
                return 0

            # 只取最近 long_window 根 K 棒
            recent_k_amount = k_amount[-self.params['k_lookback']:]
            
            # 將 JSON 字串轉換為資料結構
            self.k_data = [json.loads(record) for record in recent_k_amount]

            latest_k_ts = datetime.strptime(self.k_data[-1]['ts'], "%Y-%m-%d %H:%M:%S")

            if last_k_ts is None:
                super().save_to_redis(f"last_k_{code}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')  # 存入 Redis
                ts_comparison.append(False)  # 因為是初次儲存，不視為更新
                return

            # 記錄比較結果（時間已更新）
            ts_comparison.append(True)

            # 依照預設的對應關係將 code 換成 'A' 或 'B'
            mapped_code = self.code_mapping.get(code, code)  # 如果沒有對應關係，保持原代號
            self.k_data = sorted(self.k_data, key=lambda x: datetime.strptime(x['ts'], '%Y-%m-%d %H:%M:%S'))
            
            # 將每個 code 對應的資料存儲到字典中，key 為映射後的代號, 計算 RSI
            rsi_series = rsi( pd.Series([float(record['close']) for record in self.k_data]), self.params['rsi'])
            
            if len(rsi_series) < self.params['z_window']:
                self.log.info(f"當前的rsi時間序列資料共: {len(rsi_series)} 筆, 最低要求: {self.params['z_window']} 筆")
                return
            
            df_dict[mapped_code] = rsi_series

            if super().get_from_redis(f"flag_{code}_{self.item['strategy']}") is None:
                super().save_to_redis(f"flag_{code}_{self.item['strategy']}", {'flag': True}, type='set')
                
            if latest_k_ts != last_k_ts: # 儲存最新的 latest_k_ts 與可進場的 flag
                super().save_to_redis(f"flag_{code}_{self.item['strategy']}", {'flag': True}, type='set')
                super().save_to_redis(f"last_k_{code}_{self.item['strategy']}", {'ts': latest_k_ts.strftime("%Y-%m-%d %H:%M:%S")}, type='set')

        if ts_comparison and all(ts_comparison):
            return self.load_calculations(df_dict)

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

    def check_data_exist(self):
        code1, code2 = self.item['code'][0], self.item['code'][1]
        default_data = {'ts': '0', 'tick': [{'close': 0}]}
    
        data1 = self.last_data.get(code1, default_data)
        data2 = self.last_data.get(code2, default_data)
        
        # 檢查 code1 和 code2 是否存在於 last_data 中
        if code1 not in self.last_data:
            self.log.warning(f'雙邊有一邊缺少資料缺少code1: {code1}')
            return False
            
        if code2 not in self.last_data:
            self.log.warning(f'雙邊有一邊缺少資料缺少code2: {code2}')
            return False
        
        # 檢查 'tick' 是否存在且為非空列表
        if 'tick' not in data1 or not data1['tick']:
            self.log.warning(f'{code1} 缺少tick資料')
            return False
        
        if 'tick' not in data2 or not data2['tick']:
            self.log.warning(f'{code2} 缺少tick資料')
            return False
        
        self.log.info(f"當前data1(MXFR): \n{data1}\n")
        self.log.info(f"當前data2(TMFR): \n{data2}\n")
        
        return {code1: data1, code2: data2}

    def check_flag(self):
        flags = []
        
        for code in self.item['code']:
            if super().get_from_redis(f"flag_{code}_{self.item['strategy']}") is None:
                continue

            flags.append(super().get_from_redis(f"flag_{code}_{self.item['strategy']}")['flag'])

        self.log.info(f"當前可否進場的flag: {flags}")
        return len(flags) == len(self.item['code']) and all(flags)

    def entry(self, action):
        if action == 0: # 無交易
            self.log.info("當前z-score統計後無交易信號")
            self.nothing_order()
            return self.order

        if self.check_flag() is False: # 止損過, 等待時間更新
            self.log.info("先前止損過, 需等待時間更新後才能再次進場")
            self.nothing_order()
            return self.order

        code_data = self.check_data_exist()
        
        if code_data is False:
            self.nothing_order()
            return self.order
        
        code1, code2 = list(code_data.keys())[0], list(code_data.keys())[1]
        data1, data2 = code_data[code1], code_data[code2]
        price1, price2 = data1['tick'][0]['close'], data2['tick'][0]['close']
        ts1, ts2 =  data1['ts'], data2['ts']
        
        capital1, capital2 = int(self.current_position1.get('position', {}).get('capital', self.params['capital1'])), int(self.current_position2.get('position', {}).get('capital', self.params['capital2']))
        
        if action == 1: # 多A空B邏輯
            self.log.info("當前z-score統計後: 多A空B")
            self.publish_order(1, **{
                'code': code1,
                'ts': ts1,
                'current_price': price1,
                'stop_ratio': self.params['stop_ratio1'],
                'comm': self.params['commission1'],
                'tax': self.params['tax1'],
                'tick_size': self.params['tick_size1'],
                'share_per_trade': self.params['share_per_trade1'],
                'capital': capital1
            })
            
            self.publish_order(-1, **{
                'code': code2,
                'ts': ts2,
                'current_price': price2,
                'stop_ratio': self.params['stop_ratio2'],
                'comm': self.params['commission2'],
                'tax': self.params['tax2'],
                'tick_size': self.params['tick_size2'],
                'share_per_trade': self.params['share_per_trade2'],
                'capital': capital2
            })

            return self.order

        elif action == -1: # 空A多B邏輯
            self.log.info("當前z-score統計後: 空A多B")
            self.publish_order(-1, **{
                'code': code1,
                'ts': ts1,
                'current_price': price1,
                'stop_ratio': self.params['stop_ratio1'],
                'comm': self.params['commission1'],
                'tax': self.params['tax1'],
                'tick_size': self.params['tick_size1'],
                'share_per_trade': self.params['share_per_trade1'],
                'capital': capital1
            })
            
            self.publish_order(1, **{
                'code': code2,
                'ts': ts2,
                'current_price': price2,
                'stop_ratio': self.params['stop_ratio2'],
                'comm': self.params['commission2'],
                'tax': self.params['tax2'],
                'tick_size': self.params['tick_size2'],
                'share_per_trade': self.params['share_per_trade2'],
                'capital': capital2
            })

            return self.order

    def check_position(self):
        code1, code2 = self.item['code'][0], self.item['code'][1]
        strategy_order_info = self.execute_position_control('check') or {}
        self.current_position1 = strategy_order_info.get(code1, {})
        self.current_position2 = strategy_order_info.get(code2, {})
        
        # 判斷是否有未完成的訂單或有倉位
        has_pending_orders1 = 'pending_orders' in self.current_position1 and bool(self.current_position1['pending_orders'])
        has_position1 = 'position' in self.current_position1 and 'symbol' in self.current_position1['position'] and 'quantity' in self.current_position1['position']
        has_any_activity1 = has_pending_orders1 or has_position1

        has_pending_orders2 = 'pending_orders' in self.current_position2 and bool(self.current_position2['pending_orders'])
        has_position2 = 'position' in self.current_position2 and 'symbol' in self.current_position2['position'] and 'quantity' in self.current_position2['position']
        has_any_activity2 = has_pending_orders2 or has_position2

        # 輸出詳細狀態
        self.log.info("倉位檢查結果")
        self.log.info(f"Position1 ({code1}): 有無未完成訂單: {has_pending_orders1}, 有無持倉: {has_position1}")
        self.log.info(f"Position2 ({code2}): 有無未完成訂單: {has_pending_orders2}, 有無持倉: {has_position2}")

        # 只要任一邊有活動（訂單或持倉）就返回 True，否則返回 False
        return has_any_activity1 or has_any_activity2

    def check_exit_conditions(self, action):
        """檢查止損/止盈條件"""
        pos1_dict, pos2_dict = self.current_position1.get('position', {}), self.current_position2.get('position', {})
        position1, position2 = int(pos1_dict.get('position', 0)), int(pos2_dict.get('position', 0))
        take_profit1, take_profit2 = int(pos1_dict.get('profit', 0)), int(pos2_dict.get('profit', 0))
        stop_loss1, stop_loss2 = int(pos1_dict.get('loss', 0)), int(pos2_dict.get('loss', 0))
        origin_price1, origin_price2 = int(pos1_dict.get('origin', 0)), int(pos2_dict.get('origin', 0))
        capital1, capital2 = int(pos1_dict.get('capital', self.params['capital1'])), int(pos2_dict.get('capital', self.params['capital2']))

        code_data = self.check_data_exist()

        if code_data is False:
            self.nothing_order()
            return self.order
        
        code1, code2 = list(code_data.keys())[0], list(code_data.keys())[1]
        data1, data2 = code_data[code1], code_data[code2]
        price1, price2 = int(data1['tick'][0]['close']), int(data2['tick'][0]['close'])
        ts1, ts2 =  data1['ts'], data2['ts']
        data_time = datetime.strptime(data1['ts'], "%Y-%m-%d %H:%M:%S")
        trading_periods = [
            (time(8, 45), time(13, 44)),# 上午时段：8:45 - 13:45
            (time(15, 0), time(23, 59, 59)), # 下午到隔日凌晨时段：15:00 至次日 5:00
            (time(0, 0), time(4, 59)) #（需拆解为两段）
        ]

        if position1 < 0 and position2 > 0: # 空A多B
            self.log.info("當前空A(MXFR)多B(TMFR)")
            
            pl1 = round(((origin_price1 - price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price1 * self.params['tax1']) + (price1 * self.params['tax1']))), 2)
            pl2 = round(((price2 - origin_price2) * self.params['tick_size2'] - (2 * self.params['commission2'] + (origin_price2 * self.params['tax2']) + (price2 * self.params['tax2']))), 2)
            
            if self.force_close(data_time, trading_periods): # 判斷是否超時平倉
                self.log.info(f"當前商品A(MXFR)已經超時要平倉, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(-4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '空倉超時平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 空倉 {code1} 買回",
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前商品B(TMFR)已超時要平倉, 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(4, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'title': '多倉超時平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 多倉 {code2} 賣出",
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })
                
                # 等待下一次更新時間後才可再進場
                super().save_to_redis(f"flag_{code1}_{self.item['strategy']}", {'flag': False}, type='set')
                super().save_to_redis(f"flag_{code2}_{self.item['strategy']}", {'flag': False}, type='set')
                return self.order

            if price1 > stop_loss1 or price2 < stop_loss2: # 判斷是否有止損
                if price1 > stop_loss1: self.log.info("當前A商品(MXFR)止損")
                elif price2 < stop_loss2: self.log.info("當前B商品(TMFR)止損")
                
                self.log.info(f"當前商品A(MXFR)準備出場, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(-2, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前商品B(TMFR)準備出場, 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(2, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })

                # 等待下一次更新時間後才可再進場
                super().save_to_redis(f"flag_{code1}_{self.item['strategy']}", {'flag': False}, type='set')
                super().save_to_redis(f"flag_{code2}_{self.item['strategy']}", {'flag': False}, type='set')
                return self.order
            
            if action == 2: # zscore回歸0
                self.log.info(f"當前zscore為0要平倉, 商品A(MXFR) => 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(-4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '空倉平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 統計均值回歸: {code1}買回",
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前zscore為0要平倉, 商品B(TMFR) => 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(4, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'title': '多倉平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 統計均值回歸: {code2}賣出",
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })
                
                return self.order
            
            self.log.info("當前甚麼也沒觸發(止損, 平倉), 等待下一次檢查")
            
        elif position1 > 0 and position2 < 0: # 多A空B
            self.log.info("當前多A(MXFR)空B(TMFR)")
            
            pl1 = round(((price1 - origin_price1) * self.params['tick_size1'] - (2 * self.params['commission1'] + (origin_price1 * self.params['tax1']) + (price1 * self.params['tax1']))), 2)
            pl2 = round(((origin_price2 - price2) * self.params['tick_size2'] - (2 * self.params['commission2'] + (origin_price2 * self.params['tax2']) + (price2 * self.params['tax2']))), 2)

            if self.force_close(data_time, trading_periods): # 判斷是否超時平倉
                self.log.info(f"當前商品A(MXFR)已經超時要平倉, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '空倉超時平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 空倉 {code1} 買回",
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前商品B(TMFR)已超時要平倉, 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(-4, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'title': '多倉超時平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 多倉 {code2} 賣出",
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })
                
                # 等待下一次更新時間後才可再進場
                super().save_to_redis(f"flag_{code1}_{self.item['strategy']}", {'flag': False}, type='set')
                super().save_to_redis(f"flag_{code2}_{self.item['strategy']}", {'flag': False}, type='set')
                return self.order
            
            if price1 < stop_loss1 or price2 > stop_loss2: # 判斷是否有止損
                if price1 < stop_loss1: self.log.info("當前A商品(MXFR)止損")
                elif price2 > stop_loss2: self.log.info("當前B商品(TMFR)止損")
                
                self.log.info(f"當前商品A(MXFR)準備出場, 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(2, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前商品B(TMFR)準備出場, 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(-2, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })
                
                # 等待下一次更新時間後才可再進場
                super().save_to_redis(f"flag_{code1}_{self.item['strategy']}", {'flag': False}, type='set')
                super().save_to_redis(f"flag_{code2}_{self.item['strategy']}", {'flag': False}, type='set')
                return self.order
            
            if action == 2: # zscore回歸0
                self.log.info(f"當前zscore為0要平倉, 商品A(MXFR) => 止盈:{take_profit1}, 止損:{stop_loss1}, 原始價格:{origin_price1}, 當前價格:{price1}")
                self.publish_order(4, **{
                    'code': code1,
                    'ts': ts1,
                    'current_price': price1,
                    'title': '空倉平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 統計均值回歸: {code1}買回",
                    'pl': pl1,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit1,
                    'loss': stop_loss1,
                    'comm': self.params['commission1'],
                    'tax': self.params['tax1'],
                    'tick_size': self.params['tick_size1'],
                    'share_per_trade': self.params['share_per_trade1'],
                    'capital': capital1
                })
                
                self.log.info(f"當前zscore為0要平倉, 商品B(TMFR) => 止盈:{take_profit2}, 止損:{stop_loss2}, 原始價格:{origin_price2}, 當前價格:{price2}")
                self.publish_order(-4, **{
                    'code': code2,
                    'ts': ts2,
                    'current_price': price2,
                    'title': '多倉平倉通知(尚未下單)',
                    'description': f"{self.split_code_to_str(self.item['code'])} 統計均值回歸: {code2}賣出",
                    'pl': pl2,
                    'pl_total': pl1 + pl2,
                    'profit': take_profit2,
                    'loss': stop_loss2,
                    'comm': self.params['commission2'],
                    'tax': self.params['tax2'],
                    'tick_size': self.params['tick_size2'],
                    'share_per_trade': self.params['share_per_trade2'],
                    'capital': capital2
                })
                
                return self.order
            
            self.log.info("當前甚麼也沒觸發(止損, 平倉), 等待下一次檢查")
        
        return False
    
    def execute(self):
        try:
            self.load_k()
            
            if not self.calculate:
                self.nothing_order()
                return self.order

            # -1: 空A多B, 1: 多A空B, 2: z-score回歸
            for calculation in self.calculate:
                result = calculation.execute()
                self.log.info(f"運算結果: {result}")
                
                if self.check_position(): # 已持倉: 檢查是否需要平倉
                    if self.check_exit_conditions(result):
                        continue  # 已處理平倉，跳到下一個循環

                else: # 未持倉: 根據結果決定是否進場
                    self.entry(result)

            self.log.info("本次計算結束\n\n")
            return self.order

        except Exception as e:
            self.log.error(f"Statarb策略出錯: {e}")
            self.nothing_order()
            return self.order