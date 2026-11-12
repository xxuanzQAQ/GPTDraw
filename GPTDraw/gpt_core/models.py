"""模型列表查询、筛选与当前模型记录。

模型不再写死：用密钥调用 New API 的 /models 拉取可用模型，
用户用「gpt切换模型」选中的模型保存在数据库，生图时作为默认模型。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from gsuid_core.logger import logger

from .common import ParamError, GPTDrawError, join_api_url, token_fingerprint
from .settings import Settings
from ..gpt_database.models import GptModelChoice

ALL_KEYWORDS = frozenset({"all", "*", "全部", "所有"})
RECENT_LIST_TTL = 600.0
RECENT_LIST_LIMIT = 200
MODEL_REQUEST_TIMEOUT = 30.0

_models_cache: dict[tuple[str, str], tuple[float, list["ModelInfo"]]] = {}
_recent_lists: dict[tuple[str, str], tuple[float, list["ModelInfo"]]] = {}


class ModelListError(GPTDrawError):
    """模型列表不可用；消息可直接展示给用户。"""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    owned_by: str = ""
    created: int = 0


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = _as_text(error.get("message")) or _as_text(error.get("code"))
            if message:
                return message
        elif isinstance(error, str) and error.strip():
            return error.strip()
        for key in ("message", "detail", "msg"):
            message = _as_text(data.get(key))
            if message:
                return message
    return response.text[:200]


def parse_models(value: object) -> list[ModelInfo]:
    """兼容 /models 的 data / models 两种返回结构。"""
    items: object = None
    if isinstance(value, dict):
        items = value.get("data")
        if not isinstance(items, list):
            items = value.get("models")
    elif isinstance(value, list):
        items = value
    if not isinstance(items, list):
        return []
    models: dict[str, ModelInfo] = {}
    for item in items:
        if isinstance(item, str):
            model_id = item.strip()
            owned_by = ""
            created = 0
        elif isinstance(item, dict):
            model_id = _as_text(item.get("id") or item.get("name") or item.get("model"))
            owned_by = _as_text(item.get("owned_by") or item.get("ownedBy"))
            created_value = item.get("created")
            try:
                created = int(created_value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                created = 0
        else:
            continue
        if model_id and model_id not in models:
            models[model_id] = ModelInfo(id=model_id, owned_by=owned_by, created=created)
    return sorted(models.values(), key=lambda item: item.id.lower())


async def fetch_models(
    settings: Settings,
    api_key: str,
    *,
    force: bool = False,
    timeout: float | None = None,
) -> list[ModelInfo]:
    base_url = settings.require_api_base()
    token = str(api_key or "").strip()
    if not token:
        raise ModelListError("没有可用的 API 密钥，请先绑定密钥。")
    cache_key = (base_url, token_fingerprint(token))
    now = time.time()
    if not force and settings.model_cache_ttl > 0:
        cached = _models_cache.get(cache_key)
        if cached is not None and now - cached[0] < settings.model_cache_ttl:
            return list(cached[1])
    request_timeout = min(float(timeout or settings.request_timeout), MODEL_REQUEST_TIMEOUT)
    url = join_api_url(base_url, "/models")
    try:
        async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise ModelListError(f"查询模型列表失败：{exc}") from exc
    if response.status_code >= 400:
        raise ModelListError(f"查询模型列表失败 HTTP {response.status_code}：{_error_text(response)}")
    try:
        data: object = response.json()
    except ValueError as exc:
        raise ModelListError("模型列表返回了非 JSON 内容。") from exc
    models = parse_models(data)
    if not models:
        raise ModelListError("模型列表为空：这把密钥可能没有可用模型。")
    _models_cache[cache_key] = (now, models)
    logger.info("[GPTDraw] 从 %s 拉到 %d 个模型", url, len(models))
    return list(models)


def filter_models(models: list[ModelInfo], keyword: str) -> list[ModelInfo]:
    words = [word for word in re.split(r"[,，\s]+", str(keyword or "").strip()) if word]
    if not words or any(word.lower() in ALL_KEYWORDS for word in words):
        return list(models)
    lowered = [word.lower() for word in words]
    return [model for model in models if any(word in model.id.lower() for word in lowered)]


def match_model(models: list[ModelInfo], query: str) -> str:
    value = str(query or "").strip()
    if not value:
        raise ParamError("请填写模型序号或模型名。")
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(models):
            return models[index - 1].id
        raise ParamError(f"序号超出范围：当前列表共 {len(models)} 个模型。")
    lowered = value.lower()
    for model in models:
        if model.id.lower() == lowered:
            return model.id
    suffix = [
        model
        for model in models
        if model.id.lower().endswith(f":{lowered}") or model.id.lower().endswith(f"/{lowered}")
    ]
    if len(suffix) == 1:
        return suffix[0].id
    contains = [model for model in models if lowered in model.id.lower()]
    if len(contains) == 1:
        return contains[0].id
    if contains:
        preview = "、".join(model.id for model in contains[:6])
        raise ParamError(f"【{value}】匹配到多个模型：{preview}，请写完整模型名。")
    raise ParamError(f"没有找到模型【{value}】，先发「gpt模型列表」看看有哪些可选。")


def remember_models(bot_id: str, user_id: str, models: list[ModelInfo]) -> None:
    """记住本次展示的列表，让「gpt切换模型 3」按看到的序号生效。"""
    now = time.time()
    if len(_recent_lists) >= RECENT_LIST_LIMIT:
        for key, cached in list(_recent_lists.items()):
            if now - cached[0] >= RECENT_LIST_TTL:
                _recent_lists.pop(key, None)
        if len(_recent_lists) >= RECENT_LIST_LIMIT:
            _recent_lists.clear()
    _recent_lists[(bot_id, user_id)] = (now, list(models))


def recent_models(bot_id: str, user_id: str) -> list[ModelInfo] | None:
    cached = _recent_lists.get((bot_id, user_id))
    if cached is None:
        return None
    if time.time() - cached[0] > RECENT_LIST_TTL:
        _recent_lists.pop((bot_id, user_id), None)
        return None
    return list(cached[1])


def clear_model_cache() -> None:
    _models_cache.clear()
    _recent_lists.clear()


async def selected_model(bot_id: str, user_id: str) -> str:
    row = await GptModelChoice.get_choice(bot_id, user_id)
    return row.model if row is not None else ""


async def save_selected_model(bot_id: str, user_id: str, model: str) -> None:
    await GptModelChoice.set_choice(bot_id, user_id, model)


async def clear_selected_model(bot_id: str, user_id: str) -> bool:
    return await GptModelChoice.clear_choice(bot_id, user_id)


__all__ = [
    "ModelInfo",
    "ModelListError",
    "clear_model_cache",
    "clear_selected_model",
    "fetch_models",
    "filter_models",
    "match_model",
    "parse_models",
    "recent_models",
    "remember_models",
    "save_selected_model",
    "selected_model",
]
