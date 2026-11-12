"""生图命令：gpt生图 / gpt画图 / gptbnn。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .help import send_help
from ..gpt_core.access import AccessError, resolve_access
from ..gpt_core.common import ParamError
from ..gpt_core.models import selected_model
from ..gpt_core.params import build_request, parse_options, apply_inline_options
from ..gpt_core.service import generate
from ..gpt_core.settings import load_settings

sv_draw = SV("GPTDraw 生图", pm=6, area="ALL")

DRAW_USAGE = (
    "用法：gpt生图 <提示词> [--model 模型] [--size 1:1] [--format gif]\n"
    "别名：gpt画图 / gptbnn。直接发图并附带提示词可做参考图改图。\n"
    "看模型：gpt模型列表；换模型：gpt切换模型 <序号|模型名>。"
)


@sv_draw.on_command(
    ("生图", "画图", "bnn"),
    block=True,
    to_ai="""用 GPT 生成图片

当用户要求画图、生图、改图，或给出提示词想生成图片时调用；需已绑定密钥或被授权。

Args:
    text: 提示词与可选参数，例如 "一只橘猫在窗台上晒太阳 --size 16:9 --format gif"。
          支持 1:1 / 16:9 / 2k 等内联参数；--model 可临时换模型；
          当前消息附带图片时可作为参考图改图。""",
)
async def gpt_draw_command(bot: Bot, ev: Event) -> None:
    raw = ev.text.strip()
    if raw in ("帮助", "help", "？", "?"):
        await send_help(bot)
        return
    settings = load_settings()
    try:
        settings.require_api_base()
    except ParamError as exc:
        await bot.send(f"❌ {exc}\n请在配置 GPTDraw 中填写 New API 地址。")
        return
    if not raw:
        await bot.send(DRAW_USAGE)
        return
    try:
        access = await resolve_access(ev)
    except AccessError as exc:
        await bot.send(str(exc))
        return
    options, prompt = parse_options(raw)
    options, prompt = apply_inline_options(options, prompt, settings)
    if not prompt:
        await bot.send("❌ 请输入提示词，例如：gpt生图 一只橘猫在窗台上晒太阳 --size 16:9")
        return
    chosen_model = await selected_model(ev.bot_id, ev.user_id)
    try:
        request = build_request(options, prompt, ev.raw_text, settings, default_model=chosen_model)
    except ParamError as exc:
        await bot.send(f"❌ 参数错误：{exc}")
        return
    await generate(bot, ev, request, access, settings)


__all__ = ["DRAW_USAGE", "gpt_draw_command", "sv_draw"]
