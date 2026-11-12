"""New API HTTP 客户端：请求、错误格式化、异步任务轮询与图片下载。"""

from __future__ import annotations

import re
import json
import base64
import asyncio
import binascii

import httpx

from gsuid_core.logger import logger

from .common import (
    GENERATED_IMAGE_MAX_BYTES,
    IMAGE_URL_IN_TEXT_PATTERN,
    GPTDrawError,
    ImageRequestPayload,
    dump_payload,
    join_api_url,
)
from .params import is_image_size_error
from .settings import Settings


class ImageApiError(GPTDrawError):
    """New API 返回的错误，消息可直接展示给用户。"""


def _as_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ImageApiError("New API 返回的不是 JSON 对象。")
    return {str(key): item for key, item in value.items()}


def _as_list(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _error_message(data: dict[str, object], fallback: str) -> str:
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
    return fallback


def headers(api_key: str, json_body: bool = True) -> dict[str, str]:
    token = str(api_key or "").strip()
    if not token:
        raise ImageApiError("没有可用的 API 密钥，请先使用「gpt设置密钥 <密钥>」绑定。")
    result = {"Authorization": f"Bearer {token}"}
    if json_body:
        result["Content-Type"] = "application/json"
    return result


def _parse_payload(response: httpx.Response) -> dict[str, object]:
    text = response.text
    try:
        parsed: object = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        if response.status_code >= 400:
            raise ImageApiError(f"New API 请求失败 HTTP {response.status_code}: {text[:300]}")
        raise ImageApiError(f"New API 返回了非 JSON 内容：{text[:300]}")
    data = _as_object(parsed)
    if response.status_code >= 400:
        raise ImageApiError(f"New API 请求失败 HTTP {response.status_code}: {_error_message(data, text[:300])}")
    return data


async def post_json(
    settings: Settings,
    path: str,
    payload: ImageRequestPayload,
    api_key: str,
    *,
    timeout: float | None = None,
) -> dict[str, object]:
    url = join_api_url(settings.require_api_base(), path)
    logger.info("[GPTDraw] HTTP POST %s body: %s", url, dump_payload(payload))
    request_timeout = timeout if timeout is not None else float(settings.request_timeout)
    try:
        async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
            response = await client.post(url, json=payload, headers=headers(api_key))
    except httpx.TimeoutException as exc:
        raise ImageApiError(
            f"请求超时（{int(request_timeout)}s）。如果 New API 仍在生成，"
            "可以调大 request_timeout，或稍后用同一提示词重试。"
        ) from exc
    except httpx.HTTPError as exc:
        raise ImageApiError(f"请求 New API 失败：{exc}") from exc
    return _parse_payload(response)


async def get_json(settings: Settings, url: str, api_key: str, *, timeout: float | None = None) -> dict[str, object]:
    request_timeout = timeout if timeout is not None else float(settings.request_timeout)
    try:
        async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers(api_key, json_body=False))
    except httpx.TimeoutException as exc:
        raise ImageApiError("查询 New API 图片任务超时。") from exc
    except httpx.HTTPError as exc:
        raise ImageApiError(f"查询 New API 图片任务失败：{exc}") from exc
    return _parse_payload(response)


def _first_data_item(data: dict[str, object]) -> dict[str, object]:
    payload = data.get("data")
    if isinstance(payload, dict):
        return _as_object(payload)
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            return _as_object(first)
    return data


