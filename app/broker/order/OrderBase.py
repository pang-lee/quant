from abc import ABC, abstractmethod
from db.redis import get_redis_connection
import queue, asyncio, pytz

class BaseOrderManager(ABC):
    def __init__(self, async_queue, log):
        self.async_queue = async_queue
        self.log = log
        self.tz = pytz.timezone('Asia/Taipei')
        self.queue = queue.Queue()
        self.redis = get_redis_connection()
        
        # 啟動異步任務來持續將資料從同步隊列轉移到異步隊列
        asyncio.create_task(self.transfer_to_async_queue())  # 在初始化時啟動異步任務

    async def transfer_to_async_queue(self):
        while True:
            # 檢查同步隊列是否有資料
            if not self.queue.empty():
                data = self.queue.get()  # 從同步隊列獲取資料
                await self.async_queue.put(data)  # 將資料放入異步隊列
                self.queue.task_done()  # 標記同步隊列中的任務為完成
            await asyncio.sleep(1)  # 稍微休息一會兒，避免CPU過高使用
    
    # 下單方法，子類只需實現 _handle_order 即可完成業務邏輯
    def place_buy_order(self, contract, account, order_params):
        """下多單"""
        order_params['order_action'] = 'Long'
        return self._handle_order("Buy", contract, account, order_params)

    def place_sell_order(self, contract, account, order_params):
        """下空單"""
        order_params['order_action'] = 'Short'
        return self._handle_order("Sell", contract, account, order_params)

    def place_stop_loss_buy_order(self, contract, account, order_params):
        """多倉止損"""
        order_params['order_action'] = 'Long Stop Loss'
        return self._handle_order("Sell", contract, account, order_params)

    def place_stop_loss_sell_order(self, contract, account, order_params):
        """空倉止損"""
        order_params['order_action'] = 'Short Stop Loss'
        return self._handle_order("Buy", contract, account, order_params)

    def place_take_profit_buy_order(self, contract, account, order_params):
        """多倉止盈"""
        order_params['order_action'] = 'Long Profit'
        return self._handle_order("Sell", contract, account, order_params)

    def place_take_profit_sell_order(self, contract, account, order_params):
        """空倉止盈"""
        order_params['order_action'] = 'Short Profit'
        return self._handle_order("Buy", contract, account, order_params)

    def place_close_buy_order(self, contract, account, order_params):
        """多倉平倉"""
        order_params['order_action'] = 'Long Close'
        return self._handle_order("Sell", contract, account, order_params)

    def place_close_sell_order(self, contract, account, order_params):
        """空倉平倉"""
        order_params['order_action'] = 'Short Close'
        return self._handle_order("Buy", contract, account, order_params)

    def place_dynamic_price_adjustment_buy(self, contract, account, order_params):
        """動態多倉改價"""
        order_params['order_action'] = 'Long Dynamic Change Price'
        return self._handle_order("DynamicAdjustBuy", contract, account, order_params)

    def place_dynamic_price_adjustment_sell(self, contract, account, order_params):
        """動態空倉改價"""
        order_params['order_action'] = 'Short Dynamic Change Price'
        return self._handle_order("DynamicAdjustSell", contract, account, order_params)
        
    def place_cancel_order(self, contract, account, order_params):
        """取消訂單"""
        order_params['order_action'] = 'Cancel Order'
        return self._handle_order(account, order_params)

    # 留給子類實現的抽象方法
    @abstractmethod
    async def _handle_order(self, action, contract, account, order_params):
        pass