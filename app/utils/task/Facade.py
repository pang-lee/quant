from utils.task.CalculateCoeffTask import CalculateCoeffTask
from utils.task.ClearRedisTask import ClearRedisTask
from utils.log import get_module_logger

class Facade:
    def __init__(self):
        """
        初始化 Trade 門面，管理所有子任務
        """
        self.log = get_module_logger('utils/task/facade')
        self.tasks = [
            CalculateCoeffTask(),
            ClearRedisTask()
        ]

    async def run_task(self, task_name, process_lock, *args, **kwargs) -> None:
        """
        根據任務名稱執行對應的子任務
        """
        self.log.info(f"正在加載任務: {task_name}")
        for task in self.tasks:
            if task.name == task_name:
                try:
                    await task.execute(process_lock)
                    self.log.info(f"Task {task_name} 完成")
                except Exception as e:
                    self.log.error(f"task {task_name} 出錯: {str(e)}")
                    raise
                return
        self.log.warning(f"Task {task_name} 不存在")
        raise ValueError(f"Task {task_name} 不存在")