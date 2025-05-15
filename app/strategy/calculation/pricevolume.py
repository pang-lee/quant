from .abc.AbstractCalculation import AbstractCalculation
from datetime import datetime
import copy

class Pricevolume(AbstractCalculation):
    def execute(self, params, datas):
        current_ts = datas[0]['ts']
        vol_threshold = params.get('volume_threshold')
        monitor_period = params.get('period')
        
        redis_key = f"{datas[0]['code']}_pv"
        redis_pop = super().check_redis_pop(redis_key)
        
        previous_ts = redis_pop['ts']
        previous_pv_list = redis_pop['pv_list']
        short_signal, long_signal = 0, 0 # 初始化信号和计数器，默认为 0
        short_counter = redis_pop.get('short_counter', 0)
        long_counter = redis_pop.get('long_counter', 0)
        current_pv_list = self.calculation(previous_pv_list, datas)
        
        # 如果要計算空
        if params.get('short') is True:
            short_signal, short_counter = self.short_signal(current_ts, previous_ts, current_pv_list, previous_pv_list, vol_threshold, monitor_period, short_counter)
        
        # 如果要計算多
        if params.get('long') is True:
            long_signal, long_counter = self.long_signal(current_ts, previous_ts, current_pv_list, previous_pv_list, vol_threshold, monitor_period, long_counter)
        
        self.save_to_redis(redis_key, {
            'ts': current_ts,
            'pv_list': current_pv_list,
            'short_counter': short_counter,
            'long_counter': long_counter
        })
        
        limit_up = 10000
        limit_down = 10
        
        return short_signal, long_signal, {'pv': current_pv_list, 'limit_up': limit_up, 'limit_down': limit_down}
        
    def calculation(self, pre_data, datas):
        '''
        計算價量
        pre_data: 前一筆Redis中的資料
        datas: 當前API請求獲得的資料
        '''
        
        pv_list = copy.deepcopy(pre_data)
        print(f'\nThis Time The Datas Are: {datas}\n')

        # 遍历 datas 进行处理
        for data in datas:
            close_price = data['close']
            volume = data['volume']
            
            # 当 redis_data 为空时，直接插入数据
            if not pv_list:
                pv_list.append((close_price, volume))
                continue  # 继续处理下一条数据

            # 将新的 (close, volume) 插入到 order_list 中，保持按照 close 降序排序
            inserted = False
            for i, (price, vol) in enumerate(pv_list):
                if close_price == price: # 如果价格相同，累加成交量
                    pv_list[i] = (price, vol + volume)
                    inserted = True
                    break
                
                elif close_price > price: # 如果当前价格大于列表中的价格，插入到当前位置
                    pv_list.insert(i, (close_price, volume))
                    inserted = True
                    break

            # 如果没有找到合适的位置，则将数据添加到末尾
            if not inserted:
                pv_list.append((close_price, volume))
            
        return pv_list

    def pop_from_redis(self, redis_key):
        return super().pop_from_redis(redis_key)

    def save_to_redis(self, redis_key, dict_data):
        return super().save_to_redis(redis_key, dict_data)

    def time_diff(self, ts1, ts2):
        ''' 
        計算時間差:
        ts1: 當前此秒的時間戳
        ts2: 前一秒的時間戳
        '''
        # 处理时间格式，判断 pre_ts 是否为 "0"
        cur_ts_dt = datetime.strptime(ts1, "%Y-%m-%d %H:%M:%S")
        pre_ts_dt = cur_ts_dt if ts2 == "0" else datetime.strptime(ts2, "%Y-%m-%d %H:%M:%S")
    
        # 计算时间差
        return int((cur_ts_dt - pre_ts_dt).total_seconds())
  
    def short_signal(self, cur_ts, pre_ts, cur_pv_list, pre_pv_list, vol_threshold, monitor_period, counter):
        # 计算时间差
        time_diff = self.time_diff(cur_ts, pre_ts)
        
        # 取得當前的最高價量(list of tuple)與, 前一個時刻的最高價量(list of tuple), 第一筆資料為(0, 0)
        cur_highest_price, cur_highest_volume = max(cur_pv_list, key=lambda x: x[0])
        pre_high_price, _ = max(pre_pv_list, key=lambda x: x[0]) if pre_pv_list else (0, 0)

        # 初始化返回信号
        signal = 0
        
        print('the price pair', cur_highest_price, pre_high_price)
        
        # 判断是否符合条件最高價量在條件內 
        if cur_highest_price == pre_high_price and cur_highest_volume < vol_threshold:
            # 条件符合，开始累加秒數, 如果 counter 为 0，则counter從1開始
            counter += time_diff if counter > 0 else 1
            
            # 如果 counter 达到或超过 monitor_period，生成信号 -1
            if counter >= monitor_period:
                signal = -1
                
        else: # 条件不符合，重置 counter
            print('reset the counter')
            counter = 0
            signal = 0
            
        return signal, counter
    
    def long_signal(self, cur_ts, pre_ts, cur_pv_list, pre_pv_list, vol_threshold, monitor_period, counter):
        # 初始化返回信号
        signal = 0
        
        return signal, counter