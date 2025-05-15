from discord.ext import commands
from discord import Embed
import os, pytz
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

class SignalCog(commands.Cog):
    def __init__(self, bot, channel_id: int, timezone="Asia/Taipei"):
        self.bot = bot
        self.channel_id = channel_id
        self.timezone = timezone
            
    def create_msg_embed(self, title, description, footer, params, color=0x00ff00):
        """建立一個股票通知的 embed，並添加動態欄位"""
        embed = Embed(
            title=title,
            description=f'以下是最新的訊號「{description}」',
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
                
    async def send_signal_notification(self, title, description, footer, params, color=0x00ff00):
        """推播股票下單訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        
        if not channel:
            raise RuntimeError("無法找到指定的頻道，推播失敗。")
        
        try:
            await channel.send(embed=self.create_msg_embed(title, description, footer, params, color))
        except Exception as e:
            print(f"推播Signal訊息時出現錯誤: {e}")

async def setup(bot):
    await bot.add_cog(SignalCog(bot, int(os.getenv('DISCORD_SIGNAL_CHANNEL'))))
