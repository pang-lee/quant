from abc import ABC, abstractmethod

class Task(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """返回任務名稱"""
        pass

    @abstractmethod
    async def execute(self, *args, **kwargs) -> None:
        """執行任務邏輯"""
        pass