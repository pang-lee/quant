import os
import shioaji as sj
from dotenv import load_dotenv
load_dotenv()

_shioaji_instance = None  # 用於存儲 Redis 單例實例

def get_shioaji_instance(simulation=True):
    global _shioaji_instance
    if _shioaji_instance is None:  # 如果尚未創建連線，則創建
        api = sj.Shioaji(simulation=simulation)
        api.login(
            api_key=os.getenv('API_KEY'),
            secret_key=os.getenv('SECRET_KEY'),
            subscribe_trade=simulation,
            fetch_contract=False,
        )
        api.fetch_contracts(contract_download=True)

        _shioaji_instance = api
        
    return _shioaji_instance  # 返回已存在的連線實例
