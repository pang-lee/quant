from abc import ABC, abstractmethod
from position.load import load_position_controls

class AbstractBroker(ABC):
    """券商基類"""
    def __init__(self, items, log):
        self.log = log
        self.items = items
        self.position_controls = load_position_controls()  # 加載所有艙位控制

    def build_position_control(self, order_params):
        return self.position_controls[order_params['class_name']](take_profit=order_params['params']['take_profit'], stop_loss=order_params['params']['stop_loss'], tick_size=order_params['params']['tick_size'], symbol=order_params['params']['symbol'], redis_key=order_params['params']['redis_key'])
    
    def _get_order_method(self, result_type):
        """根據 result_type 分發至不同的訂單管理方法"""
        methods = {
            0: self.order_manager.place_cancel_order,
            1: self.order_manager.place_buy_order,
            -1: self.order_manager.place_sell_order,
            2: self.order_manager.place_stop_loss_buy_order,
            -2: self.order_manager.place_stop_loss_sell_order,
            3: self.order_manager.place_take_profit_buy_order,
            -3: self.order_manager.place_take_profit_sell_order,
            4: self.order_manager.place_close_buy_order,
            -4: self.order_manager.place_close_sell_order,
            5: self.order_manager.place_dynamic_price_adjustment_buy,
            -5: self.order_manager.place_dynamic_price_adjustment_sell,
        }
        if result_type not in methods:
            raise ValueError(f"Unknown result type: {result_type}")
        
        return methods[result_type]
        
    @abstractmethod
    def check_commodity(self):
        pass