def extract_urls(value: object) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("http://", "https://", "asset://", "data:image/")):
            urls.append(text)
        for match in IMAGE_URL_IN_TEXT_PATTERN.finditer(text):
            url = re.sub(r"\s+", "", match.group(0)).rstrip(".,，。;；")
            if url.startswith(("http://", "https://", "data:image/")):
                urls.append(url)
    elif isinstance(value, dict):
        encoded = value.get("b64_json")
        if isinstance(encoded, str) and encoded.strip():
            mime = _as_text(value.get("mime_type")) or "image/png"
            urls.append(f"data:{mime};base64,{encoded.strip()}")
        for key in ("url", "image_url", "asset_url", "download_url"):
            item = value.get(key)
            if isinstance(item, str) and item.startswith(("http://", "https://", "asset://", "data:image/")):
                urls.append(item)
        for item in value.values():
            urls.extend(extract_urls(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            urls.extend(extract_urls(item))
    return list(dict.fromkeys(urls))


def _task_id(data: dict[str, object]) -> str:
    item = _first_data_item(data)
    for source in (item, data):
        for key in ("task_id", "id"):
            value = _as_text(source.get(key))
            if value:
                return value
    return ""


def _task_status(data: dict[str, object]) -> str:
    item = _first_data_item(data)
    return _as_text(item.get("status")).lower()


def _task_error(data: dict[str, object]) -> str:
    item = _first_data_item(data)
    error = item.get("error") or data.get("error")
    if isinstance(error, dict):
        return _as_text(error.get("message")) or _as_text(error.get("code")) or "未知错误"
    if isinstance(error, str) and error.strip():
        return error.strip()
    return _as_text(item.get("message")) or "未知错误"


async def poll_task(settings: Settings, task_id: str, api_key: str) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + settings.poll_timeout
    last_data: dict[str, object] = {}
    url = settings.task_url(task_id)
    while asyncio.get_running_loop().time() < deadline:
        data = await get_json(settings, url, api_key)
        last_data = data
        if _task_status(data) in {"completed", "succeeded", "success", "failed", "cancelled", "canceled"}:
            return data
        await asyncio.sleep(settings.poll_interval)
    return last_data


async def resolve_result(settings: Settings, data: dict[str, object], api_key: str) -> list[str]:
    urls = extract_urls(data)
    task_id = _task_id(data)
    if task_id and not urls:
        final = await poll_task(settings, task_id, api_key)
        urls = extract_urls(final)
        if not urls:
            status = _task_status(final)
            if status in {"failed", "cancelled", "canceled"}:
                raise ImageApiError(f"图片任务失败：{_task_error(final)}")
            raise ImageApiError(f"图片任务未完成或未返回图片：{dump_payload(final, 400)}")
    if not urls:
        raise ImageApiError(f"未解析到图片链接：{dump_payload(data, 400)}")
    return urls


def _chat_payload(payload: ImageRequestPayload) -> dict[str, object]:
    prompt = str(payload.get("prompt") or "").strip()
    details: list[str] = []
    size = str(payload.get("size") or "").strip()
    resolution = str(payload.get("resolution") or "").strip()
    quality = str(payload.get("quality") or "").strip()
    if size:
        details.append(f"尺寸/画幅：{size}")
    if resolution:
        details.append(f"分辨率：{resolution}")
    if quality:
        details.append(f"质量：{quality}")
    if details:
        prompt = f"生成参数：{'，'.join(details)}\n\n{prompt}"
    references = payload.get("image_urls") or payload.get("images") or []
    if isinstance(references, list) and references:
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for reference in references:
            content.append({"type": "image_url", "image_url": {"url": reference}})
        return {"model": payload.get("model"), "messages": [{"role": "user", "content": content}], "stream": False}
    return {"model": payload.get("model"), "messages": [{"role": "user", "content": prompt}], "stream": False}


async def submit(
    settings: Settings,
    payload: ImageRequestPayload,
    size_values: list[str],
    api_key: str,
) -> list[str]:
    if settings.chat_image_mode:
        return await post_chat(settings, payload, api_key)

    last_error: ImageApiError | None = None
    for size in size_values or [str(payload.get("size") or "")]:
        attempt = _with_size(payload, size)
        try:
            data = await post_json(settings, settings.billing_request_path, attempt, api_key)
            return await resolve_result(settings, data, api_key)
        except ImageApiError as exc:
            if not is_image_size_error(str(exc)):
                raise
            last_error = exc
            logger.warning("[GPTDraw] size=%s 被上游拒绝，尝试其他格式：%s", size, exc)
    if last_error is not None:
        raise last_error
    raise ImageApiError("图片生成失败：未找到可用的 size 格式。")


def _with_size(payload: ImageRequestPayload, size: str) -> ImageRequestPayload:
    updated: ImageRequestPayload = {}
    updated.update(payload)
    updated["size"] = size
    return updated


async def post_chat(settings: Settings, payload: ImageRequestPayload, api_key: str) -> list[str]:
    chat = _chat_payload(payload)
    url = join_api_url(settings.require_api_base(), settings.billing_request_path)
    logger.info("[GPTDraw] HTTP POST %s chat body: %s", url, dump_payload(chat))
    try:
        async with httpx.AsyncClient(timeout=float(settings.request_timeout), follow_redirects=True) as client:
            response = await client.post(url, json=chat, headers=headers(api_key))
    except httpx.HTTPError as exc:
        raise ImageApiError(f"请求 New API 失败：{exc}") from exc
    data = _parse_payload(response)
    return extract_urls(data)


def edit_path(settings: Settings) -> str:
    path = settings.billing_request_path.strip() or "/images/generations"
    normalized = "/" + path.lstrip("/")
    for suffix in ("/images/generations", "/v1/images/generations"):
        if normalized.rstrip("/").endswith(suffix):
            return normalized.rstrip("/")[: -len("/generations")] + "/edits"
    return "/images/edits"


async def post_edits(
    settings: Settings,
    payload: ImageRequestPayload,
    size_values: list[str],
    api_key: str,
    references: list[tuple[str, bytes, str]],
) -> list[str]:
    """multipart /images/edits 兜底：参考图以文件形式上传。"""
    url = join_api_url(settings.require_api_base(), edit_path(settings))
    last_error: ImageApiError | None = None
    for size in size_values or [""]:
        form: dict[str, str] = {}
        for key in ("model", "prompt", "resolution", "quality", "output_format", "background", "moderation"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                form[key] = value
        if size:
            form["size"] = size
        if payload.get("output_compression") is not None:
            form["output_compression"] = str(payload.get("output_compression"))
        files = [("image", (filename, data, mime)) for filename, data, mime in references]
        try:
            async with httpx.AsyncClient(timeout=float(settings.request_timeout), follow_redirects=True) as client:
                response = await client.post(url, data=form, files=files, headers=headers(api_key, json_body=False))
            return await resolve_result(settings, _parse_payload(response), api_key)
        except ImageApiError as exc:
            if not is_image_size_error(str(exc)):
                raise
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ImageApiError("图片 edits 重试失败。")


async def download_image(url: str) -> bytes:
    if url.startswith("data:image/"):
        _, separator, encoded = url.partition(",")
        if not separator:
            raise ImageApiError("生成结果不是有效的 base64 图片。")
        try:
            data = base64.b64decode("".join(encoded.split()), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageApiError("生成图片 base64 解码失败。") from exc
        if len(data) > GENERATED_IMAGE_MAX_BYTES:
            raise ImageApiError("生成图片超过 50MB，已停止发送。")
        return data
    if not url.startswith(("http://", "https://")):
        raise ImageApiError("生成结果不是可下载的图片 URL。")
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ImageApiError(f"下载生成图片失败：{exc}") from exc
    if len(response.content) > GENERATED_IMAGE_MAX_BYTES:
        raise ImageApiError("生成图片超过 50MB，已停止发送。")
    return response.content


__all__ = [
    "ImageApiError",
    "download_image",
    "extract_urls",
    "post_chat",
    "post_edits",
    "poll_task",
    "resolve_result",
    "submit",
]
