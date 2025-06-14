from .abc.AbstractCalculation import AbstractCalculation
from utils.technical_indicator.bias import calculate_bias_ratio
from utils.technical_indicator.diff import shift_log, diff_change, diff_change_shift
from utils.log import get_module_logger

class Zscore(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/zscore")
        
    def execute(self):
        return self.calculation()

    def calculation(self):
        self.log.info(f"當前計算方式: {self.params['statarb_type']}")
        
        if self.params['statarb_type'] == 'beta':
            return self.generate_signal(self.zscore(self.beta_sereis()))
        elif self.params['statarb_type'] == 'bias':
            return self.generate_signal(self.zscore(self.bias_sereis(self.params['use_ratio'])))
        elif self.params['statarb_type'] == 'shift_log':
            return self.generate_signal(self.zscore(self.shift_log_sereis(self.params['use_log'])))
        elif self.params['statarb_type'] == 'diff_change_shift':
            return self.generate_signal(self.zscore(self.diff_change_shift_sereis()))
        elif self.params['statarb_type'] == 'diff_change':
            return self.generate_signal(self.zscore(self.diff_change_sereis(self.params['use_pct'])))
    
    def bias_sereis(self, ratio):
        bias_series = calculate_bias_ratio(self.data['A'], self.data['B'], self.params['bias_period'], use_ratio=ratio)
        self.log.info(f"當前的bias序列偏差計算: {bias_series}")
        return bias_series

    def diff_change_sereis(self, pct):
        diff_series = diff_change(self.data['A'], self.data['B'], pct=pct)
        self.log.info(f"當前的diff序列計算: {diff_series}")
        return diff_series

    def diff_change_shift_sereis(self):
        diff_change_series = diff_change_shift(self.data['A'], self.data['B'])
        self.log.info(f"當前的diff_change序列計算: {diff_change_series}")
        return diff_change_series
    
    def shift_log_sereis(self, log):
        shfit_log_series = shift_log(self.data['A'], self.data['B'], log=log)
        self.log.info(f"當前的shift_log序列計算: {shfit_log_series}")
        return shfit_log_series

    def beta_sereis(self):
        self.log.info(f"開始計算\n: {self.data}")
        
        if 'A' not in self.data.columns or 'B' not in self.data.columns:
            self.log.error("DF表中沒有A, B兩個商品代號")
            return 0
        
        # Compute residuals
        residuals = self.data['B'] - self.params['beta'] * self.data['A']
        self.log.info(f"Residual 計算完畢,\n 當前數值: {residuals}\n")
        return residuals

    def zscore(self, series):
        self.log.info(series)

        mean = series.mean()
        std = series.std()
        if std == 0:
            self.log.warning("當前標準差為0無法計算, z-score 設定為0")
            return 0  # 避免除以 0
        
        current_zscore = (series.iloc[-1] - mean) / std
        self.log.info(f"Z-score 統計完畢,\n {current_zscore}\n")

        return current_zscore
    
    def generate_signal(self, z_score):
        """根據 z-score 生成交易信號"""
        self.log.info(f"當前z-score: {z_score}, 準備生成交易訊號\n")
        if z_score > self.params['threshold']: # Z-score > threshold，多 A 空 B
            return -1 
        elif z_score < -self.params['threshold']: # Z-score < -threshold，空 A 多 B
            return 1
        elif abs(z_score) < 0.1: # Z-score 接近 0 時平倉
            return 2

        return 0 # 無信號
        
    def long_signal(self):
        pass
    
    def short_signal(self):
        pass
