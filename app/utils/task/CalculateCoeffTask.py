from utils.task.Task import Task
from utils.technical_indicator import rsi
from utils.log import get_module_logger
from utils.k import convert_ohlcv
import pandas as pd
import os, pytz
from utils.file import open_json_file, update_settings
from statsmodels.tsa.vector_ar.vecm import coint_johansen
import shioaji as sj
from datetime import timedelta, datetime
from dotenv import load_dotenv
load_dotenv()

class CalculateCoeffTask(Task):
    def __init__(self):
        self.log = get_module_logger('utils/task/CalculateCoeffTask')
    
    @property
    def name(self) -> str:
        return "calculate_coeff"

    async def execute(self, **kwargs) -> None:
        try:
            self.log.info(f"運行calculate_coeff task")
            self._init_params(**kwargs)
            self.filter_settings()

            if kwargs.get('redo') is True:
                self.filter_strategy()
            else:
                self.filter_night()

            await self.calculate_coeff(self.lock)
        except Exception as e:
            self.log.error(f"calculate_coeff運行錯誤: {str(e)}")
            raise

    def _init_params(self, **kwargs):
        self.strategy = {}
        self.indicator = {
            'rsi': rsi
        }
        self.lock = kwargs.get('lock')
        return
    
    def filter_settings(self):
        with self.lock: # 調用 open_json_file 獲取 JSON 數據，並過濾掉值為空的鍵值對
            json_data = {k: v for k, v in open_json_file()['items'].items() if v}

        # 遍歷 json_data 中的所有鍵值對
        for key, items in json_data.items():
            # 過濾 strategy 字串以 'smc' 結尾的項目
            filtered_items = [item for item in items if item.get('strategy', '').startswith("statarb")]
            if filtered_items:  # 只有非空列表才添加到 self.strategy
                self.strategy[key] = filtered_items

        return self.strategy

    def filter_night(self):
        # 在 self.strategy 上進一步過濾 cross_day 為 False 的項目
        for key in list(self.strategy.keys()):  # 使用 list 避免運行時修改字典
            self.strategy[key] = [
                item for item in self.strategy[key]
                if item.get('params', {}).get('night', False) is False
            ]
            if not self.strategy[key]:  # 如果過濾後列表為空，移除該鍵
                del self.strategy[key]
        
        self.log.info(f"將要過濾night為False的statarb, 過濾出: {len(self.strategy)} 個\n策略: {self.strategy}")
        return self.strategy

    def filter_strategy(self):
        self.log.info(f"將要重新計算全部策略的statarb: {len(self.strategy)} 個\n 策略: {self.strategy}")
        return self.strategy

    async def calculate_coeff(self, lock):
        try:
            api = sj.Shioaji()
            api.login(
                api_key=os.getenv('DATA_KEY'),
                secret_key=os.getenv('DATA_SECRET'),
                fetch_contract=False,
            )
            api.fetch_contracts(contract_download=True)

            try:
                usage = api.usage()
                self.log.info(f"剩餘可用API: {usage}\n")
            except TimeoutError as e:
                self.log.warning(f"無法獲得 API 使用量: {e}\n")

            with lock:
                setting = open_json_file()

            for category, items in self.strategy.items():
                for item in items:
                    dt_dict = {}
                    data_dict = {}
                    statarb_type = item.get('params', {}).get('statarb_type', "beta")
                    
                    # 協整beta策略
                    if statarb_type == 'beta':
                        strategy = item["strategy"]
                        base_path = f"data/coeff/{strategy}" # 定義歷史數據路徑
                        window_trading_days = item["params"]["window_trading_days"]

                        # 計算 end 和 begin 日期
                        end = datetime.now(tz=pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d')  # 當前日期，例如 '2025-04-15'
                        begin = (datetime.now(tz=pytz.timezone('Asia/Taipei')) - timedelta(days=5)).strftime('%Y-%m-%d')  # 當前日期減 3 天，例如 '2025-04-12'

                        # 獲取歷史 K 棒資料
                        for code in item['code']:
                            if code in data_dict:
                                self.log.info(f"跳過: {code} ({category}), 已經獲取過")
                                continue
                            
                            # 根據 category 選擇合約類型
                            if category == 'stock':
                                contract = api.Contracts.Stocks[code]
                            elif category == 'future':
                                contract = api.Contracts.Futures[code]
                            else:
                                self.log.error(f"未知的分類 key：{category}")
                                continue
                            
                            self.log.info(f"獲取k棒資料中:{code}, 開始日期: {begin}, 結束日期: {end}, 合約: {contract}")
                            
                            # 調用 API 獲取歷史 K 棒資料
                            kbars = api.kbars(
                                contract=contract,
                                start=begin,  # 例如 '2025-04-14'
                                end=end,      # 例如 '2025-04-14'
                            )

                            # 轉為 DataFrame
                            df = pd.DataFrame({**kbars})
                            
                            self.log.info(f"k棒獲取完畢: {df.head(5)}")

                            # 確保 ts 欄位為 datetime，並設置為索引
                            df['ts'] = pd.to_datetime(df['ts'])
                            # 將 OHLCV 欄位名稱改為小寫
                            df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
                            if 'ts' in df.columns:
                                df.set_index('ts', inplace=True)

                            data_dict[code] = df
                            self.log.info(f"資料獲取完畢")

                        # 檢查 data_dict 是否為空
                        if not data_dict:
                            self.log.error(f"未獲取到任何 {category} 的 K 棒資料，data_dict 為空")
                            continue  # 跳過後續處理，例如窗口篩選
                        
                        # 如果數據足夠，開始正常處理
                        for code in item['code']:
                            # 篩選窗口
                            window_df, _ = self.filter_and_check_window(data_dict[code], window_trading_days, code, f"{base_path}/{code}")  # 此處已確保數據足夠

                            if item['params'].get('indicator'):  # 判斷params中計算是否是使用技術指標, 多個技術指標順序對應者商品A, B的coint計算 Ex: indicator: {rsi, macd} => {A: rsi(時間序列), B: macd(時間序列)}
                                indicator_dict = item['params']['indicator']
                                for indicator_type, indicator_param in indicator_dict.items():
                                    k_time = convert_ohlcv(window_df, item['params']['K_time'])
                                    indicator_func = self.indicator.get(indicator_type)
                                    if indicator_func:
                                        dt_dict[code] = indicator_func(k_time['close'], indicator_param)
                                    else:
                                        raise ValueError(f"Indicator function for '{indicator_type}' not found in self.indicator")
                            else:
                                dt_dict[code] = convert_ohlcv(window_df, item['params']['K_time'])['close']

                        # 依照ABC生成時間序列
                        column_names = [chr(65 + i) for i in range(len(dt_dict))]
                        combined_df = pd.DataFrame(dict(zip(column_names, dt_dict.values()))).dropna()

                        num_codes = len(combined_df.columns)
                        if num_codes == 2: # 只有兩個標的協整beta計算
                            beta, _ = self.analyze_two_cointegration(combined_df)

                        with self.lock:
                            update_settings(category, item['code'], item['strategy'], {'beta': beta})

            # 登出 API
            api.logout()
            self.log.info("Shioaji API logged out")
            return

        except Exception as e:
            err = f"計算係數出現錯誤: {e}"
            self.log.error(err)
            raise RuntimeError(err)

    def analyze_two_cointegration(self, data, debug=True):
        """
        使用 Johansen 檢定計算協整參數，並回傳 beta_coefficient
        增加錯誤處理和數據檢查
        """
        # 只选择数值列 'A' 和 'B'
        numeric_data = data[['A', 'B']].dropna()  # 移除缺失值

        # 提取日期範圍
        start_date = numeric_data.index.min().strftime('%Y-%m-%d')
        end_date = numeric_data.index.max().strftime('%Y-%m-%d')

        # 記錄日期範圍
        self.log.info(f"協整分析數據範圍: {start_date} 至 {end_date}, 共 {len(numeric_data)} 筆數據")

        # 檢查數據是否足夠
        if len(numeric_data) < 10:  # 設定一個最小數據點閾值
            if debug:
                self.log.info("窗口期數據不足")
            return 1.0, None  # 返回默認值

        # 檢查方差
        var_A = numeric_data['A'].var()
        var_B = numeric_data['B'].var()
        if var_A < 1e-8 or var_B < 1e-8:  # 檢查方差是否接近零
            if debug:
                self.log.info(f"方差過小: var_A={var_A}, var_B={var_B}")
            return 1.0, None  # 返回默認值

        try:
            result = coint_johansen(numeric_data, det_order=0, k_ar_diff=1)  # 增加 k_ar_diff
            beta = result.evec[:, 0]  # 第一個協整向量
            beta_A = beta[0]

            # 避免除以接近零的值
            if abs(beta_A) < 1e-8:
                if debug:
                    self.log.info("協整系數接近零")
                return 1.0, None

            beta_B = beta[1]
            beta_coefficient = -beta_B / beta_A

            if debug:
                self.log.info(f"分析視窗共整向量: {beta}, beta: {beta_coefficient}")

            return beta_coefficient, None

        except Exception as e:
            if debug:
                self.log.error(f"協整分析錯誤: {e}")
            return 1.0, None  # 發生錯誤時返回默認值

    def filter_and_check_window(self, df, window_trading_days, code=None, csv_path=None):
        """篩選窗口數據並檢查交易日數量是否足夠"""
        # 獲取所有獨特的交易日期（有數據的日期）
        unique_dates = pd.Series(df.index.date).unique()

        if len(unique_dates) < window_trading_days:
            if code and csv_path:
                # 確保 base_path 存在，若不存在則創建
                if not os.path.exists(csv_path):
                    os.makedirs(csv_path)
                self.log.info(f"{code}資料的交易日數量不足, 僅有{len(unique_dates)}天, 但是需要 {window_trading_days}天. 將此pandas存入 {csv_path}.")
            return None, False  # 數據不足

        # 從最新的日期開始，選取前 window_trading_days 個交易日
        cutoff_date = unique_dates[-(window_trading_days):][0]  # 選取第 window_trading_days 個交易日
        window_df = df[df.index.date >= cutoff_date]

        # 再次確認交易日數量
        unique_trading_days = len(pd.Series(window_df.index.date).unique())
        if unique_trading_days < window_trading_days:
            if code and csv_path:
                if not os.path.exists(csv_path):
                    os.makedirs(csv_path)
                self.log.info(f"{code}篩選後的交易日數量不足, 僅有{unique_trading_days}天, 但是需要 {window_trading_days}天. 將此pandas存入 {csv_path}.")
                df.to_csv(f"{csv_path}/{code}.csv", index=True)
            return None, False

        # 提取篩選後的開始和結束日期
        start_date = window_df.index.min().strftime('%Y-%m-%d')
        end_date = window_df.index.max().strftime('%Y-%m-%d')

        # 記錄篩選的日期範圍
        if code:
            self.log.info(f"{code} 選出的計算數據範圍: {start_date} 至 {end_date}, 共 {unique_trading_days} 個交易日")
        else:
            self.log.info(f"選出的計算數據範圍: {start_date} 至 {end_date}, 共 {unique_trading_days} 個交易日")

        return window_df, True  # 返回窗口數據和檢查成功的標誌
