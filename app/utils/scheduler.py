from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor
import pytz
from utils.log import get_module_logger
from typing import List, Dict
from utils.task import Facade

class TaskScheduler:
    def __init__(self, process_lock, timezone: str = "Asia/Taipei"):
        """
        初始化任務調度器
        """
        self.process_lock = process_lock
        self.scheduler = AsyncIOScheduler(
            executors={'default': AsyncIOExecutor()},
            job_defaults={'coalesce': False, 'max_instances': 3},
            timezone=pytz.timezone(timezone)
        )
        self.facade = Facade()
        self.task_configs = self._load_task_configs()
        self.log = get_module_logger('utils/scheduler')

    def _load_task_configs(self) -> List[Dict]:
        """
        定義任務配置（可以從配置文件或數據庫加載）
        """
        return [
            {
                "name": "calculate_coeff",
                "trigger": CronTrigger(hour=6, minute=0),
                "args": [self.process_lock]
            },
            {
                "name": "clear_redis",
                "trigger": CronTrigger(hour=7, minute=0),
                "args": [self.process_lock]
            },
            {
                "name": "reinit_shioaji",
                "trigger": CronTrigger(hour=8, minute=0),
                "args": []
            },
            {
                "name": "calculate_coeff",
                "trigger": CronTrigger(hour=14, minute=15),
                "args": [self.process_lock]
            },
            {
                "name": "clear_redis",
                "trigger": CronTrigger(hour=14, minute=30),
                "args": [self.process_lock]
            },
            {
                "name": "reinit_shioaji",
                "trigger": CronTrigger(hour=14, minute=45),
                "args": []
            }
        ]

    def register_tasks(self) -> None:
        """
        根據配置註冊所有定時任務
        """
        for config in self.task_configs:
            task_name = config["name"]
            trigger = config["trigger"]
            args = config["args"]
            self.scheduler.add_job(
                self.facade.run_task,
                trigger,
                args=[task_name] + args,
                name=task_name
            )
            self.log.info(f"註冊任務 {task_name} 與觸發器 {trigger}")

    def start(self) -> None:
        """
        啟動調度器
        """
        self.register_tasks()
        self.scheduler.start()
        self.log.info("定時任務啟動")

    def stop(self) -> None:
        """
        停止調度器
        """
        self.scheduler.shutdown()
        self.log.info("定時任務停止")