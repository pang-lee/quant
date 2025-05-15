from .abc.AbstractCalculation import AbstractCalculation
from utils.log import get_module_logger

class Zscore(AbstractCalculation):
    def __init__(self, params, data, log_name):
        super().__init__(params, data)
        self.log = get_module_logger(f"{log_name}/vwap")