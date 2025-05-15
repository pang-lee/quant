from logging.handlers import TimedRotatingFileHandler, QueueHandler, QueueListener
import gzip, os, logging, shutil
from datetime import datetime
import pytz

_logger_cache = {}
_listener_cache = {}

def get_module_logger(module_path, log_queue=None):
    if module_path in _logger_cache:
        return _logger_cache[module_path]
    
    logger = logging.getLogger(module_path)
    logger.setLevel(logging.DEBUG)
    tz = pytz.timezone('Asia/Taipei')  # 設定時區
    logger.handlers.clear()
    
    if log_queue is not None:
        # 多進程模式：使用 QueueHandler
        handler = QueueHandler(log_queue)
    else:
        log_dir = os.path.join(os.getcwd(), 'log', module_path)
        os.makedirs(log_dir, exist_ok=True)
        
        # 获取当前日期字符串
        date_str = datetime.now(tz=tz).strftime("%Y-%m-%d")
        log_filename = os.path.join(log_dir, f'{module_path.split("/")[-1]}.log.{date_str}')
        
        handler = TimedRotatingFileHandler(
            log_filename,
            when='midnight',
            interval=5,
            encoding='utf-8'
        )
        
        # 修改 namer，使得旋转后的文件名格式为 "apple.YYYY-MM-DD.log"
        def namer(default_name):
            base, ext = os.path.splitext(default_name)
            date_suffix = datetime.now(tz=tz).strftime("%Y-%m-%d")
            return f"{base}.{date_suffix}{ext}"
        
        def rotator(source, dest):
            # 提取轮转日期（例如 apple.log.2024-03-01 → 2024-03-01）
            base_name = os.path.basename(source)
            date_str = base_name.split('.')[-1]
            try:
                rotation_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError as e:
                logger.error(f"解析日志日期失败: {base_name}, 错误: {e}")
                return
            
            # 构建目标目录（如 /log/strategy/apple/old/2024/03）
            log_dir = os.path.dirname(source)
            old_dir = os.path.join(
                log_dir,
                "old",
                rotation_date.strftime("%Y"),
                rotation_date.strftime("%m")
            )
            os.makedirs(old_dir, exist_ok=True)

            # 压缩并移动文件
            compressed_name = f"{base_name}.gz"
            compressed_dest = os.path.join(old_dir, compressed_name)
            with open(source, 'rb') as f_in, gzip.open(compressed_dest, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            
        handler.rotator = rotator
        handler.namer = namer
        
        # 使用自訂 formatter，並加入 PID 與線程 ID (TID)
        formatter = logging.Formatter(
            '%(asctime)s - PID: %(process)d - TID: %(thread)d - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        formatter.converter = lambda *args: datetime.now(tz).timetuple()
        handler.setFormatter(formatter)
        
    logger.addHandler(handler)
    _logger_cache[module_path] = logger
    return logger

def start_queue_listener(module_path, log_queue=None):
    """
    為特定模組啟動 QueueListener，如果未提供 log_queue，則創建一個新的。
    返回 logger 和 listener。
    """
    if log_queue is None:
        import multiprocessing
        log_queue = multiprocessing.Queue()  # 為模組創建獨立的 Queue
    
    # 獲取 logger
    logger = get_module_logger(module_path, log_queue)
    
    # 如果該模組已有 listener，直接返回
    if module_path in _listener_cache:
        return logger, _listener_cache[module_path]
    
    # 為特定模組創建 TimedRotatingFileHandler
    log_dir = os.path.join(os.getcwd(), 'log', module_path)
    os.makedirs(log_dir, exist_ok=True)
    
    tz = pytz.timezone('Asia/Taipei')
    date_str = datetime.now(tz=tz).strftime("%Y-%m-%d")
    log_filename = os.path.join(log_dir, f'{module_path.split("/")[-1]}.log.{date_str}')
    
    handler = TimedRotatingFileHandler(
        log_filename,
        when='midnight',
        interval=5,
        encoding='utf-8'
    )
    
    def namer(default_name):
        base, ext = os.path.splitext(default_name)
        date_suffix = datetime.now(tz=tz).strftime("%Y-%m-%d")
        return f"{base}.{date_suffix}{ext}"
    
    def rotator(source, dest):
        base_name = os.path.basename(source)
        date_str = base_name.split('.')[-1]
        try:
            rotation_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            logger.error(f"解析日志日期失败: {base_name}, 错误: {e}")
            return
        
        old_dir = os.path.join(
            log_dir,
            "old",
            rotation_date.strftime("%Y"),
            rotation_date.strftime("%m")
        )
        os.makedirs(old_dir, exist_ok=True)
        
        compressed_name = f"{base_name}.gz"
        compressed_dest = os.path.join(old_dir, compressed_name)
        with open(source, 'rb') as f_in, gzip.open(compressed_dest, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    handler.rotator = rotator
    handler.namer = namer
    
    formatter = logging.Formatter(
        '%(asctime)s - PID: %(process)d - TID: %(thread)d - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    formatter.converter = lambda *args: datetime.now(tz).timetuple()
    handler.setFormatter(formatter)
    
    # 啟動 QueueListener
    listener = QueueListener(log_queue, handler)
    listener.start()
    _listener_cache[module_path] = listener
    
    return logger, listener

def stop_all_listeners():
    """停止所有已啟動的 QueueListener"""
    for module_path, listener in _listener_cache.items():
        listener.stop()
    _listener_cache.clear()