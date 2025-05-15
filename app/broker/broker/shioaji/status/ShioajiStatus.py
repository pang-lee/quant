from enum import Enum

class ShioajiStatus(Enum):    
    PENDING_SUBMIT = {
        'title': '下單通知',
        'description': "{code}等待傳送中",
        'color': 0xFA8072,  # 浅珊瑚色(等待傳送)
        'notify_params': {
            '代號': '{code}',
            '下單標的': '{symbol}',
            '標的名稱': '{name}',
            '交易策略': '{strategy}',
            '下單價格': '{price}',
            '操作行為': '{action}',
            '下單數量': '{quantity}',
            '下單類型': '{type}',
            '訂單ID': '{id}',
            '下單時間': '{ts}',
            '訂單序號\n訂單流水號': '{no}',
            '帳號類型\n個人ID\n帳號ID\n卷商ID': '{account}',
            '訂單狀態': '{status}'
        }
    }
    
    PRE_SUBMITTED = {
        'title': '下單通知',
        'description': "{code}預約單",
        'color': 0xFFA500,  # 橙色預約單
        'notify_params': {
            '預約單掛出': '100'
        }
    }
    
    SUBMITTED = {
        'title': '下單通知',
        'description': "{code}委託成功",
        'color': 0x00FF00,  # 綠色進場成功
        'notify_params': {
            '代號': '{code}',
            '下單標的': '{symbol}',
            '標的名稱': '{name}',
            '交易策略': '{strategy}',
            '下單價格': '{price}',
            '操作行為': '{action}',
            '下單數量': '{quantity}',
            '下單類型': '{type}',
            '訂單ID': '{id}',
            '訂單時間': '{order_ts}',
            "成交時間": '{place_ts}',
            '訂單序號\n訂單流水號': '{no}',
            '帳號類型\n個人ID\n帳號ID\n卷商ID': '{account}',
            '訂單狀態': '{status}'
        }
    }
    
    FAILED = {
        'title': '下單通知',
        'description': "{code}下單失敗",
        'footer': "{code}",
        'color': 0xFF0000,  # 紅色下單失敗
        'notify_params': {
            '下單失敗': '100'
        }
    }
    
    CANCELLED = {
        'title': '下單通知',
        'description': "{code}已取消(刪除)",
        'color': 0x808080,  # 灰色已取消
        'notify_params': {
            '代號': '{code}',
            '取消標的': '{symbol}',
            '標的名稱': '{name}',
            '交易策略': '{strategy}',
            '下單價格': '{price}',
            '操作行為': '{action}',
            '下單數量': '{quantity}',
            '取消數量': '{cancel_quantity}',
            '下單類型': '{type}',
            '訂單ID': '{id}',
            '下單時間': '{ts}',
            '訂單序號\n訂單流水號': '{no}',
            '帳號類型\n個人ID\n帳號ID\n卷商ID': '{account}',
            '訂單狀態': '{status}'
        }
    }
    
    FILLED = {
        'title': '下單通知',
        'description': "{code}完全成交",
        'color': 0x0000FF,  # 藍色完全成交
        'notify_params': {
            '代號': '{code}',
            '下單標的': '{symbol}',
            '標的名稱': '{name}',
            '交易策略': '{strategy}',
            '下單價格': '{price}',
            '操作行為': '{action}',
            '下單數量': '{quantity}',
            '下單類型': '{type}',
            '止盈': '{profit}',
            '止損': '{loss}',
            '訂單ID': '{id}',
            '下單時間': '{order_ts}',
            '成交時間': '{place_ts}',
            '訂單序號\n訂單流水號': '{no}',
            '帳號類型\n個人ID\n帳號ID\n卷商ID': '{account}',
            '訂單狀態': '{status}'
        }
    }
    
    FILLING = {
        'title': '下單通知',
        'description': "{code}部分成交",
        'color': 0x800080,  # 紫色部分成交
        'notify_params': {
            '部分成交': '100'
        }
    }
    
    CLOSE = {
        'title': '平倉通知',
        'description': "{code}平倉",
        'color': 0xC8A2C8,  # 紫色部分成交
        'notify_params': {
            '代號': '{code}',
            '下單標的': '{symbol}',
            '交易策略': '{strategy}',
            '操作行為': '{order_action}',
            '時間': '{time}',
            '進場': '{entry}',
            '出場': '{exit}',
            '盈虧': '{pl}',
            '淨盈虧': '{net_pl}',
            '總手續費': '{total_fees}'
        }
    }
    
    CHANGE = {
        'title': '下單通知',
        'description': "{code}價位數量更改",
        'color': 0xFFBF00,  # 琥珀色(改價量)
        'notify_params': {
            '代號': '{code}',
            '下單標的': '{symbol}',
            '標的名稱': '{name}',
            '交易策略': '{strategy}',
            '操作行為': '{action}',
            '下單價格': '{price}',
            '新下單價格': '{new_price}',
            '下單數量': '{quantity}',
            '新下單數量': '{new_quantity}',
            '下單類型': '{type}',
            '訂單ID': '{id}',
            '下單時間': '{ts}',
            '訂單序號\n訂單流水號': '{no}',
            '帳號類型\n個人ID\n帳號ID\n卷商ID': '{account}',
            '訂單狀態': '{status}'
        }
    }
    
    @classmethod
    def from_status(cls, status):
        """根据 trade.status.status 返回对应的 ShioajiStatus 枚举"""
        status_mapping = {
            "PendingSubmit": cls.PENDING_SUBMIT,
            "PreSubmitted": cls.PRE_SUBMITTED,
            "Submitted": cls.SUBMITTED,
            "Filled": cls.FILLED,
            "Filling": cls.FILLING,
            "Failed": cls.FAILED,
            "Cancelled": cls.CANCELLED,
            "Close": cls.CLOSE,
            "Change": cls.CHANGE
        }
        
        if hasattr(status, 'value'):
            status_str = status.value
        elif isinstance(status, str):
            status_str = status
        else:
            raise ValueError("Unsupported type for status")
    
        return status_mapping.get(status_str, None)
    
    def get_notification(self, **kwargs):
        """根據給定的參數格式化通知內容"""
        # 複製當前狀態的模板
        notification = self.value.copy()
        
        # 格式化 description 和 footer 中的佔位符
        notification['description'] = notification['description'].format(**kwargs)
        
        # 格式化 notify_params 中的佔位符
        notification['notify_params'] = {
            key: str(value).format(**kwargs) for key, value in notification['notify_params'].items()
        }
        
        return notification