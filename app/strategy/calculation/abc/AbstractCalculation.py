from abc import ABC, abstractmethod
from datetime import datetime

class AbstractCalculation(ABC):
    def __init__(self, params, data): # 初始位置在AbstractStrategy -> load_calculation()
        self.cur_time =  datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.params = params
        self.data = data

    @abstractmethod
    def execute(self):
        """抽象方法，執行策略"""
        pass
    
    @abstractmethod
    def calculation(self):
        """抽象方法，執行計算"""
        pass
    
    @abstractmethod
    def short_signal(self):
        pass
    
    @abstractmethod
    def long_signal(self):
        pass
    
    