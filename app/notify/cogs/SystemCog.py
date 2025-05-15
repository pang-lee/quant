from discord.ext import commands
from discord import Embed
import os, pytz, json, re
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

class SystemCog(commands.Cog):
    def __init__(self, bot, channel_id: int, timezone="Asia/Taipei"):
        self.bot = bot
        self.channel_id = channel_id
        self.timezone = timezone
        self.setpath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'setting.json'))

    @commands.command(name="syscmd")
    async def check_command(self, ctx):
        channel = self.bot.get_channel(self.channel_id)
        
        if channel:
            return await channel.send(embed=self.create_msg_embed(
                title="設定指令操作集",
                description="DC系統指令",
                footer="DC指令",
                color=0xD3D3D3,
                params={
                    "查看當前所有商品交易設定": "/system",
                    "新增交易標的(可多筆)": "/system add stock (3550, 2330...)",
                    "刪除交易標的(可多筆)": "/system del stock (3550, 2330...)",
                    "刪除指定類型全部交易標的": "/system delall stock",
                    "修改全局參數": "/system modify params (loss:20, profit:10, dynamic:true)",
                    "修改交易商品策略參數": "/system modify stock 2330 calculation (price_vol, bid_ask...)",
                    "修改交易商品交易參數": "/system modify stock 2330 params (loss:20, profit:10...)",
                    "查看交易商品集合": "/system check list stock",
                    "查看交易商品參數": "/system check stock (2330, 2315...)",
                    "查看有哪些策略可使用": "/system check strategy",
                    "查看參數設定名稱意義": "/system check params",
                    "查看當前所有交易商品": "/system check quick"
                }
            ))
        else:
            return await ctx.send("/syscmd 無法找到指定的頻道。")

    @commands.command(name="system")
    async def check_setting(self, ctx, *args):
        channel = self.bot.get_channel(self.channel_id)
        # 讀取設定
        settings = self.read_system_settings()
        
        if not args: # 沒有參數時，顯示當前設定
            if channel:
                await channel.send(embed=self.create_param_embed(
                    title="當前交易設定",
                    description="參數",
                    footer="交易參數",
                    color=0xff7f00,
                    params=settings['params']
                ))
                
                # 過濾出非空陣列並逐一生成嵌入消息
                for key, value in settings['items'].items():
                    if value:  # 檢查陣列是否有元素
                        for item in value:
                            code = item['code']

                            # 判斷 params 是否是 $ref，若是則使用 settings['params']
                            if "$ref" in item['params']:
                                params = settings['params']
                            else:
                                params = item['params']
                            
                            # 發送嵌入消息
                            await channel.send(embed=self.create_param_embed(
                                code=code,
                                title=f"交易類型: {key}",
                                description=f" {code}參數",
                                footer="交易參數",
                                params=params,
                                calculation=item['calculation'],
                                color=0xff7f00
                            ))
                return
            else:
                return await ctx.send("system 無法找到指定的頻道。")
        else: # 依照指令
            if args[0] == "add":
                # 把第三個參數（括號部分）整合成一個完整字符串
                params = " ".join(args[2:])
                # 使用正則表達式提取括號內的數值
                match = re.match(r"\(([\d,\s]+)\)", params)
                if match:
                    try:
                        # 分解出多個股票代碼，並去除空格
                        items = [s.strip() for s in match.group(1).split(",")]
                        # 將每個股票代碼逐一添加
                        for item in items:
                            result = self.add_items((args[1], item), settings)
                            if result is None: return await ctx.send(f"新增資料失敗, 請檢查")
                            
                            # 判斷 params 是否是 $ref，若是則使用 settings['params']
                            if "$ref" in result['params']:
                                params = settings['params']
                            else:
                                params = result['params']
                            
                            await ctx.send(embed=self.create_param_embed(
                                code=item,
                                title=f"交易類型: {args[1]}",
                                description=f" {item}參數",
                                footer="交易參數",
                                params=params,
                                calculation=result['calculation'],
                                color=0xff7f00
                            ))
                    except:
                        return await ctx.send(f"參數: {params}格式錯誤, 應為 (3550, 2330...)")
                else:
                    return await ctx.send("請提供有效的格式，例如 /system add stock (3550, 2330...)")
            
            elif args[0] == "del" or args[0] == "delall":
                if args[0] == "del":
                    # 把第三個參數（括號部分）整合成一個完整字符串
                    params = " ".join(args[2:])
                    # 使用正則表達式提取括號內的數值
                    match = re.match(r"\(([\d,\s]+)\)", params)
                    if match:
                        try:
                            # 分解出多個股票代碼，並去除空格
                            items = [s.strip() for s in match.group(1).split(",")]
                            # 將每個股票代碼逐一添加
                            for item in items:
                                self.remove_items((args[1], item), settings)
                            
                            await ctx.send(f"已成功批量刪除項目: {', '.join(items)}")
                        except:
                            return await ctx.send(f"參數: {params}格式錯誤, 應為 (3550, 2330...)")
                    else:
                        return await ctx.send("請提供有效的格式，例如 /system del stock (3550, 2330...)")
                
                # 全部刪除
                elif args[0] == "delall":
                    if args[1]:
                        settings["items"][args[1]] = []
                        self.write_system_settings(settings)
                        return await ctx.send(f"已將 {args[1]} 清空")
                    else:
                        return await ctx.send("請提供有效的格式，例如 /system delall stock")
                
            elif args[0] == "modify":
                if args[1] == "params": # 修改全局參數設定
                    # 把括號部分整合成一個完整字符串
                    params = " ".join(args[2:])
                    # 使用正則表達式提取括號內的鍵值對
                    match = re.match(r"\(([\w\s:,\d]+)\)", params)
                    if match:
                        try:
                            # 將鍵值對解析成字典
                            kv_pairs = [kv.strip() for kv in match.group(1).split(",")]
                            param_dict = {}
                            for kv in kv_pairs:
                                key, value = kv.split(":")
                                key = key.strip()
                                value = value.strip()

                                # 判斷值的類型：整數、布爾值或字符串
                                if value.isdigit():
                                    param_dict[key] = int(value)
                                elif value.lower() == "true":
                                    param_dict[key] = True
                                elif value.lower() == "false":
                                    param_dict[key] = False
                                else:
                                    param_dict[key] = value  # 保持為字符串

                            # 更新 params 設定
                            new_global_params = self.modify_params(param_dict, settings)
                            if new_global_params is None: return await ctx.send("修改全局參數失敗, 請檢查輸入的參數是否正確")
                            
                            await channel.send(embed=self.create_param_embed(
                                title="全局參數修改",
                                description="參數",
                                footer="交易參數",
                                color=0xff7f00,
                                params=new_global_params
                            ))
                        except:
                            return await ctx.send(f"參數: {params}格式錯誤, 應為 (loss:20, profit:10...)")
                    else:
                        return await ctx.send("請提供有效的格式，例如 /system modify params (loss:20, profit:10, dynamic:true)")

                elif args[1] in settings["items"]: # 修改個別交易項目參數(calculation, params)
                    if args[3] == 'calculation': # 修改個別交易項目 calculation 參數
                        params = " ".join(args[4:])
                        # 使用正則表達式提取括號內的數值
                        match = re.match(r"\(([\w\s,]+)\)", params)  # 可以是字母、數字和逗號
                        if match:
                            try:
                                # 分解出多個項目，並去除空格
                                items = [s.strip() for s in match.group(1).split(",")]
                                # 執行移除動作（或其他相應的邏輯）
                                for item in items:
                                    result = self.modify_item_calculation((args[1], args[2], item), settings)
                                    if result is None: return await ctx.send("修改 calculation 參數失敗, 請檢查參數或商品代號是否正確")
                                return await ctx.send(f"已成功處理 {args[1]} {args[2]} calculation 項目: {', '.join(items)}")
                            except:
                                return await ctx.send(f"參數: {params}格式錯誤, 應為 (price_vol, bid_ask...)")
                        else:
                            return await ctx.send("請提供有效的格式，例如 /system modify stock 2330 calculation (price_vol, bid_ask...)")
                        
                    elif args[3] == 'params': # 修改個別交易項目 params 參數
                        # 把括號部分整合成一個完整字符串
                        params = " ".join(args[4:])
                        # 使用正則表達式提取括號內的鍵值對
                        match = re.match(r"\(([\w\s:,\d]+)\)", params)
                    
                        if match:
                            try:
                                # 將鍵值對解析成字典
                                kv_pairs = [kv.strip() for kv in match.group(1).split(",")]
                                param_dict = {}
                                for kv in kv_pairs:
                                    key, value = kv.split(":")
                                    key = key.strip()
                                    value = value.strip()

                                    # 判斷值的類型：整數、布爾值或字符串
                                    if value.isdigit():
                                        param_dict[key] = int(value)
                                    elif value.lower() == "true":
                                        param_dict[key] = True
                                    elif value.lower() == "false":
                                        param_dict[key] = False
                                    else:
                                        param_dict[key] = value  # 保持為字符串

                                # 更新 params 設定
                                new_params_result = self.modify_item_params((args[1], args[2]), param_dict, settings)
                                if new_params_result is None: return await ctx.send(f"修改 {args[1]}, {args[2]}參數失敗, 請檢查輸入的參數是否正確")
                                
                                await ctx.send(embed=self.create_param_embed(
                                    title=f"{args[1]}, {args[2]}交易參數修改",
                                    description="參數",
                                    footer="交易參數",
                                    color=0xff7f00,
                                    params=new_params_result['params'],
                                    calculation=new_params_result['calculation']
                                ))
                            except:
                                return await ctx.send(f"參數: {params}格式錯誤, 應為 (loss:20, profit:10...)")
                        else:
                            return await ctx.send("請提供有效的格式，例如 /system modify stock 2330 params (loss:20, profit:10...)")

            elif args[0] == 'check':
                if args[1] == 'quick':
                    try:
                        result = self.quick_check(settings)
                        if not result: return await ctx.send("當前所有交易項目為空, 可以設定交易項目")
                        return await ctx.send(f"當前所有交易項目: {', '.join(result)}")
                    except:
                        return await ctx.send("請提供有效的格式，例如 /system check quick") 
                    
                elif args[1] == 'list':
                    try:
                        # 檢查 stock_items 是否非空並處理每個項目
                        for item in settings['items'][args[2]]:
                            code = item['code']

                            # 檢查 params 是否為 $ref，若是則使用 settings['params']
                            if "$ref" in item['params']:
                                params = settings['params']
                            else:
                                params = item['params']

                            # 發送嵌入消息
                            await channel.send(embed=self.create_param_embed(
                                title=f"交易類型: {args[2]}",  # 將 key 設為標題
                                description=f"代號: {code}參數",  # 代號作為描述
                                footer="交易參數",
                                color=0xff7f00,
                                params=params,
                                calculation=item['calculation']
                            ))
                    except:
                        return await ctx.send("請提供有效的格式，例如 /system check list stock") 
                
                elif args[1] == 'strategy': # 查看有哪些策略可以使用
                    try:
                        result = self.check_strategy()
                        # 將陣列中的元素轉換為字串並以逗號隔開
                        result_string = ', '.join(result)
                        return await ctx.send(f"可使用交易策略: {result_string}")
                    except:
                        return await ctx.send("請提供有效的格式，例如 /system check strategy")
                
                elif args[1] == 'params': # 查看有那些參數可以設定
                    try:
                        # 將陣列中的元素轉換為字串並以逗號隔開
                        return await ctx.send(embed=self.create_msg_embed(
                            title="參數名稱意義",
                            description="可用參數",
                            footer="交易參數",
                            color=0xff7f00,
                            params={
                                'long': 'True: 做多, False: 不做',
                                'short': 'True: 做空, False: 不做',
                                'dynamic': 'True: 動態, False: 靜態',
                                'is_pct': 'True: 百分比進場, False: Ticks進場',
                                'pct': '進場百分比(0.02 = 2%)',
                                'ticks': '進場tick數(10 = 10tick)',
                                'profit_ratio': '止盈比例(0.02 = 2%)',
                                'loss_ratio': '止損比例(0.01 = 1%)',
                                'volume_threshold': '交易量門檻(10 = 10張)',
                                'period': '交易時段(30 = 30秒)',
                                'last_trade_hour': '最後可進場交易小時(10 = 10點)',
                                'last_trade_minute': '最後可進場交易分鐘(30 = 30分)',
                                'close_position_hour': '平倉小時(13 = 13點)',
                                'close_position_minute': '平倉分鐘(0 = 0分)',
                                'cash': '倉位資金(1000 = 1千塊)'
                            }
                        ))
                    except:
                        return await ctx.send("請提供有效的格式，例如 /system check params")
                
                else: # 查看個別交易項目所有內容
                    # 把第三個參數（括號部分）整合成一個完整字符串
                    params = " ".join(args[2:])
                    # 使用正則表達式提取括號內的數值
                    match = re.match(r"\(([\d,\s]+)\)", params)
                    if match:
                        try:
                            # 分解出多個股票代碼，並去除空格
                            items = [s.strip() for s in match.group(1).split(",")]
                            # 將每個股票代碼逐一添加
                            for item in items:
                                result = self.check_items((args[1], item), settings)
                                if result is None: return await ctx.send(f"交易類型: {args[1]}, 代號: {item} 不存在, 請檢查")
                                
                                # 判斷 params 是否是 $ref，若是則使用 settings['params']
                                if "$ref" in result['params']:
                                    params = settings['params']
                                else:
                                    params = result['params']
                            
                                await ctx.send(embed=self.create_param_embed(
                                    code=item,
                                    title=f"交易類型: {args[1]}",
                                    description=f" {item}參數",
                                    footer="交易參數",
                                    params=params,
                                    calculation=result['calculation'],
                                    color=0xff7f00
                                ))
                        except:
                            return await ctx.send(f"參數: {params}格式錯誤, 應為 (3550, 2330...)")
                    else:
                        return await ctx.send("請提供有效的格式，例如 /system check stock (3550, 2330...)")
                    
            #新指令添加在此縮排
            
    def add_items(self, item, settings):
        # 確保對應的類型是列表，避免覆蓋原有的資料, 如果不是列表，就初始化為空列表
        if not isinstance(settings["items"][item[0]], list):
            settings["items"][item[0]] = []
        
        # 檢查是否已經存在相同的 code，如果存在則跳過
        if not any(exist['code'] == item[1] for exist in settings["items"][item[0]]):
            # 添加新的標的
            settings["items"][item[0]].append({"code": item[1], "calculation": [], "params": {"$ref": "#/params"}})
            
        self.write_system_settings(settings)
        return next((code for code in settings['items'][item[0]] if code['code'] == item[1]), None)
      
    def remove_items(self, item, settings):
        settings["items"][item[0]] = [code for code in settings["items"][item[0]] if code["code"] != item[1]]
        
        self.write_system_settings(settings)
        return settings
        
    def check_items(self, item, settings):
        return next((code for code in settings['items'][item[0]] if code['code'] == item[1]), None)

    def quick_check(self, settings):
        # 初始化一個空的陣列用於存儲所有 code
        codes = []

        # 遍歷 items 中的每個類別
        for item_type, items in settings["items"].items():
            for item in items:
                # 檢查 item 是否有 'code' 欄位，並將其添加到 codes 陣列中
                if "code" in item:
                    codes.append(item["code"])

        return codes
    
    def check_strategy(self):
        # 設定要列出檔案的目錄
        directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'strategy', 'calculation'))

        # 使用 os.listdir() 列出目錄中的所有文件
        file_names = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

        # 如果需要只取檔名，不要副檔名，可以使用 os.path.splitext()
        return [os.path.splitext(f)[0] for f in file_names]
    
    def modify_params(self, param_dict, settings):
        # 用於存放不存在的鍵
        missing_keys = []
    
        # 遍歷需要更新的項目
        for key, value in param_dict.items():
            if key in settings['params']:
                # 如果鍵存在於 params 中，則進行更新
                settings['params'][key] = value
            else:
                # 如果鍵不存在，則記錄在 missing_keys 中
                missing_keys.append(key)

        # 如果有缺失的鍵，返回 None 並列出這些鍵
        if missing_keys:
            return None
        
        self.write_system_settings(settings)
        return settings['params']
    
    def modify_item_calculation(self, item, settings):
        # 檢查 strategy 中是否包含 item[2]
        strategy = self.check_strategy()  # 回傳陣列，如 ['bid_ask', 'price_vol']
        # 根據 item[0] 和 item[1] 查找 settings 中的對應商品
        item_type = item[0]
        item_code = item[1]
        item_calc = item[2]
        
        if item_calc not in strategy: 
            return None

        # 檢查 settings 中是否有對應的 item_type
        if item_type not in settings["items"]:         
            return None

        # 查找 item_code 的對應設置
        target_item = None
        for entry in settings["items"][item_type]:
            if entry["code"] == item_code:
                target_item = entry
                break
        
        # 如果沒有找到對應的 item_code，則返回 None
        if target_item is None:
            return None

        # 設置 calculation 的值為 item[2]（即 item_calc）
        if item_calc not in target_item["calculation"]:
            target_item["calculation"].append(item_calc)

        self.write_system_settings(settings)
        return True
        
    def modify_item_params(self, item, param_dict, settings):
        # 用於存放不存在的鍵
        missing_keys = []

        # 查找指定的項目類型（如 stock）中的 code 為指定值（如 2330）的項目
        item_list = settings['items'].get(item[0], [])
        target_index = next((index for index, i in enumerate(item_list) if i['code'] == item[1]), None)

        # 如果找不到指定的項目，返回 None
        if target_index is None:
            return None

        # 獲取項目的 params 進行更新
        target_item = item_list[target_index]
        params = target_item.get('params')
        
        # 如果 params 中存在 "$ref": "#/params"，將其替換為全局 settings['params']
        if params.get('$ref') == '#/params':
            # 將 settings['params'] 的值複製到 params 中
            params = settings['params'].copy()
            # 更新 target_item 的 params
            target_item['params'] = params

        # 遍歷 param_dict 中的項目，進行更新
        for key, value in param_dict.items():
            if key in params:
                # 如果鍵存在於 params 中，則更新
                params[key] = value
            else:
                # 如果鍵不存在，則記錄在 missing_keys 中
                missing_keys.append(key)

        # 如果有缺失的鍵，返回 None 並列出這些鍵
        if missing_keys:
            return None
        
        # 將更新後的 target_item 回寫到 settings 數據中
        settings['items'][item[0]][target_index] = target_item
        
        # 調用 write_system_settings() 以保存更改
        self.write_system_settings(settings)

        # 最後返回更新後的 target_item
        return target_item
          
    def create_param_embed(self, title, description, footer, params=None, calculation=[], color=0xff7f00, code=None):
        """建立一個股票通知的 embed，並添加動態欄位"""
        new_params = {
            "做多": params['long'],
            "做空": params['short'],
            "倉位型態": "動態" if params['dynamic'] else "靜態",
            "進場型態": "百分比%" if params['is_pct'] else "Tick數",
            "進場百分比": params['pct'],
            "進場Tick數": params['ticks'],
            "止盈": params['profit_ratio'],
            "止損": params['loss_ratio'],
            "成交量門檻": params['volume_threshold'],
            "監測秒數": params['period'],
            "最後交易時間": f"{params['last_trade_hour']}:{params['last_trade_minute']}",
            "平倉時間": f"{params['close_position_hour']}:{params['close_position_minute']}", 
            "倉位資金": params['cash']
        }
        
        if code: # 如果有商品編號, 則依照編號取得參數
            embed = Embed(
                title=title,
                description=f'交易代號:「{description}」',
                color=color,
                timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
            )

            embed.set_author(name="交易系統參數與設定")
            
            # 檢查 calculation 是否為空
            if not calculation:
                # 如果 calculation 為空，則添加預設的策略
                new_params['無交易策略'] = ['請添加策略']
            else:
                for index, value in enumerate(calculation, start=1):
                    new_params[f'策略{index}'] = value
                
            # 動態添加欄位，每四個欄位換行
            fields = list(new_params.items())
            for _, (name, value) in enumerate(fields):
                embed.add_field(name=name, value=value, inline=True)

            # 添加 footer
            embed.set_footer(text=footer)
            
        else: # 沒有編號, 全局參數設定
            embed = Embed(
                title=title,
                description=f'以下是可使用的「{description}」',
                color=color,
                timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
            )

            embed.set_author(name="交易系統參數與設定")
            
            if calculation is not None:
                # 使用 for 迴圈來添加策略
                for index, value in enumerate(calculation, start=1):
                    new_params[f'策略{index}'] = value
            
            # 動態添加欄位，每四個欄位換行
            fields = list(new_params.items())
            for _, (name, value) in enumerate(fields):
                embed.add_field(name=name, value=value, inline=True)

            # 添加 footer
            embed.set_footer(text=footer)            

        return embed

    def create_msg_embed(self, title, description, footer, params, color=0x00ff00):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是可使用的「{description}」',
            color=color,
            timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
        )
        
        embed.set_author(name="交易系統參數與設定")
        
        

        # 動態添加欄位，每四個欄位換行
        fields = list(params.items())
        for _, (name, value) in enumerate(fields):
            embed.add_field(name=name, value=value, inline=True)

        # 添加 footer
        embed.set_footer(text=footer)

        return embed
                
    def read_system_settings(self):
        try:
            with open(self.setpath, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            return settings
        except FileNotFoundError:
            return None  # 文件不存在
        except json.JSONDecodeError:
            return None  # JSON 格式錯誤
        
    def write_system_settings(self, new_settings):
        # 寫入設定
        with open(self.setpath, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, ensure_ascii=False, indent=4)    
        return
        
async def setup(bot):
    await bot.add_cog(SystemCog(bot, int(os.getenv('DISCORD_SYSTEM_CHANNEL'))))
