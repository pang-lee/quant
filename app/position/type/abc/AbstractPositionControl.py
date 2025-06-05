from abc import ABC, abstractmethod
import redis
from redis.lock import Lock
from db.redis import get_redis_connection
import json, ast, os, time
from utils.log import get_module_logger
from dotenv import load_dotenv
load_dotenv()

class AbstractPositionControl(ABC):
    # 全局 Lua 腳本（在類級別定義）
    _LUA_SCRIPT = """
    local key = KEYS[1]
    local version = ARGV[1]
    local current_version = redis.call('HGET', key, 'version')
    if not version or tonumber(version) == nil then
        return redis.error_reply("Invalid version provided")
    end
    if current_version and tonumber(current_version) >= tonumber(version) then
        return 0
    end
    for i = 2, #ARGV, 2 do
        redis.call('HSET', key, ARGV[i], ARGV[i+1])
    end
    return 1
    """
    
    def __init__(self, take_profit, stop_loss, tick_size, symbol, redis_key):
        self.redis = get_redis_connection()
        self.cluster_host = os.getenv('REDIS_HOST')
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.tick_size = tick_size
        self.symbol = symbol
        self.redis_key = redis_key
        self.log = get_module_logger(f"position/{redis_key.replace(':', '_')}")
        self._lua_script = self.redis.register_script(self._LUA_SCRIPT)

    def get_position(self):
        lock = Lock(self.redis, f"lock:{self.redis_key}", timeout=5)
        
        try:
            with lock:
                # 從 Redis 取得指定 key 的所有哈希欄位和值
                raw_data = self.redis.hgetall(self.redis_key)

                formatted_data = {
                    k: (ast.literal_eval(v) if isinstance(v, str) else v.decode('utf-8') if isinstance(v, bytes) else 
                        float(v) if '.' in v else int(v) if v.isdigit() else v) for k, v in raw_data.items()
                }
        
                # 反向解析：將從 Redis 取出的字典中的每個值從 string 或 bytes 轉回原本的資料類型
                # 確保將字串解析成字典
                for key, value in formatted_data.items():
                    if isinstance(value, str):
                        try:
                            # 使用 ast.literal_eval 來安全地將字串解析成字典
                            formatted_data[key] = ast.literal_eval(value)
                        except (ValueError, SyntaxError):
                            # 如果解析失敗，保留原始字串
                            pass

                # 提取訂單和成交 ID
                order_ids = {k.split(':')[1] for k in formatted_data.keys() if k.startswith('order:')}
                deal_ids = {k.split(':')[1] for k in formatted_data.keys() if k.startswith('deal:')}
                # 未成交訂單
                formatted_data['pending_orders'] = order_ids - deal_ids
                # 已成交訂單
                formatted_data['completed_orders'] = order_ids & deal_ids
                # 成交先到達的訂單
                formatted_data['arrived_deals'] = deal_ids - order_ids

                return formatted_data
        
        except Exception as e:
            self.log.error(f"獲取倉位資料失敗, key: {self.redis_key}, 錯誤: {e}")
            return {}
    
    def set_position(self, **params):
        key, data = params.get('key'), params.get('data')
        
        # 定義不應存入 Redis 移除不需要的鍵
        exclude_keys = {'pending_orders', 'completed_orders', 'arrived_deals', 'update_position', 'clear_position'}
        clean_data = {k: v for k, v in data.items() if k not in exclude_keys}
        
        # 確保字典中的值被轉換為 Redis 支援的類型（例如 string 或 bytes）
        formatted_data = {k: str(v) if not isinstance(v, (str, bytes)) else v for k, v in clean_data.items()}
        lock = Lock(self.redis, f"lock:{self.redis_key}", timeout=5)
    
        if self.cluster_host in ['redis', '127.0.0.1']:
            # 使用事務與樂觀鎖
            while True:
                try:
                    with self.redis.pipeline() as pipe:
                        # 監控指定的 key
                        pipe.watch(key)
                        # 開始事務
                        pipe.multi()
                        # 執行 HSET 操作
                        pipe.hset(key, mapping=formatted_data)
                        # 提交事務
                        pipe.execute()
                        # 如果成功，退出循環
                        break
                except redis.WatchError:
                    # 如果 key 在事務執行前被其他客戶端修改，捕獲 WatchError 並重試
                    self.log.warning(f"Redis {key} 進行設置倉位時, 已被其他客戶端修改, 即將重試")
                    continue
        
        elif self.cluster_host == 'redis-node-1':
            try:
                with lock:
                    # 添加版本號
                    version = str(time.time())
                    formatted_data['version'] = version

                    # 準備 Lua 腳本參數
                    args = [version] + [item for pair in formatted_data.items() for item in pair]

                    # 執行 Lua 腳本
                    result = self._lua_script(keys=[key], args=args)

                    if result == 1:
                        self.log.info(f"Redis {key} 設置倉位成功，版本: {formatted_data['version']}")
                        return True
                    else:
                        self.log.warning(f"Redis {key} 設置倉位失敗，版本衝突")
                        return False
            except redis.RedisError as e:
                self.log.error(f"Redis 設置倉位失敗，key: {key}, 錯誤: {e}")
                return False
            
        return True  # 返回成功標誌（可根據需求調整返回值）
    
    def get_analyze(self, **params):
        raw_data = self.redis.hgetall(params.get('key'))
        return {field: json.loads(value) for field, value in raw_data.items()}
    
    def set_analyze(self, **params):
        product_key, redis_key, trade_results = params.get('product_key'), params.get('redis_key'), params.get('data', [])

        # 更新分析資料
        analyze_data = self.get_analyze(**{'key': redis_key}) or {}

        # 如果分析資料中已經有對應的商品結果，則將新結果附加到現有的列表中
        if product_key in analyze_data:
            existing_results = analyze_data[product_key]
            if isinstance(existing_results, list):
                existing_results.append(trade_results[0])  # 添加新交易結果
            else:
                analyze_data[product_key] = [existing_results, trade_results[0]]  # 如果之前不是列表，則轉為列表後再添加
        else:
            analyze_data[product_key] = trade_results  # 新的商品，直接設置為交易結果列表
        
        return self.save_analyze(**{'key': redis_key, 'data': analyze_data})
    
    def save_analyze(self, **params):
        key, data = params.get('key'), params.get('data')
    
        if self.cluster_host in ['redis', '127.0.0.1']:
            # 使用事務與樂觀鎖
            while True:
                try:
                    with self.redis.pipeline() as pipe:
                        # 監控指定的 key
                        pipe.watch(key)
                        # 開始事務
                        pipe.multi()
                        # 遍歷 data 字典，將每個鍵值對存入 Redis 哈希表
                        for field, value in data.items():
                            # 將值序列化為 JSON 字符串
                            serialized_value = json.dumps(value, ensure_ascii=False)
                            # 使用 hset 命令將字段和值存入 Redis 哈希表
                            pipe.hset(key, field, serialized_value)
                        # 提交事務
                        pipe.execute()
                        # 如果成功，退出循環
                        break
                except redis.WatchError:
                    # 如果 key 在事務執行前被其他客戶端修改，捕獲 WatchError 並重試
                    self.log.warning(f"Redis {key} 進行設置分析結果時, 已被其他客戶端修改, 即將重試")
                    continue

        elif self.cluster_host == 'redis-node-1':
            try:
                # 添加版本號
                version = str(time.time())
                data_with_version = data.copy()
                data_with_version['version'] = version
            
                # 準備數據：JSON 序列化
                args = [version]
                for field, value in data_with_version.items():
                    if field == 'version':
                        serialized_value = value  # 直接使用純字符串
                    else:
                        serialized_value = json.dumps(value, ensure_ascii=False)
                    args.extend([field, serialized_value])
            
                # 執行 Lua 腳本
                result = self._lua_script(keys=[key], args=args)

                if result == 1:
                    self.log.info(f"Redis {key} 設置分析結果成功，版本: {version}")
                    return True
                else:
                    self.log.warning(f"Redis {key} 設置分析結果失敗，版本衝突")
                    return False
            except redis.RedisError as e:
                self.log.error(f"Redis 設置分析結果失敗，key: {key}, 錯誤: {e}")
                return False
            
        return True
    
    def determine_plt(self, **params):
        code = params.get('code')
        p_l = params.get('p_l')
        
        if p_l == 'profit':
            # 判斷take_profit是否有交易多個商品, 如果多商品會是dict格式 => {代號1: 止盈1, 代號2, 止盈2}
            if isinstance(self.take_profit, dict):
                if code is None:
                    raise ValueError("當 take_profit 為字典時，必須提供 code 參數")
                if code not in self.take_profit:
                    raise ValueError(f"code {code} 不存在於 take_profit 字典中")
                point_value = self.take_profit[code]
                
            else: # 如果只有交易一個商品則直接回傳self.params['take_profit']
                point_value = self.take_profit
        
        elif p_l == 'loss':
            # 判斷stop_loss是否有交易多個商品, 如果多商品會是dict格式 => {代號1: 止損1, 代號2, 止損2}
            if isinstance(self.stop_loss, dict):
                if code is None:
                    raise ValueError("當 stop_loss 為字典時，必須提供 code 參數")
                if code not in self.stop_loss:
                    raise ValueError(f"code {code} 不存在於 stop_loss 字典中")
                point_value = self.stop_loss[code]
                
            else: # 如果只有交易一個商品則直接回傳self.params['stop_loss']
                point_value = self.stop_loss
        
        # 如果傳遞的tick_size是dict, 那麼會有多種資訊
        if isinstance(self.tick_size, dict):
            if code is None:
                raise ValueError("當 tick_size 為字典時，必須提供 code 參數")
            if code not in self.tick_size:
                raise ValueError(f"code {code} 不存在於 tick_size 字典中")
            tick_size = self.tick_size[code]
            
        else: # 如果只有交易一個商品則直接回傳self.params['tick_size']
            tick_size = self.tick_size
            
        return point_value, tick_size
    
    def calculate(self, **params):
        """
        計算單一價格的止盈與止損:
        - 如果有交易多筆, 傳遞code, 可以從code來獲得止盈, 止損, tick_size
        - 如果code沒傳遞則代表當前交易一筆(故self.take_proft, self.stop_loss, self.tick_size都會是單個數值)
        """
        action = params.get('action')
        current_price = params.get('current_price')
        code = params.get('code', None)
        
        if action == 'long':
            take_profit = self.calculate_take_profit(current_price, 'long', code)
            stop_loss = self.calculate_stop_loss(current_price, 'long', code)
        elif action == 'short':
            take_profit = self.calculate_take_profit(current_price, 'short', code)
            stop_loss = self.calculate_stop_loss(current_price, 'short', code)
        else:
            raise ValueError("未知的交易行為，請傳入 'long' 或 'short'")
        return take_profit, stop_loss
        
    def calculate_take_profit(self, current_price, position_type, code):
        """
        根據商品類型與倉位類型計算止盈:
        take_profit傳遞會有以下情況:
            1. self.take_profit => 交易單商品, 也就是單商品的止盈
            
            2.{
                'TMFR': self.params['take_profit1'],
                'MXFR': self.params['take_profit2']
            }
            
        tick_size傳遞會有多種情況如下:
            1.{
                'TMFR': {
                    'tick_size': self.params['tick_size1'],
                    'leverage': self.params['leverage1'],
                    'symbol': 'ETF'
                },
                'MXFR': {
                    'tick_size': self.params['tick_size2'],
                    'leverage': self.params['leverage2'],
                    'symbol': 'ETF' 
                }
                ...
            }
            
            2.{
                'TMFR': self.params['tick_size1'],
                'MXFR': self.params['tick_size2']
            }
            
            3. self.params['tick_size'] => (單獨某商品的tick)
        """
        if self.take_profit == 0:
            return 0

        tick_symbol = 'index' # 默認交易商品為指數index
        take_profit_value, tick_size = self.determine_plt(code=code, p_l='profit')
        
        if isinstance(tick_size, dict): # 情况1：包含多属性的嵌套字典
            if 'tick_size' in tick_size  and 'symbol' in tick_size:
                tick_symbol = tick_size['symbol']
                tick = tick_size['tick_size']
      
        else: # 情况2：直接的数值
            tick = tick_size
        
        if self.symbol == 'stock': # 交易商品為股票, 故沒有槓桿, 直接用tick算
            if position_type == 'long':
                return round((current_price * (1 + take_profit_value)) / tick) * tick
            else:  # short
                return round((current_price * (1 - take_profit_value)) / tick) * tick

        elif self.symbol == 'future':
            if tick_symbol == 'stock': # 交易的商品為股票期貨, 或者配對交易的另一邊為現貨個股
                if position_type == 'long':
                    return round((current_price * (1 + take_profit_value)) / tick) * tick
                else:  # short
                    return round((current_price * (1 - take_profit_value)) / tick) * tick
                
            else: # 交易的商品為指數期貨, 不需要tick_size
                if position_type == 'long':
                    return int(current_price) + int(take_profit_value)
                else:  # short
                    return int(current_price) - int(take_profit_value)

        else:
            raise ValueError("止盈計算不支持的商品類型")

    def calculate_stop_loss(self, current_price, position_type, code):
        """
        根據商品類型與倉位類型計算止損
        stop_loss傳遞會有以下情況:
            1. self.stop_loss => 交易單商品, 也就是單商品的止盈
            
            2.{
                'TMFR': self.params['stop_loss1'],
                'MXFR': self.params['stop_loss2']
            }
            
        如果tick_size傳遞是dict, 那麼會有多種情況如下:
            1.{
                'TMFR': {
                    'tick_size': self.params['tick_size1'],
                    'leverage': self.params['leverage1'],
                    'symbol': 'ETF'  # 使用 self.symbol 填充
                },
                'MXFR': {
                    'tick_size': self.params['tick_size2'],
                    'leverage': self.params['leverage2'],
                    'symbol': 'ETF'  # 使用 self.symbol 填充
                }
                ...
            }
            
            2.{
                'TMFR': self.params['tick_size1'],
                'MXFR': self.params['tick_size2']
            }
            
            3. self.params['tick_size'] => (單獨某商品的tick)
        """
        if self.stop_loss == 0:
            return 0
        
        tick_symbol = 'index' # 默認交易商品為指數index
        stop_loss_value, tick_size = self.determine_plt(code=code, p_l='loss')
        
        if isinstance(tick_size, dict): # 情况1：包含多属性的嵌套字典
            if 'tick_size' in tick_size  and 'symbol' in tick_size:
                tick_symbol = tick_size['symbol']
                tick = tick_size['tick_size']
      
        else: # 情况2：直接的数值
            tick = tick_size
        
        if self.symbol == 'stock':
            if position_type == 'long':
                return round((current_price * (1 - stop_loss_value)) / tick) * tick
            else:  # short
                return round((current_price * (1 + stop_loss_value)) / tick) * tick
            
        elif self.symbol == 'future':
            if tick_symbol == 'stock': # 交易的商品為股票期貨, 或者配對交易的另一邊為現貨個股
                if position_type == 'long':
                    return round((current_price * (1 - stop_loss_value)) / tick) * tick
                else:  # short
                    return round((current_price * (1 + stop_loss_value)) / tick) * tick
            
            else: # 交易的商品為指數期貨, 不需要tick_size
                if position_type == 'long':
                    return int(current_price) - int(stop_loss_value)
                else:  # short
                    return int(current_price) + int(stop_loss_value)
            
        else:
            raise ValueError("止損計算不支持的商品類型")
    
    def check_action(self, type, **params):
        """執行艙位控制行為"""
        if type == 'check':
            return self.get_position() or False
        elif type == 'set':
            return self.set_position(**params)
        elif type == 'calculate':
            return self.calculate(**params)
        elif type == 'set_analyze':
            return self.set_analyze(**params)

        else:
            raise ValueError(f"未知倉位行為: {type}")
    
    @abstractmethod
    def execute(self):
        """執行倉位控制"""
        pass