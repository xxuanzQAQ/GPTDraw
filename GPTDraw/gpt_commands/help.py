"""帮助命令与全局帮助注册。"""

from PIL import Image, ImageDraw

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.help.utils import register_help, clean_plugin_help
from gsuid_core.utils.fonts.fonts import core_font

from ..gpt_core.help_card import render_help_image

sv_help = SV("GPTDraw 帮助", pm=6, area="ALL")

# 图片渲染不可用时的兜底文本，只保留用户需要的命令。
HELP_TEXT = """🎨 GPTDraw 生图帮助

【密钥】
gpt设置密钥 <密钥> — 绑定你的 New API 密钥
gpt我的密钥 — 查看已绑定的密钥
gpt删除密钥 [序号|全部] — 删除已绑定的密钥

【模型】
gpt模型列表 [关键词|全部] — 查看当前密钥可用的模型
gpt切换模型 <序号|模型名> — 切换之后生图使用的模型
gpt当前模型 — 查看当前模型
gpt切换模型 默认 — 恢复配置里的默认模型

【生图】
gpt生图 <提示词> — 文生图
gpt画图 / gptbnn <提示词> — 同上
附带一张图 — 这张图作为参考图改图
--model / --size / --format gif — 临时换模型、画幅、输出格式
--quality / --background / --frame_count — 质量、背景、GIF 帧数

【预设】
gpt预设列表 — 查看可用预设
gpt预设 <名称> [额外提示词] — 用预设生图
gpt预设添加 <名称> <提示词> — 添加本地预设
gpt重载预设库 — 立即同步远程提示词库

【授权】
gpt授权本群开启 / 关闭 — 让本群成员用你的密钥生图
gpt授权 @某人 — 允许对方私聊使用你的密钥
gpt取消授权 @某人 — 收回个人授权
gpt授权状态 — 查看当前授权情况"""


async def send_help(bot: Bot) -> None:
    try:
        image = await render_help_image()
    except (RuntimeError, OSError, ValueError) as exc:
        logger.exception(f"[GPTDraw] 帮助图渲染失败，已回退文本: {exc}")
        await bot.send(HELP_TEXT)
        return
    await bot.send(image)


@sv_help.on_fullmatch(("帮助", "菜单", "help"), block=True)
async def help_command(bot: Bot, ev: Event) -> None:
    await send_help(bot)


def _help_icon() -> Image.Image:
    size = 64
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = ImageDraw.Draw(icon)
    for y in range(size):
        ratio = y / (size - 1)
        gradient.line(
            [(0, y), (size, y)],
            fill=(
                round(99 + (34 - 99) * ratio),
                round(102 + (211 - 102) * ratio),
                round(241 + (238 - 241) * ratio),
                255,
            ),
        )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill=255)
    icon.putalpha(mask)
    font = core_font(34, weight=700)
    draw = ImageDraw.Draw(icon)
    left, top, right, bottom = draw.textbbox((0, 0), "G", font=font)
    draw.text(
        ((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
        "G",
        font=font,
        fill=(255, 255, 255, 255),
    )
    return icon


def register_plugin_help() -> None:
    clean_plugin_help("GPTDraw")
    register_help("GPTDraw", "gpt帮助", _help_icon())


__all__ = ["HELP_TEXT", "help_command", "register_plugin_help", "send_help", "sv_help"]
