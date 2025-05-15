import os, importlib
from position.type.abc.AbstractPositionControl import AbstractPositionControl

def load_position_controls(position_directory="position/type"):
    position_controls = {}
    
    # 瀏覽 type 目錄下所有文件
    for filename in os.listdir(position_directory):
        if filename.endswith(".py"):
            # 移除 .py 扩展名
            module_name = filename[:-3]
            class_name = module_name.capitalize()  # "dynamic" -> "Dynamic"
            module_path = f"position.type.{module_name}"
            
            try:
                # 動態加載模組
                module = importlib.import_module(module_path)
                
                if hasattr(module, class_name):
                    cls = getattr(module, class_name)                    
                    if issubclass(cls, AbstractPositionControl):  # 確保是 AbstractPositionControl 的子類
                        position_controls[class_name.lower()] = cls  # 初始化並存入 dict
                        
            except Exception as e:
                print(f"Error when loading position control {module_name}: {e}")
    
    return position_controls