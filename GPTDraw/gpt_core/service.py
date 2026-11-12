"""生图主流程：参考图、提交、下载与发送。"""

from __future__ import annotations

import asyncio

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from .api import ImageApiError, submit, post_edits, download_image
from .access import AccessResolution
from .common import (
    REFERENCE_IMAGE_LIMIT,
    REFERENCE_IMAGE_INLINE_MAX_BYTES,
    GPTDrawError,
    ImageRequestPayload,
    is_public_reference_url,
)
from .params import DrawRequest
from .settings import Settings
from .image_input import to_data_url, decode_base64, read_image_ref, validate_image, collect_image_refs

_SEMAPHORE: asyncio.Semaphore | None = None
_SEMAPHORE_SIZE = 0

# 一次最多发回几张结果图；n 大于 1 时逐张发送。
MAX_RESULT_IMAGES = 4


def _semaphore(settings: Settings) -> asyncio.Semaphore:
    global _SEMAPHORE, _SEMAPHORE_SIZE
    size = max(1, settings.max_concurrent)
    if _SEMAPHORE is None or _SEMAPHORE_SIZE != size:
        _SEMAPHORE = asyncio.Semaphore(size)
        _SEMAPHORE_SIZE = size
    return _SEMAPHORE


def split_values(value: str) -> list[str]:
    return [item for item in value.replace("，", ",").replace(" ", ",").split(",") if item.strip()]


async def _reference_value(ref: str, settings: Settings) -> str | None:
    """把一条图片引用收敛成 New API 能接受的形式。"""
    value = ref.strip()
    if value.startswith("link://"):
        value = value[7:]
    if value.startswith("data:image/"):
        if len(value) > REFERENCE_IMAGE_INLINE_MAX_BYTES * 4 // 3 + 200:
            return None
        return value
    if value.startswith(("http://", "https://")):
        if settings.allow_private_reference_urls or is_public_reference_url(value):
            return value
        data = await read_image_ref(value)
        return _inline_data_url(data)
    if value.startswith("base64://"):
        try:
            return _inline_data_url(decode_base64(value))
        except ValueError:
            return None
    try:
        return _inline_data_url(await read_image_ref(value))
    except ValueError:
        return None


def _inline_data_url(data: bytes) -> str | None:
    if len(data) > REFERENCE_IMAGE_INLINE_MAX_BYTES:
        return None
    return to_data_url(data)


async def build_references(ev: Event, settings: Settings, options: dict[str, str]) -> tuple[list[str], int]:
    urls: list[str] = []
    skipped = 0
    for raw in split_values(options.get("images", "")):
        resolved = await _reference_value(raw, settings)
        if resolved is None:
            skipped += 1
        else:
            urls.append(resolved)
    for ref in collect_image_refs(ev):
        resolved = await _reference_value(ref, settings)
        if resolved is None:
            skipped += 1
        else:
            urls.append(resolved)
    unique = list(dict.fromkeys(urls))[:REFERENCE_IMAGE_LIMIT]
    return unique, skipped


def attach_references(payload: ImageRequestPayload, urls: list[str]) -> None:
    if urls:
        payload["image_urls"] = urls


async def _edit_files(urls: list[str]) -> list[tuple[str, bytes, str]]:
    files: list[tuple[str, bytes, str]] = []
    for index, url in enumerate(urls[:REFERENCE_IMAGE_LIMIT], start=1):
        if url.startswith("data:image/"):
            data = decode_base64(url)
            mime = url[5:].split(";", 1)[0] or "image/png"
        elif url.startswith(("http://", "https://")):
            data = await read_image_ref(url)
            mime = "image/png"
        else:
            continue
        files.append((f"image{index}.png", data, mime))
    return files


def submit_message(request: DrawRequest, source: str) -> str:
    message = f"🎨 已提交图片生成（模型：{request.model}），密钥来源：{source}，请稍候..."
    if request.billing_units > 1:
        message = f"{message}\n已识别 {request.resolution} 分辨率参数，扣费以 New API 渠道定价为准。"
    return message


