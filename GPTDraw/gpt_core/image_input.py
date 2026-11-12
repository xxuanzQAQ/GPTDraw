"""参考图收集与读取。"""

from __future__ import annotations

import io
import base64
import binascii
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from gsuid_core.models import Event

MAX_IMAGE_BYTES = 20 * 1024 * 1024


def collect_image_refs(ev: Event) -> tuple[str, ...]:
    refs: list[str] = []
    for content in ev.content or []:
        if content.type in ("image", "img") and isinstance(content.data, str):
            ref = content.data.strip()
            if ref:
                refs.append(ref)
    for item in ev.image_list or []:
        if isinstance(item, str) and item.strip():
            refs.append(item.strip())
    if isinstance(ev.image, str) and ev.image.strip():
        refs.append(ev.image.strip())
    return tuple(dict.fromkeys(refs))


def decode_base64(value: str) -> bytes:
    encoded = value
    if value.startswith("data:image/"):
        _, separator, encoded = value.partition(",")
        if not separator:
            raise ValueError("图片 base64 数据格式不正确。")
    elif value.startswith("base64://"):
        encoded = value[9:]
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 base64 数据无法解码。") from exc


def validate_image(data: bytes) -> bytes:
    if not data:
        raise ValueError("图片内容为空。")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 20MB。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("无法识别这张图片。") from exc
    return data


def detect_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def to_data_url(data: bytes) -> str:
    mime = detect_mime(data)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def read_image_ref(ref: str, timeout: float = 20.0) -> bytes:
    value = ref.strip()
    if not value:
        raise ValueError("图片引用为空。")
    if value.startswith(("data:image/", "base64://")):
        return validate_image(decode_base64(value))
    if value.startswith("link://"):
        value = value[7:]
    if value.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(value)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError("下载图片失败。") from exc
        return validate_image(response.content)
    path = Path(value)
    if not path.is_file():
        raise ValueError("图片文件不存在。")
    return validate_image(path.read_bytes())


__all__ = ["collect_image_refs", "detect_mime", "read_image_ref", "to_data_url", "validate_image"]
