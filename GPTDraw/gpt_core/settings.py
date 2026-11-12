"""配置读取与归一化（每次调用现取，支持网页控制台热更新）。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .common import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_API_BASE_URL,
    LEGACY_IMAGE_TASK_REQUEST_PATH,
    ParamError,
    join_api_url,
    newapi_base_url,
)
from ..gpt_config.gpt_config import CONFIG


def _raw(key: str) -> object:
    return CONFIG.get_config(key).data


def _text(key: str) -> str:
    return str(_raw(key))


def _number(key: str) -> int:
    return int(_text(key))


def _flag(key: str) -> bool:
    return bool(_raw(key))


def normalize_request_mode(value: str, request_path: str, base_url: str = "") -> str:
    raw = str(value or "auto").strip().lower().replace("-", "_")
    path_hint = f"{str(base_url).rstrip('/')}/{str(request_path).lstrip('/')}".lower()
    if raw in {"chat", "chat_completion", "chat_completions", "completions"}:
        return "chat_completions"
    if raw in {
        "image",
        "images",
        "image_generation",
        "image_generations",
        "images_generation",
        "images_generations",
        "openai_image",
    }:
        return "images_generations"
    if "/chat/completions" in path_hint:
        return "chat_completions"
    return "images_generations"


def normalize_size_format(value: str) -> str:
    raw = str(value or "ratio").strip().lower().replace("-", "_")
    if raw in {"pixel", "pixels", "px", "size"}:
        return "pixels"
    if raw in {"auto"}:
        return "auto"
    if raw in {"single", "one"}:
        return "single"
    return "ratio"


def normalize_task_path(value: str) -> str:
    return str(value or "").strip() or LEGACY_IMAGE_TASK_REQUEST_PATH


def normalize_output_format(value: str) -> str:
    raw = str(value or "").strip().lower().lstrip(".")
    if raw in {"", "auto"}:
        return raw
    if raw in {"jpg", "jpe", "jpeg"}:
        return "jpeg"
    return raw


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    request_timeout: int
    max_concurrent: int
    allow_private_reference_urls: bool
    billing_request_path: str
    image_request_mode: str
    image_async_enabled: bool
    image_task_request_path: str
    poll_interval: int
    poll_timeout: int
    default_image_model: str
    model_list_filter: str
    model_cache_ttl: int
    default_image_size: str
    default_image_size_format: str
    default_image_resolution: str
    default_output_format: str
    default_quality: str
    default_background: str
    default_complexity: str
    default_frame_count: int
    default_frame_duration_ms: int
    extra_request_params: str
    preset_api_base_url: str
    preset_api_timeout: int
    preset_api_refresh_interval: int

    @property
    def chat_image_mode(self) -> bool:
        return self.image_request_mode == "chat_completions"

    def require_api_base(self) -> str:
        if not self.api_base_url.startswith(("http://", "https://")):
            raise ParamError("api_base_url 配置无效，必须以 http:// 或 https:// 开头。")
        return self.api_base_url

    def models_url(self) -> str:
        return join_api_url(self.require_api_base(), "/models")

    def task_url(self, task_id: str) -> str:
        escaped = quote(str(task_id).strip(), safe="")
        template = self.image_task_request_path
        if template.startswith(("http://", "https://")):
            raise ParamError("image_task_request_path 只能填写 New API 相对路径。")
        if "{task_id}" in template:
            path = template.replace("{task_id}", escaped)
        else:
            path = f"{template.rstrip('/')}/{escaped}"
        return join_api_url(newapi_base_url(self.api_base_url), path)


def load_settings() -> Settings:
    base_url = (_text("api_base_url") or DEFAULT_API_BASE_URL).strip().rstrip("/")
    request_path = _text("billing_request_path").strip() or "/images/generations"
    if not request_path.startswith("/"):
        request_path = f"/{request_path}"
    return Settings(
        api_base_url=base_url,
        request_timeout=max(_number("request_timeout"), 30),
        max_concurrent=max(_number("max_concurrent"), 1),
        allow_private_reference_urls=_flag("allow_private_reference_urls"),
        billing_request_path=request_path,
        image_request_mode=normalize_request_mode(_text("image_request_mode"), request_path, base_url),
        image_async_enabled=_flag("image_async_enabled"),
        image_task_request_path=normalize_task_path(_text("image_task_request_path")),
        poll_interval=max(_number("poll_interval"), 1),
        poll_timeout=max(_number("poll_timeout"), 10),
        default_image_model=_text("default_image_model").strip() or DEFAULT_IMAGE_MODEL,
        model_list_filter=_text("model_list_filter").strip() or "all",
        model_cache_ttl=max(_number("model_cache_ttl"), 0),
        default_image_size=_text("default_image_size").strip() or "1:1",
        default_image_size_format=normalize_size_format(_text("default_image_size_format")),
        default_image_resolution=_text("default_image_resolution").strip() or "1k",
        default_output_format=normalize_output_format(_text("default_output_format")),
        default_quality=_text("default_quality").strip(),
        default_background=_text("default_background").strip(),
        default_complexity=_text("default_complexity").strip(),
        default_frame_count=max(_number("default_frame_count"), 0),
        default_frame_duration_ms=max(_number("default_frame_duration_ms"), 0),
        extra_request_params=_text("extra_request_params").strip(),
        preset_api_base_url=_text("preset_api_base_url").strip().rstrip("/"),
        preset_api_timeout=max(_number("preset_api_timeout"), 1),
        preset_api_refresh_interval=max(_number("preset_api_refresh_interval"), 5),
    )


__all__ = ["Settings", "load_settings", "normalize_output_format", "normalize_request_mode", "normalize_size_format"]
