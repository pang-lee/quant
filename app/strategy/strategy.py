import importlib
from utils.log import get_module_logger

class Strategy:
    def __init__(self, symbol, item, datas):
        self.strategies = None
        self.symbol = symbol
        self.item = item
        self.data = datas
        self.log = get_module_logger(f"strategy/loader")
        self.load_strategy(item)
        
    def load_strategy(self, item):
        try:
            # 模組名稱小寫，類名首字母大寫（PascalCase）
            class_name = item['strategy'].capitalize()
            module_name = item['strategy'].lower()
            module_path = f'strategy.strategies.{module_name}'
        
            # 動態導入模組
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, class_name)
            strategy_instance = strategy_class(self.data, self.item, self.symbol)
            self.strategies = strategy_instance
        except Exception as e:
            self.log.error(f"Strategy 加載錯誤: {e}")
        except ImportError:
            self.log.error(f"Strategy 種類 '{class_name}' 不存在.")
        except AttributeError:
            self.log.error(f"Strategy class '{class_name.capitalize()}' 沒有找到.")
        
        return [(self.symbol, self.item, False, {}, {}, {})]

    def execute(self):
        if not self.data or not self.strategies:
            self.log.info(f"當前無資料: {self.data}, 或沒加載策略: {self.strategies}")
            return [(self.symbol, self.item, False, {}, {}, {})]
        
        return self.strategies.execute()
