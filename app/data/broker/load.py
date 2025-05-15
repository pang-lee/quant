import importlib, os, inspect
from data.broker.abc.AbstractDatasource import AbstractDatasource

def load_datasources():
    """動態加載所有資料源，返回字典"""
    datasource_classes = {}
    dir = os.path.dirname(__file__)  # broker 資料夾路徑

    for root, _, files in os.walk(dir):
        if 'abc' in root:
            continue
        
        for file in files:
            if file.endswith(".py") and file not in ["__init__.py", "load.py"]:
                # 模組名稱路徑處理
                module_path = os.path.relpath(os.path.join(root, file), dir).replace(os.sep, ".")[:-3]
                module = importlib.import_module(f"data.broker.{module_path}")
                
                # 動態加載資料源類
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, AbstractDatasource) and obj is not AbstractDatasource:
                        datasource_classes[name] = obj
                        
    return datasource_classes

