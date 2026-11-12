"""模型命令：列出可用模型、切换当前模型、查看当前模型。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .util import split_text
from ..gpt_core.access import AccessError, AccessResolution, resolve_access
from ..gpt_core.common import ParamError, GPTDrawError
from ..gpt_core.models import (
    ModelInfo,
    ModelListError,
    match_model,
    fetch_models,
    filter_models,
    recent_models,
    selected_model,
    remember_models,
    save_selected_model,
    clear_selected_model,
)
from ..gpt_core.settings import Settings, load_settings

sv_model = SV("GPTDraw 模型", pm=6, area="ALL")

MODEL_USAGE = (
    "模型用法：\n"
    "gpt模型列表 [关键词|全部] — 查看当前密钥可用的模型\n"
    "gpt切换模型 <序号|模型名> — 切换之后生图使用的模型\n"
    "gpt当前模型 — 查看当前模型\n"
    "gpt切换模型 默认 — 恢复配置里的默认模型"
)

_RESET_WORDS = frozenset({"默认", "default", "恢复默认", "重置", "auto"})


async def _load_models(bot: Bot, ev: Event) -> tuple[Settings, AccessResolution, list[ModelInfo]] | None:
    settings = load_settings()
    try:
        settings.require_api_base()
    except ParamError as exc:
        await bot.send(f"❌ {exc}\n请在配置 GPTDraw 中填写 New API 地址。")
        return None
    try:
        access = await resolve_access(ev)
    except AccessError as exc:
        await bot.send(str(exc))
        return None
    try:
        models = await fetch_models(settings, access.api_key, force=True)
    except (ModelListError, GPTDrawError) as exc:
        await bot.send(f"❌ {exc}")
        return None
    return settings, access, models


def _current_model_text(settings: Settings, selected: str) -> str:
    if selected:
        return f"🧠 当前模型：{selected}（已手动切换）\n配置默认：{settings.default_image_model}"
    return f"🧠 当前模型：{settings.default_image_model}（配置默认）"


@sv_model.on_command(
    ("模型列表", "模型"),
    block=True,
    to_ai="""查看 GPTDraw 可用模型

当用户想看有哪些画图模型，或想换模型时调用。

Args:
    text: 留空查看常用模型；"全部" 查看全部模型；也可以填关键词筛选。""",
)
async def model_list_command(bot: Bot, ev: Event) -> None:
    keyword = ev.text.strip()
    if keyword in ("帮助", "help", "？", "?"):
        await bot.send(MODEL_USAGE)
        return
    loaded = await _load_models(bot, ev)
    if loaded is None:
        return
    settings, access, models = loaded
    filter_word = keyword or settings.model_list_filter
    visible = filter_models(models, filter_word)
    notice = ""
    if not visible:
        visible = models
        notice = f"没有名称包含「{filter_word}」的模型，下面是全部 {len(visible)} 个：\n"
    current = await selected_model(ev.bot_id, ev.user_id) or settings.default_image_model
    remember_models(ev.bot_id, ev.user_id, visible)
    lines = [f"🧠 可用模型（{len(visible)} 个，密钥来源：{access.source}）"]
    if notice:
        lines.append(notice.rstrip("\n"))
    for index, model in enumerate(visible, start=1):
        mark = "⭐" if model.id == current else "·"
        lines.append(f"{mark} {index}. {model.id}")
    lines.append("")
    lines.append(f"当前使用：{current}")
    lines.append("切换：gpt切换模型 <序号|模型名>；看全部：gpt模型列表 全部")
    for chunk in split_text("\n".join(lines)):
        await bot.send(chunk)


@sv_model.on_command(
    ("切换模型", "选择模型", "使用模型", "模型切换"),
    block=True,
    to_ai="""切换 GPTDraw 使用的模型

当用户想换一个画图模型时调用，参数是模型序号或完整模型名。

Args:
    text: 模型序号（见 gpt模型列表）或完整模型名；填 "默认" 恢复配置默认模型。""",
)
async def switch_model_command(bot: Bot, ev: Event) -> None:
    query = ev.text.strip()
    if not query:
        await bot.send(f"用法：gpt切换模型 <序号|模型名>\n\n{MODEL_USAGE}")
        return
    if query in _RESET_WORDS:
        settings = load_settings()
        removed = await clear_selected_model(ev.bot_id, ev.user_id)
        state = "已恢复配置默认模型" if removed else "本来就在用配置默认模型"
        await bot.send(f"✅ {state}：{settings.default_image_model}")
        return
    loaded = await _load_models(bot, ev)
    if loaded is None:
        return
    settings, _access, models = loaded
    try:
        if query.isdigit():
            listed = recent_models(ev.bot_id, ev.user_id) or filter_models(models, settings.model_list_filter)
            target = match_model(listed, query)
        else:
            target = match_model(models, query)
    except ParamError as exc:
        await bot.send(f"❌ {exc}")
        return
    await save_selected_model(ev.bot_id, ev.user_id, target)
    await bot.send(f"✅ 已切换到模型：{target}\n之后生图默认用它；单次临时指定：--model {target}")


@sv_model.on_command(
    ("当前模型", "我的模型"),
    block=True,
    to_ai="""查看 GPTDraw 当前使用的模型

当用户问现在用哪个画图模型时调用。""",
)
async def current_model_command(bot: Bot, ev: Event) -> None:
    settings = load_settings()
    selected = await selected_model(ev.bot_id, ev.user_id)
    lines = [
        _current_model_text(settings, selected),
        "",
        "切换：gpt切换模型 <序号|模型名>",
        "看列表：gpt模型列表",
        "恢复默认：gpt切换模型 默认",
    ]
    await bot.send("\n".join(lines))


__all__ = ["MODEL_USAGE", "current_model_command", "model_list_command", "sv_model", "switch_model_command"]
