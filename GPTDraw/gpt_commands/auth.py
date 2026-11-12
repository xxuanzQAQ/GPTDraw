"""授权命令：会话级（群）与个人级授权。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .util import target_ids
from ..gpt_core.access import (
    AccessError,
    scope_id,
    grant_user,
    grant_owner,
    list_grants,
    revoke_user,
    session_state,
    authorize_session,
)
from ..gpt_core.common import GPTDrawError
from ..gpt_database.models import GptKey

sv_auth = SV("GPTDraw 授权", pm=6, area="ALL")

_AUTH_USAGE = (
    "授权用法：\n"
    "gpt授权本群开启 — 本群成员用你的密钥生图\n"
    "gpt授权本群关闭 — 关闭本群授权\n"
    "gpt授权 @某人 — 允许对方私聊使用你的密钥\n"
    "gpt取消授权 @某人 — 收回个人授权\n"
    "gpt授权状态 — 查看当前授权情况"
)


async def _status_text(ev: Event) -> str:
    scope = scope_id(ev)
    lines: list[str] = [f"📋 授权状态（{ev.bot_id}）"]
    own = await GptKey.get_active(ev.bot_id, ev.user_id)
    lines.append(f"你的密钥：{own.hint if own is not None else '未绑定'}")
    session = await session_state(ev.bot_id, scope)
    if session is None:
        lines.append("本会话授权：未设置")
    else:
        state = "已开启" if session.enabled else "已关闭"
        lines.append(f"本会话授权：{state}（授权人 {session.owner_user_id}）")
    grants = await list_grants(ev.bot_id, ev.user_id)
    if grants:
        lines.append("你授权给：" + "、".join(row.target_user_id for row in grants))
    else:
        lines.append("你授权给：无")
    owner = await grant_owner(ev.bot_id, ev.user_id)
    lines.append(f"你被授权于：{owner or '无'}")
    return "\n".join(lines)


@sv_auth.on_command(("授权",), block=True)
async def auth_command(bot: Bot, ev: Event) -> None:
    action = ev.text.strip()
    lowered = action.lower()
    if lowered.startswith(("本群开启", "本群打开", "开启", "打开", "on")):
        await _enable_group(bot, ev)
        return
    if lowered.startswith(("本群关闭", "本群关", "关闭", "关", "off")):
        await _disable_group(bot, ev)
        return
    targets = target_ids(ev)
    if targets:
        results: list[str] = []
        for target in targets:
            try:
                added = await grant_user(ev.bot_id, ev.user_id, target)
            except (AccessError, GPTDrawError) as exc:
                results.append(f"❌ {target}：{exc}")
                continue
            results.append(f"✅ 已授权 {target} 私聊使用你的密钥" if added else f"ℹ️ {target} 早已被你授权")
        await bot.send("\n".join(results))
        return
    if lowered in {"状态", "查看", "列表", "查询"} or not action:
        await bot.send(await _status_text(ev))
        return
    await bot.send(_AUTH_USAGE)


@sv_auth.on_command(("取消授权", "解除授权", "收回授权"), block=True)
async def revoke_command(bot: Bot, ev: Event) -> None:
    action = ev.text.strip()
    if action in ("本群", "本群授权", "本群关闭", "本群画图"):
        if not ev.group_id:
            await bot.send("❌ 这个命令只能在群里用。")
            return
        await _disable_group(bot, ev)
        return
    targets = target_ids(ev)
    if not targets:
        await bot.send("用法：gpt取消授权 @某人 / gpt取消授权 本群")
        return
    results: list[str] = []
    for target in targets:
        removed = await revoke_user(ev.bot_id, ev.user_id, target)
        results.append(f"✅ 已收回 {target} 的授权" if removed else f"ℹ️ {target} 本来就没有你的授权")
    await bot.send("\n".join(results))


async def _enable_group(bot: Bot, ev: Event) -> None:
    if not ev.group_id:
        await bot.send("❌ 这个命令只能在群里用。")
        return
    try:
        await authorize_session(ev.bot_id, scope_id(ev), ev.user_id, True)
    except (AccessError, GPTDrawError) as exc:
        await bot.send(f"❌ {exc}")
        return
    await bot.send(
        "✅ 已开启本群生图授权。\n本群成员直接发送「gpt生图 提示词」即可使用你的密钥计费。\n关闭命令：gpt授权本群关闭"
    )


async def _disable_group(bot: Bot, ev: Event) -> None:
    if not ev.group_id:
        await bot.send("❌ 这个命令只能在群里用。")
        return
    try:
        await authorize_session(ev.bot_id, scope_id(ev), ev.user_id, False)
    except (AccessError, GPTDrawError) as exc:
        await bot.send(f"❌ {exc}")
        return
    await bot.send("✅ 已关闭本群生图授权，本群恢复为各用各的密钥。")


__all__ = ["auth_command", "revoke_command", "sv_auth"]
