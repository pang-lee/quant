from discord.ext import commands
from discord import Embed
from datetime import datetime
import os, pytz
from dotenv import load_dotenv
load_dotenv()

class OptionCog(commands.Cog):
    def __init__(self, bot, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id

            
    def create_option_embed(self, title, description, footer, params, color=0xD3D3D3):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是Option指令「{description}」',
            color=color,
            timestamp=datetime.now(pytz.timezone(self.timezone))  # 使用指定時區
        )
        
        embed.set_author(name="Option操作")

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
            description=f'以下是最新的選擇權「{description}」下單資訊',
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
    
    async def send_option_order_notification(self, title, description, footer, params, color=0x00ff00):
        """推播股票下單訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(embed=self.create_msg_embed(title, description, footer, params, color))
        else:
            print("無法找到指定的頻道，推播失敗。")

async def setup(bot):
    await bot.add_cog(OptionCog(bot, int(os.getenv('DISCORD_OPTION_CHANNEL'))))