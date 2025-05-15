from discord.ext import commands
from discord import Embed
from datetime import datetime
import os, pytz
from dotenv import load_dotenv
load_dotenv()

class FutureCog(commands.Cog):
    def __init__(self, bot, channel_id: int, timezone="Asia/Taipei"):
        self.bot = bot
        self.channel_id = channel_id
        self.timezone = timezone
        self.broker = bot.broker

    @commands.command(name="fcmd")
    async def check_command(self, ctx):
        channel = self.bot.get_channel(self.channel_id)
        
        if channel:
            return await channel.send(embed=self.create_future_embed(
                title="期貨指令操作集",
                description="DC期貨指令",
                footer="DC指令",
                color=0xD3D3D3,
                params={
                    "查看可查詢卷商": "/future broker",
                    "查看卷商銀行餘額": "/future [卷商] balance",
                    "查看卷商保證金": "/future [卷商] margin",
                    "查看卷商結算": "/future [卷商] settle"
                }
            ))
        else:
            return await ctx.send("/fcmd 無法找到指定的頻道。")
        
    @commands.command(name="future")
    async def future_command(self, ctx, *args):
        """發送告別訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            # 找尋指定的卷商並查詢
            if args[0] in self.broker:
                check_broker = self.broker[args[0]]
                
                if args[0] == 'shioaji': # 永豐的API相關操作
                    if args[1] == 'balance': # 檢查銀行餘額
                        try:
                            result = check_broker.check_balance()
                            if result is None: return await ctx.send("獲取未實現損益失敗")
                            elif isinstance(result, str): return await ctx.send(f"獲取balance餘額失敗，錯誤訊息：{result}")

                            return await ctx.send(embed=self.create_future_embed(
                                title="查看當前帳戶餘額",
                                description="帳戶餘額",
                                footer="DC指令",
                                color=0xD3D3D3,
                                params={
                                    "帳戶餘額": result.acc_balance ,
                                    "查詢日期": result.date
                                }
                            ))

                        except:
                            return await ctx.send("請檢察指令 /future [卷商] balance")
                        
                    elif args[1] == 'margin': # 查看當前保證金
                        try:
                            result = check_broker.check_margin()
                            if result is None: return await ctx.send("獲取保證金失敗")
                            elif isinstance(result, str): return await ctx.send(f"獲取保證金餘額失敗，錯誤訊息：{result}")

                            return await ctx.send(embed=self.create_future_embed(
                                title="查看當前帳戶保證金餘額",
                                description="保證金餘額",
                                footer="DC指令",
                                color=0xD3D3D3,
                                params={
                                    "資料回傳狀態": result.status,
                                    "前日餘額": result.yesterday_balance,
                                    "今日餘額": result.today_balance,
                                    "存提": result.deposit_withdrawal,
                                    "手續費": result.fee,
                                    "期交稅": result.tax,
                                    "原始保證金": result.initial_margin,
                                    "維持保證金": result.maintenance_margin,
                                    "追繳保證金": result.margin_call,
                                    "風險指標": result.risk_indicator,
                                    "權利金收入與支出": result.royalty_revenue_expenditure,
                                    "權益數": result.equity,
                                    "權益總值": result.equity_amount,
                                    "未沖銷買方選擇權市值": result.option_openbuy_market_value,
                                    "未沖銷賣方選擇權市值": result.option_opensell_market_value,
                                    "參考未平倉選擇權損益": result.option_open_position,
                                    "參考選擇權平倉損益": result.option_settle_profitloss,
                                    "未沖銷期貨浮動損益": result.future_open_position,
                                    "參考當日未沖銷期貨浮動損益": result.today_future_open_position,
                                    "期貨平倉損益": result.future_settle_profitloss,
                                    "可動用(出金)保證金": result.available_margin,
                                    "依「加收保證金指標」所加收之保證金": result.plus_margin,
                                    "加收保證金指標": result.plus_margin_indicator,
                                    "有價證券抵繳總額": result.security_collateral_amount,
                                    "委託保證金及委託權利金": result.order_margin_premium,
                                    "有價品額": result.collateral_amount
                                }
                            ))

                        except:
                            return await ctx.send("請檢察指令 /future [卷商] balance")

                    elif args[1] == 'settle': # 查看結算
                        try:
                            result = check_broker.check_settle()
                            if result is None: return await ctx.send("獲取結算結果失敗")
                            elif isinstance(result, str): return await ctx.send(f"獲取結算結果失敗，錯誤訊息：{result}")

                            # 遍歷每個結算結果
                            for settlement in result:
                                await ctx.send(embed=self.create_future_embed(
                                    title="查看當前帳戶結算結果",
                                    description="帳戶結算",
                                    footer="DC指令",
                                    color=0xD3D3D3,
                                    params={
                                    "交割日期": settlement.date.strftime('%Y-%m-%d'),  # 將日期格式化為字符串
                                    "交割金額": settlement.amount,
                                    "T日": settlement.T
                                }))

                        except:
                            return await ctx.send("請檢察指令 /future [卷商] settle")
                      
            # 查看可使用的卷商列表
            elif args[0] == 'broker':
                # 创建并发送嵌入消息
                await ctx.send(embed=self.create_future_embed(
                    title="可用券商列表",
                    description="以下是當前可用的券商",
                    footer="DC指令",
                    color=0xD3D3D3,
                    params={f"卷商{index + 1}": broker for index, broker in enumerate(self.broker)}
                ))
        else:
            await ctx.send("無法找到指定的頻道。")
  
    def create_future_embed(self, title, description, footer, params, color=0xD3D3D3):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是Future指令「{description}」',
            color=color,
            timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
        )
        
        embed.set_author(name="Future操作")

        # 動態添加欄位，每四個欄位換行
        fields = list(params.items())
        for _, (name, value) in enumerate(fields):
            embed.add_field(name=name, value=value, inline=True)

        # 添加 footer
        embed.set_footer(text=footer)

        return embed
    
    def create_msg_embed(self, title, description, footer, params, color=0x00ff00):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是最新的期貨「{description}」下單資訊',
            color=color,
            timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
        )
        
        embed.set_author(name="交易通知系統")

        # 動態添加欄位，每四個欄位換行
        fields = list(params.items())
        for _, (name, value) in enumerate(fields):
            embed.add_field(name=name, value=value, inline=True)

        # 添加 footer
        embed.set_footer(text=footer)

        return embed
            
    async def send_future_order_notification(self, title, description, footer, params, color=0x00ff00):
        """推播股票下單訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=self.create_msg_embed(title, description, footer, params, color))
        else:
            print("無法找到指定的頻道，推播失敗。")

async def setup(bot):
    await bot.add_cog(FutureCog(bot, int(os.getenv('DISCORD_FUTURE_ORDER_CHANNEL'))))
    