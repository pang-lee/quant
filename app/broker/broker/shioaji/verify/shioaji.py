import os
import shioaji as sj
from distutils.util import strtobool
from broker.shioaji.shioaji import shioaji
from data.broker.shioaji.ShioajiDataSource import ShioajiDataSource
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

def logout_shioaji():
    global _shioaji_instance
    # simulation = bool(strtobool(os.getenv('IS_DEV', 'true')))
    simulation = True
    if _shioaji_instance is not None:
        try:
            _shioaji_instance.logout()
            _shioaji_instance = None
            api = get_shioaji_instance(simulation)
            shioaji.reinit_api(api)
            ShioajiDataSource.reinit_api(api)
        except Exception as e:
            raise RuntimeError(f"shioaji登出出錯: {e}")
    else:
        raise RuntimeError("找不到shioaji instance, 無法登出")