async def inline_references(references: list[str]) -> list[str] | None:
    """把参考图抓下来转成 data URL：上游不必再回源抓图，过期的临时链接也能用。"""
    inlined: list[str] = []
    changed = False
    for ref in references:
        if ref.startswith("data:image/"):
            inlined.append(ref)
            continue
        try:
            data = await read_image_ref(ref)
        except ValueError:
            return None
        if len(data) > REFERENCE_IMAGE_INLINE_MAX_BYTES:
            return None
        inlined.append(to_data_url(data))
        changed = True
    return inlined if changed else None


async def generate(
    bot: Bot,
    ev: Event,
    request: DrawRequest,
    access: AccessResolution,
    settings: Settings,
    *,
    caption: str = "",
) -> None:
    references, skipped = await build_references(ev, settings, request.options)
    if not references and skipped:
        await bot.send("❌ 参考图不可用：只支持公网 URL、data:image 或机器人能读取的图片。")
        return
    attach_references(request.payload, references)
    await bot.send(submit_message(request, access.source))
    try:
        async with _semaphore(settings):
            try:
                urls = await submit(settings, request.payload, request.size_values, access.api_key)
            except ImageApiError as exc:
                if not references or not _is_reference_related(str(exc)):
                    raise
                urls = await _retry_with_inline_references(request, access, settings, references) or []
                if not urls:
                    files = await _edit_files(references)
                    if not files:
                        raise
                    logger.info("[GPTDraw] 改用 /images/edits multipart 提交 %d 张参考图", len(files))
                    urls = await post_edits(settings, request.payload, request.size_values, access.api_key, files)
        await _send_result(bot, urls, caption)
    except GPTDrawError as exc:
        await bot.send(f"❌ 生成失败：{_friendly_error(str(exc))}")
    except ValueError as exc:
        await bot.send(f"❌ 生成失败：{_friendly_error(str(exc))}")


async def _retry_with_inline_references(
    request: DrawRequest,
    access: AccessResolution,
    settings: Settings,
    references: list[str],
) -> list[str] | None:
    inlined = await inline_references(references)
    if not inlined:
        return None
    payload = dict(request.payload)
    payload["image_urls"] = inlined
    try:
        return await submit(settings, payload, request.size_values, access.api_key)
    except ImageApiError as exc:
        logger.info("[GPTDraw] data URL 方式提交参考图仍失败：%s", exc)
        return None


def _friendly_error(message: str) -> str:
    """把上游的英文报错补一句可操作提示。"""
    normalized = message.lower()
    if "frame" in normalized and "pixel" in normalized:
        return f"{message}\n提示：GIF 的帧数 × 尺寸超出上游预算，可减小 --size 或 --frame_count。"
    if "safety" in normalized or "moderation" in normalized:
        return f"{message}\n提示：提示词可能触发上游安全检查，换个说法再试。"
    if "reference" in normalized and "fetch" in normalized:
        return f"{message}\n提示：参考图链接上游抓不到（QQ 图片链接会过期），重发一次图片，或用 --images <公网链接>。"
    return message


def _is_reference_related(message: str) -> bool:
    normalized = message.lower()
    markers = ("image", "edit", "参考图", "image_urls", "invalid", "unsupported", "not support")
    return any(marker in normalized for marker in markers)


async def _send_result(bot: Bot, urls: list[str], caption: str) -> None:
    if not urls:
        await bot.send("❌ 生成失败：上游没有返回图片。")
        return
    segments = []
    failed: list[str] = []
    for url in urls[:MAX_RESULT_IMAGES]:
        try:
            data = validate_image(await download_image(url))
        except (GPTDrawError, ValueError) as exc:
            logger.warning("[GPTDraw] 下载生成图片失败，改为发送链接：%s", exc)
            failed.append(url)
            continue
        segments.append(MessageSegment.image(data))
    if failed:
        segments.append(MessageSegment.text("\n" + "\n".join(failed)))
    if caption:
        segments.append(MessageSegment.text(f"\n{caption}"))
    if not segments:
        await bot.send("❌ 生成失败：返回的图片都下载不下来。")
        return
    await bot.send(segments)


__all__ = [
    "attach_references",
    "build_references",
    "generate",
    "inline_references",
    "split_values",
    "submit_message",
]
