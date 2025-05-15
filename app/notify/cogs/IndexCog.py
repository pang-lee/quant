from discord.ext import commands
import os
from dotenv import load_dotenv
load_dotenv()

class IndexCog(commands.Cog):
    def __init__(self, bot, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id

    @commands.command(name="index")
    async def say_hello(self, ctx):
        """發送問候訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send("Hello from Cog1!")
            await ctx.send(f"訊息已發送到頻道 {channel.mention}！")
        else:
            await ctx.send("無法找到指定的頻道。")
            
    async def send_index_notification(self, message):
        """推播股票下單訊息到指定頻道"""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            await channel.send(message)
        else:
            print("無法找到指定的頻道，推播失敗。")

async def setup(bot):
    await bot.add_cog(IndexCog(bot, int(os.getenv('DISCORD_INDEX_CHANNEL'))))
