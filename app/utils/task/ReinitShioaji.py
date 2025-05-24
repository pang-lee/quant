from utils.log import get_module_logger
from utils.task.Task import Task
from broker.broker.shioaji.verify.shioaji import logout_shioaji

class ReinitShioaji(Task):
    def __init__(self):
        self.log = get_module_logger('utils/task/ReinitShioaji')

    @property
    def name(self) -> str:
        return "reinit_shioaji"

    async def execute(self) -> None:
        try:
            self.log.info("運行reinit_shioaji task, 重新登入shioaji")
            await logout_shioaji()
        except Exception as e:
            self.log.error(f"reinit_shioaji, 重新登入shioaji出現錯誤: {str(e)}")
            raise