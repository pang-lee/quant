from .abc.AbstractCalculation import AbstractCalculation
import pandas as pd
import numpy as np
from utils.log import get_module_logger

class Vwap(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/vwap")
        self.timeframe = ''

    def execute(self, **kwargs):
        window = kwargs.get('timeframe_window')
        self.timeframe = kwargs.get('timeframe')
        self.log.info(f"當前要進行運算的時間: {self.timeframe}, 窗口時長: {window}")
        return self.calculation(window)
    
    def calculation(self, window):
        status = None
        if self.timeframe == '5min' or self.timeframe == '15min': # 先判斷價格是否有回到OB
            status = self.return_ob()
            self.log.info(f"當前時間段: {self.timeframe}, 要判斷是否價格有回踩OB, 判斷結果: {status}")
        
        if not status: # 當前5分或15分價格沒有回踩OB
            if self.timeframe == '4hr':
                self.log.info(f"當前時間段: {self.timeframe}, 不用檢查OB, 等待下一次判斷\n\n")
            self.log.info(f"當前時間段: {self.timeframe}, 沒有回踩價格, 等待下一次判斷\n\n")
            return (False, 0)
        
        # 當前5分或15分價格回踩OB, 即將進行vwap判斷
        self.calculate_vwap(window, self.timeframe == '5min')
        self.log.info(f"VWAP計算完畢, 當前的dataframe: {self.data.head(5)}\n\n")
        signal = self.execute_signal()
        
        if signal == 0:
            return (False, 0)

        return (signal, self.data.iloc[-1])

    def calculate_vwap(self, window, include_std_bands=False):
        """
        計算滾動窗口的 VWAP，並可選擇為 5 分鐘 K 線計算標準差帶。

        參數:
        - self.data: Pandas DataFrame，包含 'open', 'high', 'low', 'close', 'volume' 列
        - window: 滾動窗口大小（K 線數量）
        - include_std_bands: 是否計算標準差帶（僅用於 5 分鐘 K 線）

        返回:
        - DataFrame，包含原始數據和新計算的列：
          - 'vwap': 滾動 VWAP 值
          - 若 include_std_bands=True，額外包含：
            - 'vwap_upper_1std', 'vwap_lower_1std': ±1 標準差帶
            - 'vwap_upper_2std', 'vwap_lower_2std': ±2 標準差帶
        """
        
        # 將所有數值列轉為 float 並保留小數點後兩位
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_columns:
            if col in self.data.columns:
                self.data[col] = pd.to_numeric(self.data[col], errors='coerce').round(2)
                if self.data[col].isna().any():
                    self.log.warning(f"Column {col} 在轉換後有NAN: {self.data[col][self.data[col].isna()]}")
        
        # 計算典型價格 (High + Low + Close) / 3
        self.data['typical_price'] = (self.data['high'] + self.data['low'] + self.data['close']) / 3

        # 計算價格 × 成交量
        self.data['price_volume'] = self.data['typical_price'] * self.data['volume']

        # 計算滾動窗口的 VWAP
        self.data['cum_price_volume'] = self.data['price_volume'].rolling(window=window, min_periods=1).sum()
        self.data['cum_volume'] = self.data['volume'].rolling(window=window, min_periods=1).sum()
        self.data['vwap'] = self.data['cum_price_volume'] / self.data['cum_volume']

        # 如果需要計算標準差帶（僅 5 分鐘 K 線）
        if include_std_bands:
            # 計算典型價格相對於 VWAP 的平方差
            self.data['price_diff_squared'] = (self.data['typical_price'] - self.data['vwap']) ** 2
            # 計算滾動標準差
            self.data['std'] = np.sqrt(self.data['price_diff_squared'].rolling(window=window, min_periods=1).mean())
            # 計算 ±1 和 ±2 標準差帶
            self.data['vwap_upper_2std'] = self.data['vwap'] + 2 * self.data['std']
            self.data['vwap_lower_2std'] = self.data['vwap'] - 2 * self.data['std']

            # 刪除中間計算列
            self.data = self.data.drop(columns=['price_diff_squared', 'std'])

        # 刪除中間計算列
        self.data = self.data.drop(columns=['typical_price', 'price_volume', 'cum_price_volume', 'cum_volume'])

        return self.data
    
    def return_ob(self):
        ob_top = self.params['ob_top']
        ob_bottom = self.params['ob_bottom']
        close = float(self.data['close'].iloc[-1])
        
        self.log.info(f'the close:{close}, {type(close)}, {type(ob_top)}, {type(ob_bottom)}')
        
        self.log.info(f"ob_top: {ob_top}, ob_bottom: {ob_bottom}, 當前時間段{self.timeframe}價格: {close}")

        if ob_bottom <= close <= ob_top:
            return True
        
        return False
    
    def close_in_std(self, close):
        if self.data['vwap_upper_2std'] >= close >= self.data['vwap_lower_2std']:
            return True
        
        return False
    
    def long_signal(self):
        close = self.data['close'].iloc[-1]
        vwap = self.data['vwap'].iloc[-1]
        
        if close > vwap:
            self.log.info(f"當前大時間級別判斷為{self.params['direction']}, 收盤價:{close} > VWAP:{vwap}, 可進場做多")
            
            if self.timeframe == '5min':
                self.log.info(f"當前時間級別: {self.timeframe} 需判斷價格是否在標準差內")
                status = self.close_in_std(close)
                self.log.info(f"當前價格: {close}, 標準差帶 - 上限:{self.data['vwap_upper_2std']}, 下限: {self.data['vwap_lower_2std']}, 是否有在範圍內: {status}")
                
                if not status: # 不在標準差範圍內
                    return 0
                
                return 1
            return 1
        else:
            self.log.info(f"當前大時間級別判斷為{self.params['direction']}, 收盤價:{close} < VWAP:{vwap}, 不可進場做多")
            return 0
    
    def short_signal(self):
        close = self.data['close'].iloc[-1]
        vwap = self.data['vwap'].iloc[-1]
        
        if close < vwap:
            self.log.info(f"當前大時間級別判斷為{self.params['direction']}, 收盤價:{close} < VWAP:{vwap}, 可進場做空")
            
            if self.timeframe == '5min':
                self.log.info(f"當前時間級別為: {self.timeframe} 需判斷價格是否在標準差內")
                status = self.close_in_std(close)
                self.log.info(f"當前價格: {close}, 標準差帶 - 上限:{self.data['vwap_upper_2std']}, 下限: {self.data['vwap_lower_2std']}, 是否有在範圍內: {status}")
                
                if not status: # 不在標準差範圍內
                    return 0
                
                return -1
            return -1
        else:
            self.log.info(f"當前大時間級別判斷為{self.params['direction']}, 收盤價:{close} > VWAP:{vwap}, 不可進場做空")
            return 0
    
    def execute_signal(self):
        direction = self.params.get('direction')
        signal_methods = {
            1: self.long_signal,
            -1: self.short_signal
        }
        signal_method = signal_methods.get(direction)
        
        if signal_method:
            return signal_method()
        else:
            self.log.error(f"未知的 direction 值")
            return False

