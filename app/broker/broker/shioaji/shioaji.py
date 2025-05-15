from broker.broker.shioaji.verify.shioaji import get_shioaji_instance
from broker.broker.shioaji.order.shioajiOrder import ShioajiOrderManager
from broker.abc.AbstractBroker import AbstractBroker
import threading

class shioaji(AbstractBroker):
    def __init__(self, async_queue, items, log):
        super().__init__(items, log)
        self.simulation = True
        self.api = get_shioaji_instance(simulation=self.simulation)
        self.order_manager = ShioajiOrderManager(self.api, async_queue, log, self)
        self.contracts = []
        self.event_lock = threading.Lock()  # 保護回調事件和結果
        self.order_events = {}  # 存儲訂單的 Event 對象
        self.order_results = {}  # 存儲訂單的回調結果
    
    # ---------------------------- 下單程序入口 ----------------------------
    # 從Thread Pool中, 進行下單的判斷
    def place_order(self, order_params, result_type):
        try:
            if not order_params.get('code'):
                self.log.error(f"訂單參數:{order_params}, 沒有包含下單代號")
                return False

            self.contracts.clear()
            self.check_commodity(order_params)
            order_method = self._get_order_method(result_type)
            
            # 生成唯一的訂單 ID
            order_id = order_params['trade_id']
            with self.event_lock:
                self.order_events[order_id] = threading.Event()

            # 遍歷 contracts，每個合約與帳戶進行下單
            for entry in self.contracts:
                contract = entry['contract']
                account = entry['account']
                if not order_method(contract, account, order_params):
                    self.log.error(f"shioaji - order_mthod 下單失敗: {order_params}")
                    with self.event_lock:
                        del self.order_events[order_id]
                    return False

            # 等待回調（設置超時）
            self.log.info(f"{order_params['code']}/{order_params['strategy']} 正在等待 {order_id} 的回調...")
            self.order_events[order_id].wait(timeout=10)
            
            # 檢查回調結果
            with self.event_lock:
                result = self.order_results.get(order_id, False)
                del self.order_events[order_id]
                self.order_results.pop(order_id, None)  # 安全刪除，無需檢查存在

            if result:
                self.log.info(f"{order_id} 成功確認\n")
                return True
            else:
                self.log.error(f"{order_id} 回調失敗或超時\n")
                return False
        
        except Exception as e:
            self.log.error(f"Shioaji - place_order下單發生錯誤: {e}")
            return False
    
    def check_commodity(self, order_params):
        symbol = order_params['symbol']
        code = order_params['code']
        contracts = []
        account = None
        
        # 初始化倉位控制
        order_params['position_type'] = self.build_position_control(order_params=order_params['position_type'])
        
        # 根據 symbol 處理不同商品類型的代碼
        if symbol == 'stock':
            account = self.api.stock_account
            contracts = [self.api.Contracts.Stocks[code]]
        elif symbol == 'future':
            account = self.api.futopt_account
            contracts = [self.api.Contracts.Futures[code]]
        elif symbol == 'option':
            account = self.api.futopt_account
            contracts = [self.api.Contracts.Options[code]]
        else:
            self.log.error(f"不支援的商品類型: {symbol}")
            return

        # 將每個 contract 與 account 配對為字典，並加入 self.contracts
        return self.contracts.extend({'contract': contract, 'account': account} for contract in contracts)

    # ---------------------------- 帳戶訊息API調用 ----------------------------
    def check_balance(self):
        balance = self.api.account_balance()
                    
        # 如果獲取失敗，並且 errmsg 不是空，則返回錯誤訊息
        if balance and balance.errmsg:
            return balance.errmsg
        else:
            return balance
  
    def check_margin(self):
        margin = self.api.margin(self.api.futopt_account)

        if margin:
            return margin
        else:
            return None

    def check_settle(self):
        settlements = self.api.settlements(self.api.stock_account)
        
        # 否則回傳 settlements 陣列
        return settlements
    
    def get_unrealized_pnl_details(self, account="all"):
        """
        查詢未實現損益以及各部位的詳細資料，並整理成總損益與明細資料。

        參數:
          api: 已登入的 Shioaji API 實例
          account: 查詢的帳戶類型，接受 "stock"、"future" 或 "all"
                   "stock" 只查詢證券部位，
                   "future" 只查詢期貨選擇權部位，
                   "all" 則同時查詢全部帳戶。
          unit: 針對證券部位時的單位（預設為 Unit.Common，即整股，若要查詢零股可設定 Unit.Share）

        回傳:
          回傳一個字典，包含：
              "total_pnl": 所有選取帳戶的未實現損益總和
              "details": 一個 array of dict，每個 dict 的 key 為商品代號，
                         value 為該部位的詳細資料（detail）的 list
        """
        positions = []      # 用來儲存 (帳戶類型, 部位物件)
        total_pnl = 0.0

        # 查詢證券部位
        if account in ("stock", "all"):
            stock_positions = self.api.list_positions(self.api.stock_account)
            # 加入 tuple (帳戶類型, 部位)
            positions.extend([("stock", pos) for pos in stock_positions])
            total_pnl += sum(pos.pnl for pos in stock_positions)

        # 查詢期貨選擇權部位
        if account in ("future", "all"):
            futopt_positions = self.api.list_positions(self.api.futopt_account)
            positions.extend([("future", pos) for pos in futopt_positions])
            total_pnl += sum(pos.pnl for pos in futopt_positions)    
        
        # 模擬模式不進行細項查詢
        if self.simulation:
            return {
                "stock": stock_positions,
                "future": futopt_positions,
                "total_pnl": total_pnl,
                "details": []
            }
            
        # 用來儲存明細資料，依照商品代號分組（若同一商品有多筆 detail 會合併成 list）
        details_dict = {}
        
        # 對每筆部位使用 id 查詢明細
        for acc_type, pos in positions:
            if acc_type == "stock":
                pos_details = self.api.list_position_detail(self.api.stock_account, pos.id)
            elif acc_type == "future":
                pos_details = self.api.list_position_detail(self.api.futopt_account, pos.id)
            else:
                continue

            # 每筆 detail 轉成字典並依商品代號分組
            for detail in pos_details:
                # detail.__dict__ 將物件屬性轉換成字典
                detail_data = detail.__dict__
                product_code = detail_data.get("code")
                # 若此商品代號已存在，則加入 list；否則建立新 list
                if product_code in details_dict:
                    details_dict[product_code].append(detail_data)
                else:
                    details_dict[product_code] = [detail_data]

        # 將 details_dict 轉換成 array of dict，每個 dict 為 {商品代號: [明細資料,...]}
        details_array = [{code: details} for code, details in details_dict.items()]

        return {
            "total_pnl": total_pnl,
            "details": details_array
        }

    def get_realized_profit_loss_details(self, account="all", begin_date="", end_date=""):
        """
        查詢已實現損益以及各部位的詳細資料，並整理成總損益與明細資料。

        參數:
            api: 已登入的 Shioaji API 實例
            account: 查詢的帳戶類型，可接受 "stock"（證券）、"future"（期貨選擇權）或 "all"（全部）
            begin_date: 查詢起始日期（格式: 'YYYY-MM-DD'），預設為空字串（依 API 預設以當日為查詢日期）
            end_date: 查詢結束日期（格式: 'YYYY-MM-DD'），預設為空字串（依 API 預設以當日為查詢日期）
            unit: 針對證券部位時的單位（預設為 Unit.Common，即整股；若要查詢零股，可設定 Unit.Share）

        回傳:
            一個字典，包含：
                "total_pnl": 所有選取帳戶的已實現損益總和
                "details": 一個 list，每個元素是一個 dict，格式為 {商品代號: [明細資料, ...]}
                          明細資料以 dict 方式呈現（來源為 profit loss detail 的 __dict__）

        範例使用:
            result = get_realized_profit_loss_details(api, account="all", begin_date="2020-05-05", end_date="2020-05-30", unit=Unit.Common)
            print("已實現損益總和:", result["total_pnl"])
            for item in result["details"]:
                print(item)
        """
        positions = []   # 儲存 (帳戶類型, profit loss 物件) tuple
        total_pnl = 0.0

        # 查詢證券已實現損益
        if account in ("stock", "all"):
            stock_profit_loss = self.api.list_profit_loss(self.api.stock_account, begin_date, end_date)
            positions.extend([("stock", pl) for pl in stock_profit_loss])
            total_pnl += sum(pl.pnl for pl in stock_profit_loss)

        # 查詢期貨選擇權已實現損益
        if account in ("future", "all"):
            future_profit_loss =  self.api.list_profit_loss(self.api.futopt_account, begin_date, end_date)
            positions.extend([("future", pl) for pl in future_profit_loss])
            total_pnl += sum(pl.pnl for pl in future_profit_loss)

        # 模擬模式不進行細項查詢
        if self.simulation:
            return {
                "stock": stock_profit_loss,
                "future": future_profit_loss,
                "total_pnl": total_pnl,
                "details": []
            }

        # 用來儲存明細資料，以商品代號做分組
        details_dict = {}

        # 依據每筆 profit loss 物件的 id 查詢明細資料
        for acct_type, pl in positions:
            if acct_type == "stock":
                pl_details = self.api.list_profit_loss_detail(self.api.stock_account, pl.id)
            elif acct_type == "future":
                pl_details = self.api.list_profit_loss_detail(self.api.futopt_account, pl.id)
            else:
                continue

            # 將每筆 detail 轉成字典，依商品代號進行分組
            for detail in pl_details:
                detail_data = detail.__dict__
                code = detail_data.get("code")
                if code in details_dict:
                    details_dict[code].append(detail_data)
                else:
                    details_dict[code] = [detail_data]

        # 將 details_dict 轉換成 array of dict，每個 dict 格式為 {商品代號: [明細資料, ...]}
        details_array = [{code: details} for code, details in details_dict.items()]

        return {
            "total_pnl": total_pnl,
            "details": details_array
        }
