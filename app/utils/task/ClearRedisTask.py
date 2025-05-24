from db.redis import clear_redis
from utils.log import get_module_logger
from utils.task.Task import Task

class ClearRedisTask(Task):
    def __init__(self):
        self.log = get_module_logger('utils/task/ClearRedisTask')

    @property
    def name(self) -> str:
        return "clear_redis"

    async def execute(self, lock) -> None:
        try:
            self.log.info("運行clear_redis task")
            await clear_redis(lock)
        except Exception as e:
            self.log.error(f"clear_redis出現錯誤: {str(e)}")
            raise