import discord
from discord.ext import commands
from distutils.util import strtobool
import os, sys, asyncio
from dotenv import load_dotenv
load_dotenv()

class DC(commands.Bot):
    def __init__(self, queue, broker):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        self.queue = queue
        self.broker = broker
        self.isDev = bool(strtobool(os.getenv('IS_DEV', 'true')))

        super().__init__(command_prefix="/", intents=intents)
    
    async def check_queue(self):
        """持續監聽 Queue，將結果提交到 handle_all_request"""
        while True:
            type, tasks = await self.queue.get()  # 等待從隊列獲取資料
            await self.handle_all_request(tasks, type)
            self.queue.task_done()  # 標記任務完成
    
    async def start_bot(self):
        """手動啟動 bot"""
        await self.start(os.getenv("DISCORD_TOKEN"))
            
    async def shutdown_bot(self):
        await self.close()
 
    async def on_ready(self):
        print(f'We have logged in as {self.user}')

        # 動態加載所有 cogs
        await self.load_all_cogs()
        
        # 啟動監聽隊列的協程
        asyncio.create_task(self.check_queue())
 
    async def load_all_cogs(self):
        cogs_directory = os.path.join(os.path.dirname(__file__), "cogs")
        
        # 檢查 cogs 目錄是否在 sys.path 中,  遍歷 cogs 資料夾中的所有 .py 文件並加載
        if cogs_directory not in sys.path:
            sys.path.insert(0, cogs_directory)  # 將 cogs 目錄添加到 sys.path
        
        for filename in os.listdir(cogs_directory):
            if filename.endswith(".py"):
                extension = f"notify.cogs.{filename[:-3]}"  # 擷取 .py 前的名稱
                try:
                    await self.load_extension(extension)
                    print(f"Loaded extension '{extension}' successfully.")
                except Exception as e:
                    print(f"Failed to load extension '{extension}': {e}")
                    raise RuntimeError(f"Failed to load extension '{extension}': {e}")
   
    async def handle_all_request(self, tasks, type):
        tasks_to_wait = []
        
        # 根據 type 和 extra_param 選擇相應的任務
        for task in tasks:
            if self.isDev:
                task_done_event = asyncio.create_task(self.send_dev(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=0x00ff00
                ))
            
            elif type == "signal":
                task_done_event = asyncio.create_task(self.send_signal(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=0x00ff00
                ))

            elif type == "order":
                task_done_event = asyncio.create_task(self.send_order(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=task['color']
                ))
                
            elif type == "stock":
                # 如果是 future 類型，創建 send_future_order 任務
                task_done_event = asyncio.create_task(self.send_stock_order(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=task['color']
                ))
                
            elif type == "future":
                # 如果是 future 類型，創建 send_future_order 任務
                task_done_event = asyncio.create_task(self.send_future_order(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=task['color']
                ))

            elif type == "option":
                # 如果是 option 類型，創建 send_option_order 任務
                task_done_event = asyncio.create_task(self.send_option_order(
                    title=task['title'],
                    description=task['description'],
                    footer=task['footer'],
                    params=task['notify_params'],
                    color=task['color']
                ))

            tasks_to_wait.append(task_done_event)  # 將任務添加到列表中

        # 等待所有的異步任務
        if tasks_to_wait:
            await asyncio.gather(*tasks_to_wait)  # 等待所有任務完成
        
    async def send_index(self, message):
        """調用 OptionCog 中的股票下單推播方法"""
        index_cog = self.get_cog("IndexCog")  # 獲取已加載的 IndexCog 實例
        if index_cog:
            await index_cog.send_index_notification(message)
        else:
            print("IndexCog 尚未加載，無法推播訊息。")              
                    
    async def send_signal(self, title, description, footer, params, color=0x00ff00):
        """調用 SignalCog 中的股票下單推播方法"""
        signal_cog = self.get_cog("SignalCog")  # 獲取已加載的 SignalCog 實例
        if not signal_cog:
            raise RuntimeError("SignalCog 尚未加載。")

        try:
            await signal_cog.send_signal_notification(title, description, footer, params, color)
        except Exception as e:
            print(f"無法在bot中推播訊息。{e}")

    async def send_order(self, title, description, footer, params, color=0x00ff00):
        """調用 OrderCog 中的股票下單推播方法"""
        order_cog = self.get_cog("OrderCog")  # 獲取已加載的 SignalCog 實例
        if not order_cog:
            raise RuntimeError("OrderCog 尚未加載。")

        try:
            await order_cog.send_order_notification(title, description, footer, params, color)
        except Exception as e:
            print(f"無法在bot中推播訊息。{e}")
            
    async def send_stock_order(self, title, description, footer, params, color=0x00ff00):
        """調用 StockCog 中的股票下單推播方法"""
        stock_cog = self.get_cog("StockCog")  # 獲取已加載的 StockCog 實例
        if stock_cog:
            await stock_cog.send_stock_order_notification(title, description, footer, params, color)
        else:
            print("StockCog 尚未加載，無法推播訊息。")
            
    async def send_future_order(self, title, description, footer, params, color=0x00ff00):
        """調用 FutureCog 中的股票下單推播方法"""
        future_cog = self.get_cog("FutureCog")  # 獲取已加載的 FutureCog 實例
        if future_cog:
            await future_cog.send_future_order_notification(title, description, footer, params, color)
        else:
            print("FutureCog 尚未加載，無法推播訊息。")

    async def send_option_order(self, title, description, footer, params, color=0x00ff00):
        """調用 OptionCog 中的股票下單推播方法"""
        option_cog = self.get_cog("OptionCog")  # 獲取已加載的 OptionCog 實例
        if option_cog:
            await option_cog.send_option_order_notification(title, description, footer, params, color)
        else:
            print("OptionCog 尚未加載，無法推播訊息。")

    async def send_dev(self, title, description, footer, params, color=0x00ff00):
        """調用開發與測試推播"""
        dev_cog = self.get_cog("DevCog")  # 獲取已加載的 OptionCog 實例
        if dev_cog:
            await dev_cog.send_dev_notification(title, description, footer, params, color)
        else:
            print("OptionCog 尚未加載，無法推播訊息。")