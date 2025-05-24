from broker.order.OrderBase import BaseOrderManager
from broker.broker.shioaji.status.ShioajiStatus import ShioajiStatus
import functools, queue, threading
import shioaji as sj
from datetime import datetime

class ShioajiOrderManager(BaseOrderManager):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ShioajiOrderManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, api, async_queue, log, broker):
        if not hasattr(self, '_initialized'):
            super().__init__(async_queue, log)
            self.api = api
            self.broker = 'shioaji'
            self.broker_instance = broker
            self.cb_queue = queue.Queue()
            self.start_callback_processor()

    @classmethod
    def reinit_api(cls, api):
        """從外部重新初始化 self.api"""
        try:
            instance = cls._instance  # 獲取單例
            if instance is None:
                raise ValueError("ShioajiOrderManager instance 沒有初始化")

            instance.api = api
            instance.log.info("ShioajiOrderManager - 重新設定shioaji連線")
        except Exception as e:
            raise RuntimeError(f"ShioajiOrderManager - 重新設定Shioaji失敗: {e}")

    def _handle_order(self, action, contract, account, order_params):
        try:
            """Shioaji 的下單處理邏輯"""
            self.log.info(f"準備下單商品: {order_params['symbol']}/{order_params['code']}/{order_params['strategy']}, 訂單行為: {order_params['order_action']}, 下單行為: {action}, 交易ID: {order_params['trade_id']}")
            if action == 'Cancel':
                notification = self._cancel_order(account, order_params)
            elif action == 'DynamicAdjustSell' or action == 'DynamicAdjustBuy':
                 notification = self._place_change_order(account, order_params)
            elif order_params['symbol'] == 'stock':
                notification = self._place_stock(action, contract, account, order_params)
            elif order_params['symbol'] == 'future':
                notification = self._place_future(action, contract, account, order_params)
            else:
                raise ValueError(f"Unsupported symbol for Shioaji: {order_params['symbol']}")

            notification['footer'] = self.broker
            self.queue.put(('order', [notification]))
            return True
        
        except Exception as e:
            self.log.error(f"Shioaji - _handle_order下單失敗: {e}")
            return False

    # ---------------------------- 永豐API下單 ----------------------------

    # 股票下單
    def _place_stock(self, action, contract, account, order_params):
        action_value = getattr(sj.constant.Action, action)
        order_type_value = getattr(sj.constant.OrderType, order_params['order_type']['order_type'])
        price_type_value = getattr(sj.constant.StockPriceType, order_params['order_type']['price_type'])
        order_lot_value = getattr(sj.constant.StockOrderLot, order_params['order_type']['order_lot'])
        
        order = self.api.Order(
            price=order_params['price'],
            quantity=order_params['quantity'], 
            action=action_value, 
            price_type=price_type_value, 
            order_type=order_type_value, 
            order_lot=order_lot_value,
            daytrade_short=True,
            custom_field="quant",
            account=account  # 使用正確帳戶
        )

        trade = self.api.place_order(contract, order)
        self.api.set_order_callback(functools.partial(self.order_cb, order_info=order_params))

        self.log.info(f"股票下單: {order_params['symbol']}/{order_params['code']}/{order_params['strategy']}/{order_params['trade_id']}, 相關訂單參數: {order_params}")

        # 檢查交易狀態與通知
        status = self.trade_status(trade.status.status)
        return self.call_notification(status, trade={
            'trade': trade,
            'strategy': order_params['strategy']
        })

    # 期貨下單
    def _place_future(self, action, contract, account, order_params):
        action_value = getattr(sj.constant.Action, action)
        order_type_value = getattr(sj.constant.OrderType, order_params['order_type']['order_type'])
        price_type_value = getattr(sj.constant.FuturesPriceType, order_params['order_type']['price_type'])
        oct_type_value = getattr(sj.constant.FuturesOCType, order_params['order_type']['octype'])
        
        order = self.api.Order(
            price=order_params['price'],
            quantity=order_params['quantity'], 
            action=action_value,
            price_type=price_type_value, 
            order_type=order_type_value,
            order_octypelot=oct_type_value,
            account=account  # 使用正確帳戶
        )

        trade = self.api.place_order(contract, order)
        self.api.set_order_callback(functools.partial(self.order_cb, order_info=order_params))
        
        self.log.info(f"期貨下單: {order_params['symbol']}/{order_params['code']}/{order_params['strategy']}/{order_params['trade_id']}, 相關訂單參數: {order_params}")
        
        # 檢查交易狀態與通知
        status = self.trade_status(trade.status.status)
        return self.call_notification(status, trade={
            'trade': trade,
            'strategy': order_params['strategy']
        })

    # 選擇權下單
    def _place_option(self, action, contract, account, order_params):
        pass
            
    # 取消訂單
    def _cancel_order(self, account, order_params):
        try:
            # 從 order_params 取得欲操作的 trade_id
            target_trade_id = order_params.get("trade_id")
            if not target_trade_id:
                raise ValueError("order_params 中缺少 trade_id")

            # 1. 更新狀態，查詢所有當前的 trade 物件（以股票帳戶為例）
            self.api.update_status(account)
            trades = self.api.list_trades()

            # 2. 根據 trade_id 查詢相對應的 trade 物件
            target_trade = None
            for trade in trades:
                if trade.order.id == target_trade_id:
                    target_trade = trade
                    break

            if target_trade is None:
                raise Exception(f"找不到 trade_id 為 {target_trade_id} 的訂單")

            # 3. 呼叫取消訂單 API 進行取消操作
            self.api.cancel_order(target_trade)
            # 4. 再次更新狀態以確認取消結果
            self.api.update_status(account)
            self.log.info(f"訂單 {target_trade_id} 已成功取消")

            # 5. 更新後再次取得最新的 trade 資料
            self.api.update_status(account)
            updated_trades = self.api.list_trades()
            updated_trade = None
            for trade in updated_trades:
                if trade.order.id == target_trade_id:
                    updated_trade = trade
                    break

            if updated_trade is None:
                self.log.info(f"更新後找不到 trade_id 為 {target_trade_id} 的訂單")
                return

            # 6. 根據 updated_trade 取得 contract.code
            code = updated_trade.contract.code  # 例如 "2330"

            # 7. 從 position control 中取得 Redis 資料
            redis_data = order_params['position_type'].execute('check')
            if code not in redis_data:
                self.log.info(f"Redis 中找不到 code {code} 的資料")
                return

            # 8. 取得該 code 對應的資料
            data = redis_data[code]

            # 9. 將 updated_trade.order 轉成 dict 並補充最新狀態資訊更新 Redis 中該商品資料的 order 欄位
            data["order"] = self.trade_to_dict(updated_trade)

            # 10. 將更新後的資料寫回 Redis
            # 假設 position_type 物件具有 redis 與 redis_key 屬性，此處使用 HSET 更新對應 code 的資料
            order_params['position_type'].execute('set',  **{
                'key': order_params['position_key'],
                'data': data
            })

            # 檢查交易狀態與通知
            status = self.trade_status(updated_trade.status.status)
            return self.call_notification(status, trade={
                'trade': updated_trade,
                'strategy': order_params['strategy']
            })
            
        except Exception as e:
            self.log.error(f"shioaji cancel_order Error: {e}")
            raise RuntimeError(f"shioaji cancel_order Error: {e}")
    
    # 更改價錢
    def _place_change_order(self, account, order_params):
        """
        根據傳入的參數修改價格或數量（或同時修改兩者）。
        修改成功後，會更新 Redis 中對應 contract.code 的資料，
        將最新的訂單資訊寫回 Redis。

        參數:
          - trade: 原本的 Trade 物件
          - price: (可選) 修改後的新價格
          - qty: (可選) 修改後的新數量（注意：僅允許減少委託數量）
          - order_params: 包含 position_type 的字典，position_type 提供 execute() 與 redis 相關設定
        """
        try:
            # 1. 呼叫改單 API：根據傳入的 price 與 qty 參數進行改單
            price = order_params['price']
            qty = order_params['quantity']
            
            # 從 order_params 取得欲操作的 trade_id
            target_trade_id = order_params.get("trade_id")
            if not target_trade_id:
                raise ValueError("order_params 中缺少 trade_id")
            
            # 1. 更新狀態，查詢所有當前的 trade 物件（以股票帳戶為例）
            self.api.update_status(account)
            trades = self.api.list_trades()

            # 2. 根據 trade_id 查詢相對應的 trade 物件
            target_trade = None
            for trade in trades:
                if trade.order.id == target_trade_id:
                    target_trade = trade
                    break

            if target_trade is None:
                raise Exception(f"找不到 trade_id 為  {target_trade_id} 的訂單")

            if price is None: # 僅修改數量
                self.api.update_order(trade=target_trade, qty=qty)
            elif qty is None: # 僅修改價格
                self.api.update_order(trade=target_trade, price=price)
            
            # 3. 更新狀態，取得最新的訂單狀態
            self.api.update_status(self.api.account)
            updated_trades = self.api.list_trades()

            # 4. 根據原始 trade.order.id 找出更新後的 trade 物件
            updated_trade = None
            for t in updated_trades:
                if t.order.id == trade.order.id:
                    updated_trade = t
                    break
                
            if updated_trade is None:
                raise Exception(f"更新後找不到 trade_id 為 {trade.order.id} 的訂單")

            # 5. 根據 updated_trade 取得 contract.code (例如 "2330")
            code = updated_trade.contract.code

            # 6. 取得 Redis 中目前的資料（透過 position control）
            if order_params is None or 'position_type' not in order_params:
                raise ValueError("必須傳入包含 position_type 的 order_params")
                
            redis_data = order_params['position_type'].execute('check')
            if code not in redis_data:
                self.log.info(f"Redis 中找不到 code {code} 的資料")
                return

            # 7. 取得對應的資料，並更新其中 order 部分
            data = redis_data[code]
            
            # 更新 Redis 中該商品資料的 order 欄位（此處格式為單一物件）
            data["order"] = self.trade_to_dict(updated_trade)

            # 8. 將更新後的資料寫回 Redis (假設 position_type 物件有 redis 與 redis_key 屬性)
            order_params['position_type'].execute('set',  **{
                'key': order_params['position_key'],
                'data': data
            })
            
            # 檢查交易狀態與通知
            return self.call_notification('change', trade={
                'trade': updated_trade,
                'strategy': order_params['strategy']
            })
            
        except Exception as e:
            self.log.error(f"shioaji change_order Error: {e}")
            raise RuntimeError(f"shioaji change_order Error: {e}")

    # Trade物件轉換為Dict型態
    def trade_to_dict(self, trade):
        """
        將 trade 物件轉換成 dict 格式。假設 trade 有 contract, order, status 三個屬性，
        且每個屬性都可以用 __dict__ 取得內部資訊（如果屬性本身已經是 dict 則直接傳回）。
        如果某個屬性需要特殊處理，也可在此進行轉換。
        """
        return {
            "contract": trade.contract.__dict__ if hasattr(trade.contract, '__dict__') else trade.contract,
            "order": trade.order.__dict__ if hasattr(trade.order, '__dict__') else trade.order,
            "status": trade.status.__dict__ if hasattr(trade.status, '__dict__') else trade.status
        }

    # --------------------- 訂單狀態與下單回調 ----------------------------  
      
    # 訂單狀態推播組合
    def trade_status(self, current_status):
        # 动态映射状态到 ShioajiStatus
        status_enum = ShioajiStatus.from_status(current_status)
        
        if status_enum is None:
            self.log.error(f"Unrecognized status: {current_status}")
            raise RuntimeError(f"Unrecognized status: {current_status}")
        
        return status_enum

    # 推播通知(需要客製化回覆內容, 在自己的class內部定義function, 如果不用客製, 直接使用status.notificaiton)
    def call_notification(self, status, trade=None, info=None):
        # 提取 "." 後的部分並轉小寫
        method_name = str(status).split('.')[-1].lower()

        # 動態調用對應的方法
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            if info is None:
                result = method(status, trade=trade)  # 調用該方法
            else:
                result = method(status, info=info)
        else:
            self.log.error(f"Method '{method_name}' not found in the class.")
            raise RuntimeError(f"Method '{method_name}' not found in the class.")

        return result
    
    def start_callback_processor(self):
        def process_callbacks():
            while True:
                callback_data = self.cb_queue.get()
                if not callback_data:  # 檢查是否為空
                    self.log.warning("從隊列中取出空數據，跳過處理")
                    self.cb_queue.task_done()
                    continue
                
                stat = callback_data['stat']
                msg = callback_data['msg']
                order_info = callback_data['order_info']
                
                if stat is None or msg is None or order_info is None:
                    self.log.error(f"回調數據缺少必要字段: {callback_data}")
                    self.cb_queue.task_done()
                    continue
                
                self.log.info(f"隊列取出=>成交或委託: {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}")

                # Redis 鍵和初始數據
                redis_key = f"{order_info['position_key']}"
                position_data = order_info['position_type'].execute('check') or {'position': {}}

                # 更新商品資料
                product_key = order_info['code']
                product_data = position_data.get(product_key, {'position': {}})

                # 根據回調狀態處理
                if stat in [sj.order.OrderState.StockOrder, sj.order.OrderState.FuturesOrder]:
                    self.log.info(f"委託訂單回調: {msg['order']['id']}, {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}")
                    self._process_order(order_info, msg, product_data)
                elif stat in [sj.order.OrderState.StockDeal, sj.order.OrderState.FuturesDeal]:
                    self.log.info(f"成交訂單回調: {msg['trade_id']}, {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}")
                    self._process_deal(order_info, msg, product_key, product_data)
                else:
                    self.log.error(f"不支持的訂單狀態, {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}")
                    self.cb_queue.task_done()
                    continue

                # 更新並寫回 Redis
                position_data[product_key] = product_data
                self.log.info(f"本次下單回調結束: {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}\n\n")
                
                order_info['position_type'].execute('set', **{
                    'key': redis_key,
                    'data': position_data
                })

                self.cb_queue.task_done()  # 標記任務完成

        # 啟動獨立處理線程
        threading.Thread(target=process_callbacks, daemon=True).start()
        
    # 委託與成交回報
    def order_cb(self, stat, msg, order_info):
        # 將回調數據放入隊列，不直接處理
        self.log.info(f"回調存入隊列: {order_info['symbol']}/{order_info['code']}/{order_info['strategy']}/{order_info['trade_id']}")
        self.cb_queue.put({
            'stat': stat,
            'msg': msg,
            'order_info': order_info
        })
        
        order_id = order_info['trade_id']
        
        # 判斷訂單是否成功
        success = stat in [sj.order.OrderState.StockOrder, sj.order.OrderState.FuturesOrder, sj.order.OrderState.StockDeal, sj.order.OrderState.FuturesDeal]
        with self.broker_instance.event_lock:
            self.broker_instance.order_results[order_id] = success
            if order_id in self.broker_instance.order_events:
                self.broker_instance.order_events[order_id].set()
        
        return success
    
    def _process_order(self, order_info, order_callback, product_data):
        self.log.info(f"委託ID: {order_callback['order']['id']}, 訂單資訊: {order_info}, 委託回調資訊:{order_callback}")
        product_data[f"order:{order_callback['order']['id']}"] = order_callback

        # 委託成功推播
        status = self.trade_status('Submitted')
        return self.call_notification(status, info={
            'code': order_callback['contract']['code'],
            'symbol': order_info['symbol'],
            'strategy': order_info['strategy'],
            'name': order_callback['contract'].get('name', ''),
            'type':f"{order_callback['order']['price_type']}\n{order_callback['order']['order_type']}",
            'action': order_callback['order']['action'],
            'quantity': order_callback['order']['quantity'],
            'price': order_callback['order']['price'],
            'id': order_callback['order']['id'],
            'order_ts': '',
            'place_ts': f"{datetime.fromtimestamp(order_callback['status']['exchange_ts'], self.tz).strftime('%Y-%m-%d %H:%M:%S')}",
            'no': f"{order_callback['order']['ordno']}\n{order_callback['order']['seqno']}",
            'account': f"{order_callback['order']['account']['account_type']}\n{order_callback['order']['account']['person_id']}\n{order_callback['order']['account']['account_id']}\n{order_callback['order']['account']['broker_id']}",
            'status': f"{'成功' if order_callback['operation']['op_code'] == '00' else '失敗'}"
        })

    def _process_deal(self, order_info, deal_callback, product_key, product_data):
        self.log.info(f"成交ID: {deal_callback['trade_id']}, 訂單資訊: {order_info}, 成交回調資料: {deal_callback}")
        self.log.info(f"交易行為:{deal_callback['action']}, 倉位狀況: {product_data['position']}")
        
        product_data[f"deal:{deal_callback['trade_id']}"] = deal_callback
        
        # 檢查是否為平倉操作(若是平倉要將交易結果記錄在Analyze的表中)
        if order_info['order_action'] in {'Long Close', 'Short Close', 'Short Profit', 'Long Profit', 'Long Stop Loss', 'Short Stop Loss'}:
            self.log.info(f"成交ID: {deal_callback['trade_id']}, 當前交易行為: {order_info['order_action']}, 需要紀錄交易績效")
            self._analyze(order_info, deal_callback, product_key, product_data)
            
        if order_info['order_action'] in {'Long Stop Loss', 'Short Stop Loss', 'Long Close', 'Short Close'}: 
            product_data['position'] = {'capital': product_data['position']['capital']}
            self.log.info(f"當前操作: {order_info['order_action']}, 倉位與訂單重設, 訂單相關資料: {order_info}")
        
        else: # 委託成功, 不是平倉操作, 可能是首次進場買(long), 賣(short), 則需設定倉位 => (如未來有滾倉設計, 調用AbstractPosition get_position, 滾倉後重新設定)
            profit, loss = order_info['position_type'].execute('calculate',  **{
                'action': 'long' if deal_callback['action'] == 'Buy' else 'short' if deal_callback['action'] == 'Sell' else 'unknown', 
                'current_price': deal_callback['price'],
                'code': order_info['code'],
            })
            
            product_data['position'] = {
                'symbol': order_info['symbol'],
                'position': order_info['quantity'] if deal_callback['action'] == 'Buy' else -order_info['quantity'],
                'action': deal_callback['action'],
                'profit': profit,
                'quantity': order_info['quantity'],
                'loss': loss,
                'origin': deal_callback['price'],
                'capital': order_info['capital']
            }

            self.log.info(f"成交後倉位資料: {product_data['position']}")

        # 成交推播通知
        status = self.trade_status('Filled')
        return self.call_notification(status, info={
            'symbol': order_info['symbol'],
            'code': order_info['code'],
            'name': '',
            'strategy': order_info['strategy'],
            'action': deal_callback['action'],
            'price': deal_callback['price'],
            'quantity': deal_callback['quantity'],
            'type': '',
            'order_ts': '',
            'place_ts': f"{datetime.fromtimestamp(deal_callback['ts'], self.tz).strftime('%Y-%m-%d %H:%M:%S')}",
            'id': deal_callback['trade_id'],
            'no': f"{deal_callback['ordno']}\n{deal_callback['seqno']}",
            'account': f"無\n, 無,\n {deal_callback['account_id']}\n{deal_callback['broker_id']}",
            'status': "成功" 
        })

    def _analyze(self, order_info, deal_callback, product_key, product_data):
        # 盈虧計算
        original_action = product_data['position'].get("action", 0)  # 原始操作，可能是 "Buy" 或 "Sell"
        
        # 定義交易方向變量（多單/空單/無效）
        position_type = None
        if original_action == 'Buy' and deal_callback['action'] == 'Sell':
            position_type = "long"  # 多單：先買後賣
        elif original_action == 'Sell' and deal_callback['action'] == 'Buy':
            position_type = "short"  # 空單：先賣後買
        else:
            self.log.error(f"無效的交易方向組合: 原始操作=>{original_action}, 訂單操作=>{deal_callback['action']}")
            return  # 提前退出避免後續錯誤
        
        self.log.info(f"原始交易行為: {original_action}, 後續交易行為: {deal_callback['action']}, 判定為做{position_type}交易")

        # 計算交易費用
        total_fee = 0
        entry_price = int(product_data['position'].get("origin", 0))  # 開倉價格
        exit_price = int(deal_callback['price'])  # 平倉價格
        quantity = int(deal_callback['quantity'])
        capital = int(product_data['position'].get("capital", 10000))  # 開倉價格
        
        if order_info['symbol'] == 'stock':# 股票交易的費用計算
            if position_type == "short":  # 先賣後買(做空)
                total_fee = (entry_price * order_info['commission_tax']['comm'] + entry_price * order_info['commission_tax']['tax']) + (exit_price * order_info['commission_tax']['comm'])
                profit_loss = (entry_price - exit_price) * quantity
                
            elif position_type == "long":  # 先買後賣(做多)
                total_fee = (exit_price * order_info['commission_tax']['comm'] + exit_price * order_info['commission_tax']['tax']) + (entry_price * order_info['commission_tax']['comm'])
                profit_loss = (exit_price - entry_price) * quantity

        elif order_info['symbol'] == 'future':# 期貨交易的費用計算
            total_fee = (quantity * order_info['commission_tax']['comm'] + entry_price * order_info['commission_tax']['tax'] * order_info['commission_tax']['tick_size'] * quantity) + (quantity * order_info['commission_tax']['comm'] + exit_price * order_info['commission_tax']['tax'] * order_info['commission_tax']['tick_size'] * quantity)
            if position_type == 'short':
                profit_loss = (entry_price - exit_price) * quantity * order_info['commission_tax']['tick_size']
            elif position_type == 'long':
                profit_loss = (exit_price - entry_price) * quantity * order_info['commission_tax']['tick_size']

        # 記錄交易結果
        new_captal = capital + int(profit_loss) - int(total_fee)
        trade_results = []
        append_data = {
            'symbol': order_info['symbol'],
            'code': product_key,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'profit_loss': profit_loss,
            'total_fees': int(total_fee),
            'net_profit_loss': int(profit_loss - total_fee),
            'order_action': order_info['order_action'],
            'strategy': order_info['strategy'],
            'ts': datetime.now(tz=self.tz).strftime("%Y-%m-%d %H:%M:%S"),
            'capital': new_captal,
        }

        trade_results.append(append_data)

        # 更新總資產
        product_data['position']['capital'] = new_captal

        # 更新分析紀錄
        order_info['position_type'].execute('set_analyze', **{
            'product_key': product_key,
            'redis_key': order_info['analyze_key'],
            'data': trade_results
        })

        self.log.info(f'平倉訂單相關資料: {order_info}, 平倉估算: {append_data}')

        status = self.trade_status('Close')
        return self.call_notification(status, info=append_data)

    # ---------------------------- 訂單狀態推播 ----------------------------
    def close(self, status, info=None):
        try:
            notification = status.get_notification(
                code=info['code'],
                symbol=info['symbol'],
                strategy=info['strategy'],
                time=info['ts'],
                entry=info['entry_price'],
                exit=info['exit_price'],
                pl=info['profit_loss'],
                net_pl=info['net_profit_loss'],
                total_fees=info['total_fees'],
                order_action=info['order_action']
            )
            
            notification['footer'] = self.broker
            return self.queue.put((f"{info['symbol']}", [notification]))
        except Exception as e:
            self.log.error(f"shioaji close_order Error: {e}")
            raise RuntimeError(f"shioaji close_order Error: {e}")
    
    def filled(self, status, info=None, trade=None):
        try:
            if trade and not info: # 如果是傳入完整的shioaji的trade物件(下單查詢回調, 更新)
                notification = status.get_notification(
                    code=trade.contract.code,
                    symbol=trade.contract.symbol,
                    name=trade.contract.name,
                    strategy='',
                    action=trade.order.action,
                    quantity=trade.status.deals[0].quantity,
                    price=trade.status.deals[0].price,
                    type=f'{trade.order.price_type}\n{trade.order.order_type}',
                    id=trade.order.id,
                    profit='',
                    loss='',
                    order_ts=trade.status.order_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    place_ts=f"{trade.status.place_datetime.strftime('%Y-%m-%d %H:%M:%S')}" if trade.status.deals[0].ts else "N/A",
                    no=f'{trade.order.seqno}\n{trade.order.ordno}',
                    account=f'{trade.order.account.account_type}\n{trade.order.account.person_id}\n{trade.order.account.account_id}\n{trade.order.account.broker_id}',
                    status=f"{'成功' if trade.status.status_code == '00' else '失敗'}"
                )
            
            else: # 傳入的不是trade物件(成交回調)
                notification = status.get_notification(
                    code=info['code'],
                    symbol=info['symbol'],
                    name=info['name'],
                    strategy=info['strategy'],
                    action=info['action'],
                    quantity=info['quantity'],
                    price=info['price'],
                    type=info['type'],
                    id=info['id'],
                    profit='',
                    loss='',
                    order_ts=info['order_ts'],
                    place_ts=info['place_ts'],
                    no=info['no'],
                    account=info['account'],
                    status=info['status']
                )
            
            notification['footer'] = self.broker
            return self.queue.put((f"{info['symbol']}", [notification]))
            
        except Exception as e:
            self.log.error(f"shioaji filled_order Error: {e}")
            raise RuntimeError(f"shioaji filled_order Error: {e}")
    
    def change(self, status, trade): # (更新價格或量 -> place_change_order)
        new_price = ""
        if hasattr(trade['trade'].trade.status, "modified_price"):
            # 若 modified_price 有值且不同於原本價格，則視為改價
            if trade['trade'].trade.status.modified_price and trade['trade'].trade.status.modified_price != trade['trade'].trade.order.price:
                new_price = trade['trade'].trade.status.modified_price

        # 檢查是否有數量修改
        # 若 order_quantity 存在且與原始訂單數量不同，則取其值，否則設為空字串
        new_quantity = ""
        if hasattr(trade['trade'].trade.status, "cancel_quantity"):
            if trade['trade'].trade.status.order_quantity and trade['trade'].trade.status.order_quantity != trade['trade'].trade.order.quantity:
                new_quantity = trade['trade'].trade.status.order_quantity
        
        return status.get_notification(
            code=trade['trade'].trade.contract.code,
            symbol=trade['trade'].trade.contract.symbol,
            strategy=trade['trade'].strategy,
            name=trade['trade'].trade.contract.name,
            action=trade['trade'].trade.order.action,
            quantity=trade['trade'].trade.order.quantity,
            new_quantity=new_quantity,
            price=trade['trade'].trade.order.price,
            new_price=new_price,
            type=f"{trade['trade'].trade.order.price_type}\n{trade['trade'].trade.order.order_type}",
            id=trade['trade'].trade.order.id,
            ts=trade['trade'].trade.status.order_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            no=f"{trade['trade'].trade.order.seqno}\n{trade['trade'].trade.order.ordno}",
            account=f"{trade['trade'].trade.order.account.account_type}\n{trade['trade'].trade.order.account.person_id}\n{trade['trade'].trade.order.account.account_id}\n{trade.order.account.broker_id}",
            status=f"{'成功' if trade['trade'].trade.status.status_code == '00' else '失敗'}"
        )
    
    def submitted(self, status, info=None):
        try:
            notification = status.get_notification(
                code=info['code'],
                symbol=info['symbol'],
                name=info['name'],
                strategy=info['strategy'],
                action=info['action'],
                quantity=info['quantity'],
                price=info['price'],
                type=info['type'],
                id=info['id'],
                order_ts=info['order_ts'],
                place_ts=info['place_ts'],
                no=info['no'],
                account=info['account'],
                status=info['status']
            )
            
            notification['footer'] = self.broker
            return self.queue.put(('order', [notification]))
            
        except Exception as e:
            self.log.error(f"shioaji submitted_order Error: {e}")
            raise RuntimeError(f"shioaji submitted_order Error: {e}")
    
    def cancelled(self, status, trade=None):
        try: 
            notification = status.get_notification(
                code=trade['trade'].trade.contract.code,
                symbol=trade['trade'].trade.contract.symbol,
                name=trade['trade'].trade.contract.name,
                action=trade['trade'].trade.order.action,
                quantity=trade['trade'].trade.order.quantity,
                cancel_quantity=trade['trade'].trade.status.cancel_quantity,
                price=trade['trade'].trade.order.price,
                type=f"{trade['trade'].trade.order.price_type}\n{trade['trade'].trade.order.order_type}",
                id=trade['trade'].trade.order.id,
                ts=trade['trade'].trade.status.order_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                no=f"{trade['trade'].trade.order.seqno}\n{trade['trade'].trade.order.ordno}",
                account=f"{trade['trade'].trade.order.account.account_type}\n{trade['trade'].trade.order.account.person_id}\n{trade['trade'].trade.order.account.account_id}\n{trade.order.account.broker_id}",
                status=f"{'成功' if trade['trade'].trade.status.status_code == '00' else '失敗'}"
            )
            
            notification['footer'] = self.broker
            return self.queue.put(('order', [notification]))
        except Exception as e:
            self.log.error(f"shioaji cancel_order Error: {e}")
            raise RuntimeError(f"shioaji cancel_order Error: {e}")
           
    def pending_submit(self, status, trade=None):
        try:
            return status.get_notification(
                code=trade['trade'].contract.code,
                symbol=trade['trade'].contract.symbol,
                name=trade['trade'].contract.name,
                strategy=trade['strategy'],
                action=trade['trade'].order.action,
                quantity=trade['trade'].order.quantity,
                price=trade['trade'].order.price,
                type=f"{trade['trade'].order.price_type}\n{trade['trade'].order.order_type}",
                id=trade['trade'].order.id,
                ts=trade['trade'].status.order_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                no=f"{trade['trade'].order.seqno}\n{trade['trade'].order.ordno}",
                account=f"{trade['trade'].order.account.account_type}\n{trade['trade'].order.account.person_id}\n{trade['trade'].order.account.account_id}\n{trade['trade'].order.account.broker_id}",
                status=f"{'成功' if trade['trade'].status.status_code == '00' else '失敗'}"
            )
            
        except Exception as e:
            self.log.error(f"shioaji pending_order Error: {e}")
            raise RuntimeError(f"shioaji pending_order Error: {e}")