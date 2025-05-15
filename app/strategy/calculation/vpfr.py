from .abc.AbstractCalculation import AbstractCalculation
import pandas as pd
import numpy as np
import re
from utils.log import get_module_logger

class Vpfr(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/vpfr")

    def execute(self, is_trend=False, debug=True):
        if not self.check_volume_slippage(debug=debug): # 當前成交量過少可能滑價
            return (False, 0)

        vpfr_data = self.calculation()
        
        vpfr_check = self.check_vpfr(vpfr_data, self.data, is_trend=is_trend, debug=debug)
        
        # 震盪盤檢查如果 vpfr_check 是布林值 (bool) 且為 False，則返回 (False, 0)
        if isinstance(vpfr_check, bool) and not vpfr_check:
            return (False, 0)
        
        # 計算支撐位和壓力位
        result = self.find_support_resistance_based_on_vpfr(vpfr_data, debug=debug)

        if result is None:
            return (False, 0)
        
        current_price = self.data['close'].iloc[-1]
        
        support_range1, resistance_range1, support_price1, resistance_price1 = result
        if debug:
            self.log.info(f"支撐區間: {support_range1}, 壓力區間: {resistance_range1}")

        if debug:
            self.log.info(f"支撐位: {support_price1}, 壓力位: {resistance_price1}")
            self.log.info(f"支撐範圍: {support_range1}, 壓力範圍: {resistance_range1}")

        # 價格遠離支撐與壓力位, 進入監測
        if not (support_range1[0] < current_price < support_range1[1] or resistance_range1[0] < current_price < resistance_range1[1]):
            if debug:
                self.log.info(f"價格偏離支撐與壓力位，進入監控狀態，等待價格接近關鍵區間。")
            return (True, support_range1, resistance_range1)
            
        # 價格接近壓力位, 空頭交易
        if resistance_range1[0] <= current_price <= resistance_range1[1]:  
            if debug:
                self.log.info(f"價格接近壓力位 {resistance_price1:.2f}，空頭交易")
            return self.short_signal(support_range1, resistance_range1)

        # 價格接近支撐位, 多頭交易
        elif support_range1[0] <= current_price <= support_range1[1]:
            if debug:
                self.log.info(f"價格接近支撐位 {support_price1:.2f}，多頭交易")
                
            return self.long_signal(support_range1, resistance_range1)
        
        return (False, 0)

    def calculation(self):
        self.data[['open', 'close', 'high', 'low']] = self.data[['open', 'close', 'high', 'low']].apply(pd.to_numeric)
        
        self.data['lowest_low'] = self.data['low'].rolling(window=self.params['long_window']).min()
        self.data['highest_high'] = self.data['high'].rolling(window=self.params['long_window']).max()
        
        # 近期高低點
        recent_low = self.data['lowest_low'].iloc[-1]
        recent_high = self.data['highest_high'].iloc[-1]
        
        # 檢查數值是否合理
        if pd.isna(recent_low) or pd.isna(recent_high) or recent_high <= recent_low:
            self.log.info(f"當前價格範圍內, 沒有有效的數值, 回傳空物件, 當前數值: {self.data}, 近期高: {recent_high}, 近期低: {recent_low}")
            return {}
        else:
            # 計算VPFR
            price_bins = pd.interval_range(
                start=self.data['lowest_low'].iloc[-1], 
                end=self.data['highest_high'].iloc[-1], 
                freq=(self.data['highest_high'].iloc[-1] - self.data['lowest_low'].iloc[-1]) / self.params['long_window']
            )

            # 使用.copy()防止SettingWithCopyWarning
            recent_data = self.data.iloc[-self.params['long_window']:].copy()

            # 使用.loc確保安全賦值
            recent_data.loc[:, 'price_bin'] = pd.cut(recent_data['close'], bins=price_bins)

            # 修正 observed=True 警告
            volume_distribution = recent_data.groupby('price_bin', observed=True)['volume'].sum()
            total_volume = recent_data['volume'].sum()
            vpfr = volume_distribution / total_volume

            # 將VPFR作為字典傳回
            return {str(bin): value for bin, value in vpfr.items()}
    
    def check_vpfr(self, vpfr, data, is_trend=False, debug=False):
        total_volume_above_threshold = 0
        total_volume_below_threshold = 0

        # 確保 data 是 Pandas DataFrame 格式
        if not isinstance(data, pd.DataFrame):
            self.log.info("Error: data 不是 DataFrame 格式!")
            return False

        # 遍歷 DataFrame 中的每一行資料，判斷成交量是否超過閾值
        for _, entry in data.iterrows():
            volume = entry['volume']
            if volume > self.params['volume_threshold']:
                total_volume_above_threshold += 1
            else:
                total_volume_below_threshold += 1

        # 計算成交量超過閾值的比例
        total_data_points = len(data)
        if total_data_points == 0:
            return False  # 若無資料則不進行交易

        volume_above_ratio = total_volume_above_threshold / total_data_points

        if debug:
            self.log.info(f"成交量超過閾值的比例: {(volume_above_ratio)*100}%")

        # 根據震盪盤或趨勢盤判斷成交量條件
        if is_trend:
            if volume_above_ratio >= self.params['volume_ratio']:  # 超過 60% 是趨勢盤
                if debug:
                    self.log.info(f"趨勢盤: 大部分成交量大於閾值({self.params['volume_ratio']})")
            else:
                return (False, 0)  # 不符合趨勢盤條件

        else:  # 震盪盤: 成交量全部小於閾值
            if volume_above_ratio < self.params['volume_ratio']:  # 所有成交量都小於閾值
                if debug:
                    self.log.info(f"震盪盤: 所有成交量小於閾值({self.params['volume_ratio']})")
            else:
                return False  # 不符合震盪盤條件

        # ------------ VPFR 標準差與集中度計算 --------------
        price_ranges = []
        volumes = []

        # 將 vpfr 解析成數值列表
        for key, volume in vpfr.items():
            lower, upper = map(float, re.findall(r"\d+\.\d+", key))
            price_ranges.append((lower + upper) / 2)  # 中位數作為代表價格
            volumes.append(volume)

        # 計算價格的均值與標準差
        mean_price = np.mean(price_ranges)
        std_dev_price = np.std(price_ranges)

        # 定義高價區與低價區門檻
        high_price_threshold = mean_price + std_dev_price
        low_price_threshold = mean_price - std_dev_price

        # 計算高價與低價的VPFR成交量
        high_price_vpfr = sum(vol for pr, vol in zip(price_ranges, volumes) if pr >= high_price_threshold)
        low_price_vpfr = sum(vol for pr, vol in zip(price_ranges, volumes) if pr <= low_price_threshold)

        if debug:
            self.log.info(f"均值價格: {mean_price:.2f}, 標準差: {std_dev_price:.2f}")
            self.log.info(f"高價區門檻: {high_price_threshold:.2f}, 低價區門檻: {low_price_threshold:.2f}")
            self.log.info(f"高價區成交量: {high_price_vpfr:.4f}, 低價區成交量: {low_price_vpfr:.4f}")

        # 根據 VPFR 判斷盤勢類型
        if is_trend:
            if high_price_vpfr > self.params['vpfr_trend']:
                if debug:
                    self.log.info("✅ 趨勢盤: 成交量集中於高價位")
                return (True, 1)

            if low_price_vpfr > self.params['vpfr_trend']:
                if debug:
                    self.log.info("✅ 趨勢盤: 成交量集中於低價位")
                return (True, -1)

            else:
                if debug:
                    self.log.info("❌ 不符合趨勢盤條件")
                return (False, 0)
        else:
            if high_price_vpfr < self.params['vpfr_oscillation'] and low_price_vpfr < self.params['vpfr_oscillation']:
                if debug:
                    self.log.info("✅ 震盪盤: 成交量分佈均勻")
                return True
            else:
                if debug:
                    self.log.info("❌ 不符合震盪盤條件")
                return False

    def find_support_resistance_based_on_vpfr(self, vpfr, debug=False):
        """
        根據VPFR成交量分佈來直接計算支撐位和壓力位。

        :param vpfr: VPFR成交量分佈字典
        :return: 支撐位和壓力位
        """
        # 初始化最小和最大價格
        min_price = float('inf')  # 設置一個很大的初始最小價格
        max_price = float('-inf')  # 設置一個很小的初始最大價格

        # 遍歷所有區間，更新最小價格和最大價格
        for price_range in vpfr:
            lower_price, upper_price = price_range[1:-1].split(',')  # 提取區間中的價格
            lower_price = float(lower_price)  # 轉換為浮點數
            upper_price = float(upper_price)  # 轉換為浮點數

            # 更新最小價格和最大價格
            if lower_price < min_price:
                min_price = lower_price
            if upper_price > max_price:
                max_price = upper_price

        # 計算支撐與壓力區間 (加上 buffer)
        buffer = self.params['oscillation_buffer']
        support_range = (min_price - buffer), (min_price + buffer)
        resistance_range = (max_price - buffer), (max_price + buffer)

        # 計算支撐位和壓力位
        price_diff = resistance_range[0] - support_range[1]
        if price_diff <= self.params['price_diff']:
            if debug:
                self.log.info(f"價格差 {price_diff:.2f} 需大於閾值 {self.params['price_diff']:.2f}，放棄此次交易判斷")
            return None

        return support_range, resistance_range, min_price, max_price
    
    def check_volume_slippage(self, debug=False):
        # 成交量過小避免滑價不交易
        if self.data['volume'].sum() <= self.params['volume_slippage']:
            if debug:
                self.log.info(f"成交量 {self.data['volume'].sum()} 小於 {self.params['volume_slippage']}不交易")
            return False

        return True
        
    def long_signal(self, support, resistance):
        return (1, support, resistance)
    
    def short_signal(self, support, resistance):
        return (-1, support, resistance)
    