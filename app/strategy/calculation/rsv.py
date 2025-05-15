from .abc.AbstractCalculation import AbstractCalculation
import pandas as pd
from utils.log import get_module_logger

class Rsv(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/rsv")
    
    def execute(self):
        if self.params['rsv_low'] <= self.calculation() <= self.params['rsv_high']:
            self.log.info(f"RSV: {self.calculation()}")
            return True
        
        return False
    
    def calculation(self):
        self.data[['open', 'close', 'high', 'low']] = self.data[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
        
        self.data['lowest_low'] = self.data['low'].rolling(window=self.params['long_window']).min()
        self.data['highest_high'] = self.data['high'].rolling(window=self.params['long_window']).max()
        
        # 計算 RSV
        self.data['rsv'] = ((self.data['close'] - self.data['lowest_low']) / 
                     (self.data['highest_high'] - self.data['lowest_low'])) * 100

        # 如果價格沒變動，RSV 設為 0
        self.data['rsv'] = self.data['rsv'].fillna(0)

        return self.data['rsv'].iloc[-1]
        
    def long_signal(self):
        pass
    
    def short_signal(self):
        pass
    