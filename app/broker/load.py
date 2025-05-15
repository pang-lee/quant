import importlib, os, inspect
from broker.abc.AbstractBroker import AbstractBroker
from utils.log import get_module_logger

def load_brokers(queue, items):
    brokers = {}
    broker_dir = os.path.join(os.path.dirname(__file__), "broker")  # broker 資料夾路徑

    # 遞歸遍歷 broker/broker 目錄及其子目錄
    for root, _, files in os.walk(broker_dir):
        # 過濾出每個卷商的.py文件
        for file in files:
            if file.endswith(".py") and file != "__init__.py" and file != "AbstractBroker.py":
                module_path = os.path.relpath(os.path.join(root, file), broker_dir).replace(os.sep, ".")[:-3]

                # 動態加載模塊
                module = importlib.import_module(f"broker.broker.{module_path}")
                
                # 動態加載卷商類
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, AbstractBroker) and obj is not AbstractBroker:
                        brokers[name] = obj(async_queue=queue, items=items, log=get_module_logger(f"broker/{name}"))

    return brokers