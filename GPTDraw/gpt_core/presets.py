"""预设：本地自定义预设、远程提示词库缓存与提示词展开。"""

from __future__ import annotations

import json
import time
import asyncio
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from gsuid_core.logger import logger

from .common import ParamError, join_api_url, validate_preset_name, normalize_preset_name
from .settings import Settings
from ..gpt_database.models import GptPreset

ENTRY_TYPE_PRESET = "preset"

RESERVED_PRESET_NAMES = frozenset(
    {
        "bnn",
        "生图",
        "画图",
        "预设",
        "图片预设",
        "预设列表",
        "预设添加",
        "预设删除",
        "重载预设库",
        "设置密钥",
        "删除密钥",
        "我的密钥",
        "全部密钥",
        "授权",
        "取消授权",
        "授权状态",
        "授权本群开启",
        "授权本群关闭",
        "帮助",
        "生图帮助",
        "菜单",
        "重载",
    }
)


@dataclass(frozen=True)
class PresetEntry:
    name: str
    prompt: str
    reply: str
    image: str
    source: str
    title: str = ""


_remote: dict[str, PresetEntry] = {}
_last_refresh: float = 0.0
_lock = asyncio.Lock()


def _entry_type(value: object) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {"prompt_share", "prompt", "share", "image_share", "gallery"}:
        return "prompt_share"
    return ENTRY_TYPE_PRESET


def _parse_api_item(item: object) -> PresetEntry | None:
    if not isinstance(item, dict):
        return None
    if _entry_type(item.get("entry_type")) != ENTRY_TYPE_PRESET:
        return None
    name = normalize_preset_name(item.get("name") or item.get("title"))
    prompt = str(item.get("prompt") or "").strip()
    if not name or not prompt:
        return None
    title = str(item.get("title") or name).strip() or name
    return PresetEntry(
        name=name,
        prompt=prompt,
        reply=str(item.get("reply") or "").strip(),
        image=str(item.get("image") or item.get("image_url") or "").strip(),
        source="remote",
        title=title,
    )


def remote_entries() -> list[PresetEntry]:
    return list(_remote.values())


async def _fetch_remote_list(settings: Settings) -> dict[str, PresetEntry]:
    url = join_api_url(settings.preset_api_base_url, "/api/presets")
    try:
        async with httpx.AsyncClient(timeout=float(settings.preset_api_timeout), follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload: object = json.loads(response.text)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise ParamError(f"提示词库请求失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise ParamError("提示词库返回格式无效。")
    items = payload.get("presets")
    if not isinstance(items, list):
        raise ParamError("提示词库返回格式无效：presets 不是列表。")
    presets: dict[str, PresetEntry] = {}
    for item in items:
        entry = _parse_api_item(item)
        if entry is not None:
            presets[entry.name] = entry
    return presets


async def _fetch_remote_detail(settings: Settings, name: str) -> PresetEntry | None:
    url = join_api_url(settings.preset_api_base_url, f"/api/presets/{quote(name, safe='')}")
    try:
        async with httpx.AsyncClient(timeout=float(settings.preset_api_timeout), follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload: object = json.loads(response.text)
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_api_item(payload.get("preset"))


async def refresh_remote(settings: Settings, *, force: bool = False) -> int:
    global _last_refresh
    if not settings.preset_api_base_url:
        return len(_remote)
    now = time.time()
    if not force and _last_refresh and now - _last_refresh < settings.preset_api_refresh_interval:
        return len(_remote)
    async with _lock:
        now = time.time()
        if not force and _last_refresh and now - _last_refresh < settings.preset_api_refresh_interval:
            return len(_remote)
        try:
            presets = await _fetch_remote_list(settings)
        except ParamError as exc:
            logger.warning(f"[GPTDraw] 刷新远程预设失败：{exc}")
            return len(_remote)
        _remote.clear()
        _remote.update(presets)
        _last_refresh = now
        return len(_remote)


def clear_remote() -> None:
    global _last_refresh
    _remote.clear()
    _last_refresh = 0.0


def _local_entry(preset: GptPreset) -> PresetEntry:
    return PresetEntry(
        name=preset.name,
        prompt=preset.prompt,
        reply=preset.reply,
        image=preset.image,
        source="local",
        title=preset.name,
    )


async def get_preset(settings: Settings, name: str, *, refresh: bool = True) -> PresetEntry | None:
    normalized = normalize_preset_name(name)
    if refresh:
        await refresh_remote(settings)
    remote = _remote.get(normalized)
    if remote is not None:
        return remote
    local = await GptPreset.get_by_name(normalized)
    if local is not None:
        return _local_entry(local)
    if settings.preset_api_base_url:
        detail = await _fetch_remote_detail(settings, normalized)
        if detail is not None:
            _remote[detail.name] = detail
            return detail
    return None


async def list_presets(settings: Settings) -> list[PresetEntry]:
    await refresh_remote(settings, force=True)
    entries: dict[str, PresetEntry] = {}
    for row in await GptPreset.list_all():
        entries[row.name] = _local_entry(row)
    entries.update(_remote)
    return sorted(entries.values(), key=lambda item: item.name)


async def save_local_preset(name: str, prompt: str, created_by: str, *, reply: str = "", image: str = "") -> str:
    clean_name = validate_preset_name(normalize_preset_name(name))
    if clean_name in RESERVED_PRESET_NAMES:
        raise ParamError("这个预设名是插件保留命令名，请换一个。")
    if not prompt.strip():
        raise ParamError("提示词不能为空。")
    if await GptPreset.get_by_name(clean_name) is not None:
        raise ParamError("这个预设名已经存在；先删除再添加，或换个名字。")
    await GptPreset.upsert_preset(
        name=clean_name,
        name_key=clean_name,
        prompt=prompt.strip(),
        created_by=created_by,
        reply=reply,
        image=image,
    )
    return clean_name


async def delete_local_preset(name: str) -> str:
    clean_name = normalize_preset_name(name)
    if await GptPreset.get_by_name(clean_name) is None:
        raise ParamError(f"未找到自定义预设【{clean_name}】。")
    await GptPreset.delete_by_name(clean_name)
    return clean_name


def combine_prompt(preset: PresetEntry, extra: str) -> str:
    extra = extra.strip()
    if not extra:
        return preset.prompt
    return f"{preset.prompt} {extra}"


__all__ = [
    "ENTRY_TYPE_PRESET",
    "PresetEntry",
    "RESERVED_PRESET_NAMES",
    "clear_remote",
    "combine_prompt",
    "delete_local_preset",
    "get_preset",
    "list_presets",
    "refresh_remote",
    "remote_entries",
    "save_local_preset",
]
