from abc import ABC, abstractmethod
from db.redis import get_redis_connection

class AbstractDatasource(ABC):
    def __init__(self):
        self.redis = get_redis_connection()

    @abstractmethod
    async def fetch_market_data(self, symbol):
        pass
