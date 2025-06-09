from dotenv import load_dotenv
load_dotenv()
import shioaji as sj
import os

api = sj.Shioaji(simulation=True)
api.login(
    api_key=os.getenv('API_KEY1'),
    secret_key=os.getenv('SECRET_KEY1'),
    subscribe_trade=True,
    fetch_contract=False,
)
api.fetch_contracts(contract_download=True)

# 取得 TMFR1（近月）與 TMFR2（遠月）合約
tmfr1_contract = api.Contracts.Futures.TMFR1
tmfr2_contract = api.Contracts.Futures.TMFR2

# 建立組合單合約
combo_contract = sj.contracts.ComboContract(
    legs=[
        sj.contracts.ComboBase(
            contract=tmfr1_contract,
            action=sj.constant.Action.Buy,  # 買入 TMFR1
            unit=1  # 委託數量
        ),
        sj.contracts.ComboBase(
            contract=tmfr2_contract,
            action=sj.constant.Action.Sell,  # 賣出 TMFR2
            unit=1  # 委託數量
        )
    ]
)

# 建立組合單委託
combo_order = api.ComboOrder(
    contract=combo_contract,
    order=sj.order.Order(
        price=0.0,  # 市價單設為 0，限價單需指定價格
        quantity=1,
        price_type=sj.constant.StockPriceType.MKT,  # 市價單（或用 LMT 限價單）
        order_type=sj.constant.OrderType.IOC,       # 立即成交或取消
        octype=sj.constant.FuturesOCType.New,       # 新倉
        account=api.futopt_account                   # 期貨帳號
    )
)

# 下單
trade = api.place_order(combo_contract, combo_order)

# 更新組合單狀態
api.update_combostatus()

# 檢查委託狀態
combo_status = api.list_combo_trades()
for status in combo_status:
    print(f"委託 ID: {status.id}, 狀態: {status.status}, 訊息: {status.msg}")