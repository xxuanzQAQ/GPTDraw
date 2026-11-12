"""共享常量、错误类型与小工具。"""

from __future__ import annotations

import re
import json
import hashlib
from typing import TypedDict
from urllib.parse import urlparse

DEFAULT_IMAGE_MODEL = "gpt-image-2.6-sunburst"
"""配置里没有填默认模型时的兜底模型；实际用哪个模型由「gpt切换模型」决定。"""

DEFAULT_API_BASE_URL = "http://localhost:3000/v1"
LEGACY_IMAGE_TASK_REQUEST_PATH = "/v1/images/generations/{task_id}"

GENERATED_IMAGE_MAX_BYTES = 50 * 1024 * 1024
REFERENCE_IMAGE_INLINE_MAX_BYTES = 12 * 1024 * 1024
REFERENCE_IMAGE_LIMIT = 16

IMAGE_K_RESOLUTION_PATTERN = re.compile(r"(?<![0-9A-Za-z])([124])\s*[kKｋＫ](?![0-9A-Za-z])")
IMAGE_2048_PATTERN = re.compile(r"(?<!\d)2048\s*[xX×*]\s*2048(?!\d)")
IMAGE_SIZE_PATTERN = re.compile(r"^\s*(\d{2,5})\s*[xX×*]\s*(\d{2,5})\s*$")
IMAGE_INLINE_SIZE_PATTERN = re.compile(r"(?<!\d)(\d{3,5})\s*[xX×*]\s*(\d{3,5})(?!\d)")
IMAGE_ASPECT_RATIO_PATTERN = re.compile(r"^\s*(\d{1,3})\s*:\s*(\d{1,3})\s*$")
IMAGE_SINGLE_SIZE_PATTERN = re.compile(r"^\s*(\d{3,5})\s*$")
IMAGE_INLINE_RATIO_PATTERN = re.compile(r"(?<![\d:])(\d{1,2})\s*:\s*(\d{1,2})(?![\d:])")
IMAGE_URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s<>'\")]+")
LEADING_AT_PLACEHOLDER_PATTERN = re.compile(r"^(?:\[At:[^\]\r\n]+\]\s*)+")
LEADING_CQ_AT_PATTERN = re.compile(r"^(?:@.+?\([0-9]+\)\s*)+")
SAFE_ID_PATTERN = re.compile(r"[^0-9A-Za-z_-]+")
PRESET_NAME_PATTERN = re.compile(r"^[^\s/\\#]{1,32}$")

IMAGE_RESOLUTION_SHORT_SIDE = {"1k": 1024, "2k": 2048, "4k": 4096}


ImageRequestPayload = TypedDict(
    "ImageRequestPayload",
    {
        "model": str,
        "prompt": str,
        "n": int,
        "size": str,
        "resolution": str,
        "version": str,
        "quality": str,
        "complexity": str,
        "frame_count": int,
        "frame_duration_ms": int,
        "output_format": str,
        "output_compression": int,
        "background": str,
        "moderation": str,
        "image_urls": list[str],
        "images": list[str],
        "mask_url": str,
        "mask": str,
        "async": bool,
        "response_format": str,
    },
    total=False,
)


class GPTDrawError(RuntimeError):
    """可以直接展示给用户的错误。"""


class ParamError(ValueError):
    """用户填写的参数不合法。"""


def normalize_invocation_text(text: str) -> str:
    """移除群聊引用消息自动附带的前置 @，保留真正的调用文本。"""
    normalized = str(text or "").strip()
    while normalized:
        stripped = LEADING_AT_PLACEHOLDER_PATTERN.sub("", normalized, count=1)
        stripped = LEADING_CQ_AT_PATTERN.sub("", stripped, count=1).strip()
        if stripped == normalized:
            break
        normalized = stripped
    return normalized


def mask_key(token: str) -> str:
    value = str(token or "").strip()
    if value.startswith("sk-"):
        value = value[3:]
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def normalize_preset_name(value: object) -> str:
    name = str(value or "").strip().lstrip("/#").strip()
    return name[:32]


def validate_preset_name(name: str) -> str:
    if not name:
        raise ParamError("预设名不能为空。")
    if not PRESET_NAME_PATTERN.fullmatch(name):
        raise ParamError("预设名不能带空格、斜杠或反斜杠，长度 1-32。")
    return name


def newapi_base_url(api_base_url: str) -> str:
    """把 .../v1 之类的 API 根地址收敛成站点根地址。"""
    value = str(api_base_url or "").strip().rstrip("/")
    if value.endswith("/v1"):
        value = value[:-3].rstrip("/")
    return value


def join_api_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    suffix = str(path or "").strip()
    if not suffix:
        return base
    return f"{base}/{suffix.lstrip('/')}"


def is_public_reference_url(value: str) -> bool:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
        return False
    return True


def safe_payload_for_log(payload: object) -> object:
    """日志里只保留结构，不打印 base64 大字段。"""
    if isinstance(payload, dict):
        cleaned: dict[str, object] = {}
        for key, value in payload.items():
            cleaned[str(key)] = safe_payload_for_log(value)
        return cleaned
    if isinstance(payload, list):
        return [safe_payload_for_log(item) for item in payload]
    if isinstance(payload, str) and len(payload) > 240:
        return f"{payload[:120]}... <{len(payload)} chars>"
    return payload


def dump_payload(payload: object, limit: int = 2000) -> str:
    text = json.dumps(safe_payload_for_log(payload), ensure_ascii=False)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... <{len(text) - limit} chars truncated>"


def safe_id(value: str) -> str:
    cleaned = SAFE_ID_PATTERN.sub("_", str(value or ""))[:64]
    return cleaned or "unknown"


__all__ = [
    "DEFAULT_API_BASE_URL",
    "DEFAULT_IMAGE_MODEL",
    "GENERATED_IMAGE_MAX_BYTES",
    "GPTDrawError",
    "IMAGE_2048_PATTERN",
    "IMAGE_ASPECT_RATIO_PATTERN",
    "IMAGE_INLINE_RATIO_PATTERN",
    "IMAGE_INLINE_SIZE_PATTERN",
    "IMAGE_K_RESOLUTION_PATTERN",
    "IMAGE_RESOLUTION_SHORT_SIDE",
    "IMAGE_SINGLE_SIZE_PATTERN",
    "IMAGE_SIZE_PATTERN",
    "IMAGE_URL_IN_TEXT_PATTERN",
    "ImageRequestPayload",
    "LEGACY_IMAGE_TASK_REQUEST_PATH",
    "ParamError",
    "REFERENCE_IMAGE_INLINE_MAX_BYTES",
    "REFERENCE_IMAGE_LIMIT",
    "dump_payload",
    "is_public_reference_url",
    "join_api_url",
    "mask_key",
    "newapi_base_url",
    "normalize_invocation_text",
    "normalize_preset_name",
    "safe_id",
    "token_fingerprint",
    "validate_preset_name",
]
