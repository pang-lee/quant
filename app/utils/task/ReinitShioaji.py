from utils.log import get_module_logger
from utils.task.Task import Task

class ReinitShioaji(Task):
    def __init__(self):
        self.log = get_module_logger('utils/task/ReinitShioaji')

    @property
    def name(self) -> str:
        return "reinit_shioaji"

    async def execute(self, **kwargs) -> None:
        try:
            shioaji_client = kwargs.get('broker')
            shioaji_datasource = kwargs.get('datasource')
            self.log.info(f"運行reinit_shioaji task, 重新登入shioaji")
            new_client = shioaji_client.logout_shioaji()
            shioaji_datasource.reinit_api(new_client)
            self.log.info(f"reinit_shioaji task 成功運行完畢\n")
        except Exception as e:
            self.log.error(f"reinit_shioaji, 重新登入shioaji出現錯誤: {str(e)}")
            raise
