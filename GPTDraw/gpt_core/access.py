"""密钥绑定、会话授权、个人授权与计费归属判定。"""

from __future__ import annotations

from dataclasses import dataclass

from gsuid_core.models import Event

from .common import (
    ParamError,
    GPTDrawError,
    mask_key,
    token_fingerprint,
)
from .security import CipherError, decrypt_key, encrypt_key
from ..gpt_database.models import GptKey, GptGrant, GptSessionAuth

MAX_KEYS_PER_USER = 10


class AccessError(GPTDrawError):
    """用户没有可用密钥，或授权状态不满足；消息可直接展示。"""


@dataclass(frozen=True)
class AccessResolution:
    owner_user_id: str
    api_key: str
    source: str


def scope_id(ev: Event) -> str:
    if ev.user_type == "direct" or not ev.group_id:
        return f"private:{ev.bot_id}:{ev.user_id}"
    return f"group:{ev.group_id}"


def normalize_key_input(raw: str) -> str:
    token = str(raw or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise ParamError("密钥不能为空。")
    if len(token) < 8 or len(token) > 200:
        raise ParamError("密钥长度不合法。")
    if any(char.isspace() for char in token):
        raise ParamError("密钥中不能包含空格。")
    return token


async def bind_key(bot_id: str, user_id: str, raw_key: str, api_base: str) -> str:
    token = normalize_key_input(raw_key)
    base = str(api_base or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ParamError("API 地址必须以 http:// 或 https:// 开头。")
    rows = await GptKey.list_keys(bot_id, user_id)
    existing = {row.fingerprint for row in rows}
    fingerprint = token_fingerprint(token)
    if fingerprint not in existing and len(rows) >= MAX_KEYS_PER_USER:
        raise ParamError(f"最多绑定 {MAX_KEYS_PER_USER} 把密钥，请先删除不用的。")
    try:
        cipher = encrypt_key(token)
    except CipherError as exc:
        raise ParamError(str(exc)) from exc
    await GptKey.bind_key(
        bot_id=bot_id,
        user_id=user_id,
        fingerprint=fingerprint,
        api_key_cipher=cipher,
        hint=mask_key(token),
        api_base=base,
    )
    return mask_key(token)


async def delete_key(bot_id: str, user_id: str, index: int) -> str:
    rows = await GptKey.list_keys(bot_id, user_id)
    if index < 1 or index > len(rows):
        raise ParamError("序号不存在。")
    old = rows[index - 1]
    removed = await GptKey.delete_by_index(bot_id, user_id, index - 1)
    if not removed:
        raise ParamError("删除失败，请稍后重试。")
    if len(rows) <= 1:
        await GptSessionAuth.clear_owner(bot_id, user_id)
        await GptGrant.delete_for_owner(bot_id, user_id)
    return old.hint or "****"


async def unbind_all(bot_id: str, user_id: str) -> int:
    count = await GptKey.delete_all_for_user(bot_id, user_id)
    await GptSessionAuth.clear_owner(bot_id, user_id)
    await GptGrant.delete_for_owner(bot_id, user_id)
    return count


async def _decrypt_row(row: GptKey) -> str:
    try:
        return decrypt_key(row.api_key_cipher)
    except CipherError as exc:
        raise AccessError(f"密钥无法解密，请重新绑定：{exc}") from exc


async def active_key(bot_id: str, user_id: str) -> str:
    row = await GptKey.get_active(bot_id, user_id)
    if row is None:
        return ""
    return await _decrypt_row(row)


async def resolve_access(ev: Event) -> AccessResolution:
    """按“本人密钥 → 会话授权 → 个人授权”的顺序解析计费密钥。"""
    own = await active_key(ev.bot_id, ev.user_id)
    if own:
        return AccessResolution(ev.user_id, own, "个人密钥")

    session = await GptSessionAuth.get_auth(ev.bot_id, scope_id(ev))
    if session is not None and session.enabled:
        owner_key = await active_key(ev.bot_id, session.owner_user_id)
        if owner_key:
            return AccessResolution(session.owner_user_id, owner_key, "会话授权")
        raise AccessError(
            "本群授权人已经解绑/更换了密钥，会话授权暂时无效。\n"
            "请让授权人重新绑定密钥，或由其他人发送「gpt授权本群开启」。"
        )

    grant = await GptGrant.get_owner_for_target(ev.bot_id, ev.user_id)
    if grant is not None:
        owner_key = await active_key(ev.bot_id, grant.owner_user_id)
        if owner_key:
            return AccessResolution(grant.owner_user_id, owner_key, "个人授权")
    raise AccessError(
        "当前会话没有可用密钥。\n"
        "1. 先发送「gpt设置密钥 sk-xxxx」绑定你的生图密钥；\n"
        "2. 群聊可让绑定者发送「gpt授权本群开启」；\n"
        "3. 私聊可让绑定者在群里发送「gpt授权 @你」。"
    )


async def authorize_session(bot_id: str, scope: str, owner_user_id: str, enabled: bool) -> bool:
    if enabled:
        own = await GptKey.get_active(bot_id, owner_user_id)
        if own is None:
            raise AccessError("你还没有绑定密钥，先发送「gpt设置密钥 sk-xxxx」。")
    await GptSessionAuth.set_auth(
        bot_id=bot_id,
        scope_id=scope,
        owner_user_id=owner_user_id,
        enabled=enabled,
    )
    return enabled


async def grant_user(bot_id: str, owner_user_id: str, target_user_id: str) -> bool:
    if owner_user_id == target_user_id:
        raise AccessError("授权对象不能是你自己。")
    own = await GptKey.get_active(bot_id, owner_user_id)
    if own is None:
        raise AccessError("你还没有绑定密钥，先发送「gpt设置密钥 sk-xxxx」。")
    return await GptGrant.add_grant(
        bot_id=bot_id,
        owner_user_id=owner_user_id,
        target_user_id=target_user_id,
    )


async def revoke_user(bot_id: str, owner_user_id: str, target_user_id: str) -> bool:
    return await GptGrant.remove_grant(
        bot_id=bot_id,
        owner_user_id=owner_user_id,
        target_user_id=target_user_id,
    )


async def list_grants(bot_id: str, owner_user_id: str) -> list[GptGrant]:
    return await GptGrant.list_by_owner(bot_id, owner_user_id)


async def grant_owner(bot_id: str, target_user_id: str) -> str:
    row = await GptGrant.get_owner_for_target(bot_id, target_user_id)
    return row.owner_user_id if row is not None else ""


async def session_state(bot_id: str, scope: str) -> GptSessionAuth | None:
    return await GptSessionAuth.get_auth(bot_id, scope)


async def list_all_keys(bot_id: str) -> list[GptKey]:
    return await GptKey.list_all_by_bot(bot_id)


__all__ = [
    "AccessError",
    "AccessResolution",
    "active_key",
    "authorize_session",
    "bind_key",
    "delete_key",
    "grant_owner",
    "grant_user",
    "list_all_keys",
    "list_grants",
    "normalize_key_input",
    "resolve_access",
    "revoke_user",
    "scope_id",
    "session_state",
    "unbind_all",
]
