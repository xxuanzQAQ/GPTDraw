"""预设命令：列出、调用、增删与远程提示词库同步。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .util import split_text
from ..gpt_core.access import AccessError, AccessResolution, resolve_access
from ..gpt_core.common import ParamError, normalize_preset_name
from ..gpt_core.models import selected_model
from ..gpt_core.params import DrawRequest, build_request, parse_options, apply_inline_options
from ..gpt_core.presets import (
    PresetEntry,
    get_preset,
    list_presets,
    refresh_remote,
    save_local_preset,
    delete_local_preset,
)
from ..gpt_core.service import generate
from ..gpt_core.settings import Settings, load_settings

sv_preset = SV("GPTDraw 预设", pm=6, area="ALL")

PRESET_USAGE = (
    "预设用法：\n"
    "gpt预设列表 — 查看所有可用预设\n"
    "gpt预设 <名称> [额外提示词] — 用预设生图\n"
    "gpt预设添加 <名称> <提示词> — 添加本地预设\n"
    "gpt预设删除 <名称> — 删除本地预设（主人）\n"
    "gpt重载预设库 — 立即同步远程提示词库"
)


@sv_preset.on_command(
    ("预设",),
    block=True,
    to_ai="""查看或管理 GPTDraw 预设

当用户想看预设列表、用预设生图、添加或删除预设时调用。

Args:
    text: "列表" / "查看"；或 "<预设名> [额外提示词]" 用预设生图；或 "添加 <名称> :: <提示词>"；或 "删除 <名称>"（仅主人）。""",
)
async def gpt_preset_command(bot: Bot, ev: Event) -> None:
    raw = ev.text.strip()
    head, _, rest = raw.partition(" ")
    if raw in ("", "列表", "查看", "全部") or head in ("列表", "查看"):
        await _send_list(bot)
        return
    if head == "帮助":
        await bot.send(PRESET_USAGE)
        return
    if head == "添加":
        await _add_preset(bot, ev, rest.strip())
        return
    if head == "删除":
        await _delete_preset(bot, ev, rest.strip())
        return
    await _draw_preset(bot, ev, head, rest.strip())


@sv_preset.on_command(("重载预设库", "刷新预设库", "同步预设库"), block=True)
async def reload_presets_command(bot: Bot, ev: Event) -> None:
    settings = load_settings()
    if not settings.preset_api_base_url:
        await bot.send("配置里没有填写提示词库地址，远程预设同步已关闭。")
        return
    count = await refresh_remote(settings, force=True)
    await bot.send(f"✅ 已同步远程预设，共 {count} 条。本地预设始终可用。")


async def _send_list(bot: Bot) -> None:
    settings = load_settings()
    entries = await list_presets(settings)
    if not entries:
        await bot.send("当前没有可用预设。\n" + PRESET_USAGE)
        return
    lines = [f"🖼️ 可用预设（{len(entries)} 个）："]
    for entry in entries:
        source = "本地" if entry.source == "local" else "远程"
        lines.append(f"{entry.name}（{source}）")
    lines.append("\n调用：gpt预设 <名称> [额外提示词]")
    for chunk in split_text("\n".join(lines)):
        await bot.send(chunk)


async def _add_preset(bot: Bot, ev: Event, rest: str) -> None:
    if not rest:
        await bot.send("用法：gpt预设添加 <名称> <提示词>")
        return
    name, _, prompt = rest.partition("::")
    if not prompt:
        name, _, prompt = rest.partition(" ")
    clean_name = normalize_preset_name(name.strip())
    settings = load_settings()
    if clean_name and await get_preset(settings, clean_name) is not None:
        await bot.send(f"❌ 预设【{clean_name}】已存在（本地或远程），请换一个名字。")
        return
    try:
        saved = await save_local_preset(clean_name, prompt.strip(), ev.user_id)
    except ParamError as exc:
        await bot.send(f"❌ {exc}")
        return
    await bot.send(f"✅ 已保存预设【{saved}】。\n调用：gpt预设 {saved}")


async def _delete_preset(bot: Bot, ev: Event, name: str) -> None:
    if ev.user_pm > 0:
        await bot.send("❌ 删除预设仅限主人。")
        return
    if not name:
        await bot.send("用法：gpt预设删除 <名称>")
        return
    try:
        removed = await delete_local_preset(name)
    except ParamError as exc:
        await bot.send(f"❌ {exc}")
        return
    await bot.send(f"✅ 已删除预设【{removed}】。")


async def _draw_preset(bot: Bot, ev: Event, name: str, extra: str) -> None:
    settings = load_settings()
    try:
        settings.require_api_base()
    except ParamError as exc:
        await bot.send(f"❌ {exc}\n请在配置 GPTDraw 中填写 New API 地址。")
        return
    try:
        access = await resolve_access(ev)
    except AccessError as exc:
        await bot.send(str(exc))
        return
    preset = await get_preset(settings, name)
    if preset is None:
        await bot.send(f"❌ 未找到预设【{name}】。用「gpt预设列表」查看可用预设。")
        return
    chosen_model = await selected_model(ev.bot_id, ev.user_id)
    request = build_preset_request(preset, extra, settings, default_model=chosen_model)
    if request is None:
        await bot.send("❌ 参数错误：预设提示词为空或参数不合法。")
        return
    caption = preset.reply or f"✨ 图片生成完成｜{preset.name}（密钥来源：{access.source}）"
    await generate_preset(bot, ev, preset, request, access, settings, caption)


def build_preset_request(
    preset: PresetEntry,
    extra: str,
    settings: Settings,
    *,
    default_model: str = "",
) -> DrawRequest | None:
    extra_options, extra_prompt = parse_options(extra)
    extra_options, extra_prompt = apply_inline_options(extra_options, extra_prompt, settings)
    preset_options, preset_prompt = apply_inline_options({}, preset.prompt, settings)
    options = {**preset_options, **extra_options}
    prompt = preset_prompt
    if extra_prompt:
        prompt = f"{prompt}\n{extra_prompt}"
    try:
        return build_request(options, prompt, extra_prompt, settings, default_model=default_model)
    except ParamError:
        return None


async def generate_preset(
    bot: Bot,
    ev: Event,
    preset: PresetEntry,
    request: DrawRequest,
    access: AccessResolution,
    settings: Settings,
    caption: str,
) -> None:
    await generate(bot, ev, request, access, settings, caption=caption)


__all__ = [
    "PRESET_USAGE",
    "build_preset_request",
    "generate_preset",
    "gpt_preset_command",
    "reload_presets_command",
    "sv_preset",
]
