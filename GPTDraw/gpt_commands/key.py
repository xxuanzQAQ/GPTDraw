"""密钥绑定命令。"""

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..gpt_core.access import bind_key, delete_key, unbind_all, list_all_keys
from ..gpt_core.common import ParamError
from ..gpt_core.security import CipherError, decrypt_key
from ..gpt_core.settings import load_settings

sv_key = SV("GPTDraw 密钥", pm=6, area="ALL")
sv_key_admin = SV("GPTDraw 密钥管理", pm=0, area="ALL")

BIND_USAGE = (
    "用法：gpt设置密钥 <密钥>\n"
    "接口固定用配置里的 New API 地址，不用再带地址。\n"
    "建议私聊绑定；群里发送密钥会留在聊天记录里。"
)


@sv_key.on_command(("设置密钥", "绑定密钥", "设置API密钥", "绑定API密钥"), block=True)
async def bind_command(bot: Bot, ev: Event) -> None:
    settings = load_settings()
    raw = ev.text.strip()
    if not raw:
        await bot.send(BIND_USAGE)
        return
    # 地址已固定，旧习惯带的第二个参数直接忽略。
    raw_key = raw.split(maxsplit=1)[0]
    try:
        hint = await bind_key(ev.bot_id, ev.user_id, raw_key, settings.require_api_base())
    except ParamError as exc:
        await bot.send(f"❌ {exc}")
        return
    lines = [
        "✅ 已绑定生图密钥",
        f"密钥：{hint}",
        f"接口：{settings.api_base_url}",
        f"当前模型：{settings.default_image_model}（可用 gpt模型列表 查看、gpt切换模型 切换），费用记在这把密钥名下。",
        "",
        "默认仅限你使用：",
        "群聊授权：gpt授权本群开启 / gpt授权本群关闭",
        "私聊授权：gpt授权 @某人（在群聊里发）",
    ]
    if ev.group_id:
        lines.append("\n⚠️ 本次在群里发送了密钥，建议到 New API 后台更换，或以后私聊绑定。")
    await bot.send("\n".join(lines))


@sv_key.on_command(("删除密钥", "解绑密钥", "删除API密钥"), block=True)
async def delete_command(bot: Bot, ev: Event) -> None:
    raw = ev.text.strip()
    if raw in ("全部", "all"):
        count = await unbind_all(ev.bot_id, ev.user_id)
        await bot.send(f"✅ 已解绑全部 {count} 把密钥，相关授权已同时失效。")
        return
    index = 1
    if raw:
        if not raw.isdigit():
            await bot.send("用法：gpt删除密钥 [序号]（序号见「gpt我的密钥」）")
            return
        index = int(raw)
    try:
        hint = await delete_key(ev.bot_id, ev.user_id, index)
    except ParamError as exc:
        await bot.send(f"❌ {exc}")
        return
    await bot.send(f"✅ 已删除密钥 {hint}。已发出的授权会在下次判定时自动失效。")


@sv_key.on_command(("我的密钥", "密钥列表", "我的API密钥"), block=True)
async def show_keys_command(bot: Bot, ev: Event) -> None:
    from ..gpt_database.models import GptKey

    rows = await GptKey.list_keys(ev.bot_id, ev.user_id)
    if not rows:
        await bot.send(f"你还没有绑定密钥。\n{BIND_USAGE}")
        return
    lines = ["🔑 你的生图密钥："]
    for index, row in enumerate(rows, start=1):
        mark = "（当前使用）" if row.active else ""
        lines.append(f"{index}. {row.hint} {mark}")
    lines.append("\n切换某把：gpt设置密钥 <同一把密钥>")
    lines.append("删除：gpt删除密钥 <序号> / gpt删除密钥 全部")
    await bot.send("\n".join(lines))


@sv_key_admin.on_command(("全部密钥", "所有用户API密钥", "查看所有密钥"), block=True)
async def show_all_keys_command(bot: Bot, ev: Event) -> None:
    if ev.group_id:
        await bot.send("❌ 出于安全考虑，请私聊机器人执行这个命令。")
        return
    rows = await list_all_keys(ev.bot_id)
    if not rows:
        await bot.send("当前没有用户绑定生图密钥。")
        return
    lines = [f"🔐 已绑定密钥：{len(rows)} 把。以下为真实密钥，仅主人可见。", ""]
    for row in rows:
        try:
            raw = decrypt_key(row.api_key_cipher)
        except CipherError:
            raw = "<无法解密>"
        state = "当前使用" if row.active else "停用"
        lines.append(f"用户 {row.user_id}（{state}）")
        lines.append(raw)
        lines.append("")
    text = "\n".join(lines).strip()
    for start in range(0, len(text), 1200):
        await bot.send(text[start : start + 1200])


__all__ = [
    "BIND_USAGE",
    "bind_command",
    "delete_command",
    "show_all_keys_command",
    "show_keys_command",
    "sv_key",
    "sv_key_admin",
]
