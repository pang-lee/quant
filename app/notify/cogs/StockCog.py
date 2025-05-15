from discord.ext import commands
from discord import Embed
import os, pytz
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

class StockCog(commands.Cog):
    def __init__(self, bot, channel_id: int, timezone="Asia/Taipei"):
        self.bot = bot
        self.channel_id = channel_id
        self.timezone = timezone
        self.broker = bot.broker

    @commands.command(name="scmd")
    async def check_command(self, ctx):
        channel = self.bot.get_channel(self.channel_id)
        
        if channel:
            return await channel.send(embed=self.create_stock_embed(
                title="股票指令操作集",
                description="DC股票指令",
                footer="DC指令",
                color=0xD3D3D3,
                params={
                    "查看可查詢卷商": "/stock broker",
                    "查看卷商銀行餘額": "/stock [卷商] balance"
                }
            ))
        else:
            return await ctx.send("/scmd 無法找到指定的頻道。")
    
    @commands.command(name="stock")
    async def stock_command(self, ctx, *args):
        channel = self.bot.get_channel(self.channel_id)
        
        if channel:
            # 找尋指定的卷商並查詢
            if args[0] in self.broker:
                check_broker = self.broker[args[0]]
                
                if args[0] == 'shioaji': # 永豐的API相關操作
                    if args[1] == 'balance': # 檢查銀行餘額
                        try:
                            result = check_broker.check_balance()
                            if result is None: return await ctx.send("獲取股票未實現損益失敗")
                            elif isinstance(result, str): return await ctx.send(f"獲取balance餘額失敗，錯誤訊息：{result}")

                            return await ctx.send(embed=self.create_stock_embed(
                                title="查看當前帳戶餘額",
                                description="帳戶餘額",
                                footer="DC指令",
                                color=0xD3D3D3,
                                params={
                                    "帳戶餘額": result.acc_balance,
                                    "查詢日期": result.date
                                }
                            ))

                        except:
                            return await ctx.send("請檢察指令 /stock [卷商] balance")

            # 查看可使用的卷商列表
            elif args[0] == 'broker':
                # 创建并发送嵌入消息
                await ctx.send(embed=self.create_stock_embed(
                    title="可用券商列表",
                    description="以下是當前可用的券商",
                    footer="DC指令",
                    color=0xD3D3D3,
                    params={f"卷商{index + 1}": broker for index, broker in enumerate(self.broker)}
                ))
                
        else:
            await ctx.send("stock 無法找到指定的頻道。")
    
    def create_stock_embed(self, title, description, footer, params, color=0xD3D3D3):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是Stock指令「{description}」',
            color=color,
            timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
        )
        
        embed.set_author(name="Stock操作")

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
            description=f'以下是最新的股票「{description}」下單資訊',
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

    async def send_stock_order_notification(self, title, description, footer, params, color=0x00ff00):
        """推播股票下單訊息到指定頻道，以 embed 格式顯示"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=self.create_msg_embed(title, description, footer, params, color))
        else:
            print("無法找到指定的頻道，推播失敗。")
            
async def setup(bot):
    await bot.add_cog(StockCog(bot, int(os.getenv('DISCORD_STOCK_ORDER_CHANNEL'))))
    
