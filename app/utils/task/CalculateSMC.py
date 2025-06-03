from utils.log import get_module_logger
from utils.task.Task import Task
from utils.file import open_json_file, update_settings
from datetime import timedelta, datetime
from utils.k import convert_ohlcv
from utils.smartmoneyconcepts import smc
import pandas as pd
import shioaji as sj
import os, pytz

class CalculateSMC(Task):
    def __init__(self):
        self.log = get_module_logger('utils/task/CalculateSMC')

    @property
    def name(self) -> str:
        return "calculate_smc"

    async def execute(self, **kwargs) -> None:
        try:
            self.log.info("運行calculate_smc task")
            self._init_params(**kwargs)
            self.filter_settings()

            if kwargs.get('redo') is True:
                self.filter_strategy()
            else:
                self.filter_monitor()

            self.refetch_data()
            self.calculate_smc()
            self.log.info("計算完畢\n\n")
            return
        except Exception as e:
            self.log.error(f"calculate_smc, 出現錯誤: {str(e)}")
            raise

    def _init_params(self, **kwargs):
        self.strategy = {}
        self.smc_indicators = {}
        self.data_dict = {}
        self.lock = kwargs.get('lock')
        return

    def filter_settings(self):
        with self.lock: # 調用 open_json_file 獲取 JSON 數據，並過濾掉值為空的鍵值對
            json_data = {k: v for k, v in open_json_file()['items'].items() if v}

        # 遍歷 json_data 中的所有鍵值對
        for key, items in json_data.items():
            # 過濾 strategy 字串以 'smc' 結尾的項目
            filtered_items = [item for item in items if item.get('strategy', '').endswith('smc')]
            if filtered_items:  # 只有非空列表才添加到 self.strategy
                self.strategy[key] = filtered_items

        return self.strategy

    def filter_monitor(self):
        # 在 self.strategy 上進一步過濾 monitor 為 False 的項目
        for key in list(self.strategy.keys()):  # 使用 list 避免運行時修改字典
            self.strategy[key] = [
                item for item in self.strategy[key]
                if item.get('params', {}).get('monitor', False) is False
            ]
            if not self.strategy[key]:  # 如果過濾後列表為空，移除該鍵
                del self.strategy[key]
        
        self.log.info(f"將要重新計算monitor監控為False(有進場或止損出場)的SMC, 過濾出: {len(self.strategy)} 個\n策略: {self.strategy}")
        return self.strategy

    def filter_strategy(self):
        self.log.info(f"將要重新計算全部策略的SMC: {len(self.strategy)} 個\n 策略: {self.strategy}")
        return self.strategy

    def refetch_data(self):
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

        # 計算 end 和 begin 日期
        end = datetime.now(tz=pytz.timezone('Asia/Taipei')).strftime('%Y-%m-%d')  # 當前日期，例如 '2025-04-15'
        begin = (datetime.now(tz=pytz.timezone('Asia/Taipei')) - timedelta(days=14)).strftime('%Y-%m-%d')  # 當前日期減 14 天

        # 遍歷 self.strategy 中的每個項目
        for category, items in self.strategy.items():
            for item in items:
                for code in item['code']: # 遍歷每個 code, 獲取歷史 K 棒資料
                    try:
                        if code in self.data_dict:
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
                        self.log.info(f"k棒獲取完畢: {df.tail(5)}")

                        # 確保 ts 欄位為 datetime，並設置為索引
                        df['ts'] = pd.to_datetime(df['ts'])
                        # 將 OHLCV 欄位名稱改為小寫
                        df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})

                        if 'ts' in df.columns:
                            df.set_index('ts', inplace=True, drop=False)

                        self.data_dict[code] = df
                        self.log.info(f"資料獲取完畢")

                        # 檢查 data_dict 是否為空
                        if not self.data_dict:
                            self.log.error(f"未獲取到任何 {category} 的 K 棒資料，data_dict 為空")
                            continue  # 跳過後續處理，例如窗口篩選
                        
                    except Exception as e:
                        self.log.error(f"shioaji獲取: {code}, 歷史資料失敗: {e}")

        # 登出 API
        api.logout()
        self.log.info("Shioaji API logged out")
        return
     
    def calculate_smc_indicators(self, df, code, swing_length, close_break=True):
        """
        計算 SMC 指標（FVG, OB, Liquidity, BOS, CHOCH）並返回統一的字典格式。

        參數:
        - df: Pandas DataFrame，包含 'open', 'high', 'low', 'close', 'volume' 列
        - swing_length: 波段高低點計算的窗口大小
        - close_break: BOS/CHOCH 是否基於收盤價突破

        返回:
        - 字典，包含以下 SMC 指標：
          - 'FVG': FVG 數據
          - 'OB': Order Block 數據
          - 'Liquidity': Liquidity 數據
          - 'BOS': BOS 數據（僅非空）
          - 'CHOCH': CHOCH 數據（僅非空）
          - 'Swing': 波段高低點數據
        """
        # 確保輸入 df 的索引是 DatetimeIndex
        df.index = pd.to_datetime(df.index)

        # 計算波段高低點
        swing_data = smc.swing_highs_lows(df, swing_length=swing_length)
        swing_data.index = df.index  # 對齊索引

        # 計算 FVG
        fvg_data = smc.fvg(df)
        fvg_data.index = df.index  # 對齊索引

        # 計算 Order Blocks
        ob_data = smc.ob(df, swing_data)
        ob_data.index = df.index  # 對齊索引

        # 計算 Liquidity
        liquidity_data = smc.liquidity(df, swing_data)
        liquidity_data.index = df.index  # 對齊索引

        # 計算 BOS 和 CHOCH
        bos_choch_data = smc.bos_choch(df, swing_data, close_break=close_break)
        bos_choch_data.index = df.index  # 對齊索引

        # 分離 BOS 和 CHOCH
        bos_data = bos_choch_data[bos_choch_data['BOS'].notna()][['BOS', 'Level', 'BrokenIndex']]
        choch_data = bos_choch_data[bos_choch_data['CHOCH'].notna()][['CHOCH', 'Level', 'BrokenIndex']]

        # 構建輸出字典
        self.smc_indicators[code] = {
            'FVG': fvg_data,
            'OB': ob_data,
            'Liquidity': liquidity_data,
            'BOS': bos_data,
            'CHOCH': choch_data,
            'Swing': swing_data
        }

        return self.smc_indicators
    
    def get_indicator_by_code(self, code):
        # 獲取 SMC                    
        if code not in self.smc_indicators:
            self.log.warning(f"代號: {code} 不存在於smc_indicator")
            return 0
        
        indicator = self.smc_indicators[code]
        return {
            'ob_data': indicator.get('OB'),
            'fvg_data': indicator.get('FVG'),
            'liquidity': indicator.get('Liquidity'),
            'bos': indicator.get('BOS'),
            'choch': indicator.get('CHOCH'),
            'swing': indicator.get('Swing')
        }
    
    def calculate_smc(self):
        for category, items in self.strategy.items(): # 遍歷 self.strategy 中的每個鍵值對
            for item in items: # 獲取 code 列表和 params
                params = item.get('params', {})
                smc_type = params.get('smc_type', "ob_fvg")
                for code in item['code']:
                    if code not in self.data_dict: # 檢查 self.data_dict 中是否有該 code 的數據
                        self.log.warning(f"代號: {code} ({category}) 不存在於data_dict")
                        continue

                    self.log.info(f"當前: {code} SMC交易類型為: {smc_type}")

                    if smc_type == 'ob_fvg':
                        # 主時間軸 Ex: 4HR -> (計算OB與FVG)
                        data1 = convert_ohlcv(self.data_dict[code], params.get('k_time_long'))
                    
                        self.log.info(f'1分K轉換N分鐘的K棒資料: {data1.head(5)}')

                        self.calculate_smc_indicators(data1, code, swing_length=params.get('swing_length_4h'), close_break=params.get('close_break'))
              
                        smc = self.get_indicator_by_code(code)
                        
                        # 大時間級別決定交易方向(多或空)
                        direction, ob = self.ob_fvg(code, smc['ob_data'], smc['fvg_data'])
            
                        if direction == 0: # 無交易方向, 將setting設定中monitor設定為false不監控
                            with self.lock:
                                update_settings(category, item['code'], item['strategy'], {'monitor': False})
                            return
                        
                        # 有交易方向, 將交易方向, ob_top, ob_bottom, 監控, 進行相對應的參數設定
                        with self.lock: 
                            update_settings(category, item['code'], item['strategy'], {'direction': direction, 'monitor': True, 'ob_top': ob['Top'], 'ob_bottom': ob['Bottom']})
                        
                        return
                    else: # 未來如有更多SMC策略
                        pass

        return
        
    def ob_fvg(self, code, ob_data, fvg_data):
        # 確保 OB 和 FVG 數據不為空
        if ob_data is None or fvg_data is None:
            self.log.info(f"{code}: 沒有FVG和OB")
            return (0, None)
        
        # 獲取最新的 OB 和 FVG（從後往前遍歷）
        valid_ob = None
        for idx in ob_data.index[::-1]:  # 從最後一行向前遍歷
            if pd.notna(ob_data.loc[idx, 'OB']):  # 檢查 OB 是否為非空
                valid_ob = ob_data.loc[idx]
                break
            
        valid_fvg = None
        for idx in fvg_data.index[::-1]:  # 從最後一行向前遍歷
            if pd.notna(fvg_data.loc[idx, 'FVG']):  # 檢查 FVG 是否為非空
                valid_fvg = fvg_data.loc[idx]
                break
            
        # 檢查是否找到有效的 OB 和 FVG
        if valid_ob is None or valid_fvg is None:
            self.log.info(f"{code}: 無法找到有效的OB({valid_ob})或FVG({valid_fvg})")
            return (0, None)

        # 檢查 OB 和 FVG 的方向是否一致
        ob_value = valid_ob['OB']
        fvg_value = valid_fvg['FVG']
        if ob_value != fvg_value:
            self.log.info(f"{code}: OB({ob_value})和FVG({fvg_value})方向不一致")
            return (0, None)

        # 檢查 OB 是否在時間上早於 FVG
        ob_time = valid_ob.name  # 獲取 OB 的時間戳
        fvg_time = valid_fvg.name # 獲取 FVG 的時間戳
        if ob_time >= fvg_time:
            self.log.info(f"{code}: OB時間 ({ob_time}) 出現時間晚於FVG時間 ({fvg_time})")
            return (0, None)

        # 如果 OB 和 FVG 方向一致且 OB 在前，返回交易方向
        self.log.info(f"{code}: OB出現時間 {ob_time} - 交易方向 ({ob_value}), FVG出現時間 {fvg_time} - 交易方向 ({fvg_value}), OB出現早於FVG")
        if ob_value == 1:
            self.log.info(f"{code}: OB_FVG出現看漲信號")
            return (1, valid_ob)
        elif ob_value == -1:
            self.log.info(f"{code}: OB_FVG出現看跌信號")
            return (-1, valid_ob)

        return (0, None)
    
    