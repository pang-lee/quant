import multiprocessing, threading, asyncio
from notify import DC
import concurrent.futures
from main import process_item, run_data_sources
from utils.file import open_json_file
from broker.load import load_brokers
from utils.scheduler import TaskScheduler
from utils.log import start_queue_listener, stop_all_listeners

# 同時運行 Discord 客戶端和主函數
async def run_all():
    try:
        queue = asyncio.Queue()
        broker = load_brokers(queue, open_json_file()['items'])
        bot = DC(queue, broker)
        asyncio.create_task(bot.start_bot())

        main_logger, _ = start_queue_listener('main', multiprocessing.Queue())
        process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=2)  # 進程池
        thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)  # 線程池
        order_status, pending_task = multiprocessing.Manager().dict(), multiprocessing.Manager().dict()
        process_lock, async_lock  = multiprocessing.Manager().Lock(), asyncio.Lock()
        
        broker_lock =  {
            broker_name: threading.Lock()  # 每个券商对应一个线程锁
            for broker_name, _ in broker.items()
        }
        
        strategy_lock = {
            f"{key}:{item['strategy']}": threading.Lock()
            for key, item_list in {k: v for k, v in open_json_file()['items'].items() if v}.items()
            for item in item_list
            if item.get('strategy')
        }

        scheduler = TaskScheduler(process_lock)
        scheduler.start()
        
        while True:
            with process_lock:
                items = {k: v for k, v in open_json_file()['items'].items() if v}

            async with async_lock: # 使用鎖來確保 process_item 只有一個實例在執行
                await process_item(
                    items, queue, process_pool, thread_pool,
                    broker, process_lock, broker_lock,
                    order_status, strategy_lock, pending_task, main_logger
                )

            await asyncio.sleep(1) # 有上鎖故可以調快秒速增加運算次數

    finally:
        await bot.shutdown_bot()
        scheduler.stop()
        process_pool.shutdown(wait=True)
        thread_pool.shutdown(wait=True)
        stop_all_listeners()

if __name__ == "__main__":
    try:
        # 運行數據源獲取
        run_data_sources(open_json_file()['items'])

        while True:
            pass

        # 運行所有任務
        # asyncio.run(run_all())

    except KeyboardInterrupt:
        print("程序已被中断，正在退出...")
    finally:
        print("程序退出")