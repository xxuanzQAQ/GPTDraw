"""插件元命令：热重载。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.utils.plugins_update.reload_plugin import reload_plugin

from ..gpt_core.presets import clear_remote

sv_admin = SV("GPTDraw 管理", pm=0, area="ALL")


@sv_admin.on_command(("重载插件", "重载GPTDraw"), block=True)
async def reload_command(bot: Bot, ev: Event) -> None:
    await bot.send("♻️ 正在重载 GPTDraw ...")
    await bot.bot.wait_send_queue()
    clear_remote()
    # reload_plugin 是同步阻塞函数，返回成功 / 失败提示，必须回给用户。
    message = reload_plugin("GPTDraw")
    await bot.send(message)


__all__ = ["reload_command", "sv_admin"]
