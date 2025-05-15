from .abc.AbstractCalculation import AbstractCalculation
from scipy import stats
from statsmodels.tsa.stattools import adfuller, acf, pacf
import numpy as np
import pandas as pd
from utils.log import get_module_logger

class Stationary(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/stationary")
    
    def execute(self):
        return self.calculation()
    
    def calculation(self, stricter_confidence=0.95, adf_significance=0.05, debug=False):
        self.data[['open', 'close', 'high', 'low']] = self.data[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
        
        recent_data = self.data[-self.params['long_window']:]['close']
        
        if recent_data.nunique() == 1 or np.var(recent_data) == 0:
            if debug:
                self.log.info("The time series has no variance (constant). Skipping ADF test.")

            return False
        
        else:
            # 計算 ACF 和 PACF
            acf_values = acf(recent_data, nlags=self.params['long_lag'], fft=False)
            pacf_values = pacf(recent_data, nlags=self.params['long_lag'])

            # 計算信賴區間 z-score (例如 99% 設為 2.58，97% 設為 1.88，等)
            z_score = stats.norm.ppf(1 - (1 - stricter_confidence) / 2)  # ppf 返回對應的 z-score
            stricter_conf_interval = z_score / np.sqrt(len(recent_data))

            # 檢查 ACF 和 PACF 是否快速衰減到更嚴格的信賴區間內
            acf_in_blue_zone = np.all(np.abs(acf_values[1:]) < stricter_conf_interval)
            pacf_in_blue_zone = np.all(np.abs(pacf_values[1:]) < stricter_conf_interval)

            # 執行 ADF 測試
            adf_result = adfuller(recent_data)
            adf_p_value = adf_result[1]  # p-value

            # 設定 ADF 測試門檻
            adf_is_stationary = adf_p_value < adf_significance

            # 记录当前时间戳和 ADF 检验结果
            if debug:
                self.log.info(f"Time: {recent_data.index[-1]} | ADF p-value: {adf_p_value}, Is Stationary: 「{adf_is_stationary}」, ACF in blue zone: {acf_in_blue_zone}, PACF in blue zone: {pacf_in_blue_zone}")
    
            return acf_in_blue_zone and pacf_in_blue_zone and adf_is_stationary

    def long_signal(self):
        pass
    
    def short_signal(self):
        pass
    