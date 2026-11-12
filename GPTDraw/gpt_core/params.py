"""生图参数解析：尺寸、分辨率、内联选项与请求体构造。

模型不再固定：由「gpt切换模型」选择的模型（或 --model）写进请求体，
分辨率只用来把比例换算成像素尺寸，不再决定模型。
"""

from __future__ import annotations

import re
import json
import math
from typing import cast
from dataclasses import field, dataclass

from .common import (
    IMAGE_2048_PATTERN,
    IMAGE_SIZE_PATTERN,
    DEFAULT_IMAGE_MODEL,
    IMAGE_INLINE_SIZE_PATTERN,
    IMAGE_SINGLE_SIZE_PATTERN,
    IMAGE_ASPECT_RATIO_PATTERN,
    IMAGE_K_RESOLUTION_PATTERN,
    IMAGE_RESOLUTION_SHORT_SIDE,
    ParamError,
    ImageRequestPayload,
)
from .settings import Settings, normalize_output_format

RESOLUTION_BILLING_UNITS = {"2k": 2, "4k": 3}

RATIO_PIXEL_SIZES: dict[str, dict[str, str]] = {
    "1k": {
        "1:1": "1024x1024",
        "3:2": "1536x1024",
        "2:3": "1024x1536",
        "4:3": "1024x768",
        "3:4": "768x1024",
        "5:4": "1280x1024",
        "4:5": "1024x1280",
        "16:9": "1536x864",
        "9:16": "864x1536",
        "2:1": "2048x1024",
        "1:2": "1024x2048",
        "3:1": "1536x512",
        "1:3": "512x1536",
        "21:9": "2016x864",
        "9:21": "864x2016",
    },
    "2k": {
        "1:1": "2048x2048",
        "3:2": "2048x1360",
        "2:3": "1360x2048",
        "4:3": "2048x1536",
        "3:4": "1536x2048",
        "5:4": "2560x2048",
        "4:5": "2048x2560",
        "16:9": "2048x1152",
        "9:16": "1152x2048",
        "2:1": "2688x1344",
        "1:2": "1344x2688",
        "3:1": "3072x1024",
        "1:3": "1024x3072",
        "21:9": "2688x1152",
        "9:21": "1152x2688",
    },
    "4k": {
        "1:1": "2880x2880",
        "3:2": "3520x2336",
        "2:3": "2336x3520",
        "4:3": "3312x2480",
        "3:4": "2480x3312",
        "5:4": "3216x2576",
        "4:5": "2576x3216",
        "16:9": "3840x2160",
        "9:16": "2160x3840",
        "2:1": "3840x1920",
        "1:2": "1920x3840",
        "3:1": "3840x1280",
        "1:3": "1280x3840",
        "21:9": "3840x1648",
        "9:21": "1648x3840",
    },
}

# 常见画幅：内联识别「16:9」这类写法时使用，不再限制提交值。
API_RATIO_SIZES = frozenset({"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"})
SUPPORTED_RATIOS = tuple(sorted(API_RATIO_SIZES, key=len, reverse=True))

_RATIO_ALTERNATION = "|".join(re.escape(ratio) for ratio in sorted(SUPPORTED_RATIOS, key=len, reverse=True))
_BARE_RATIO_PATTERN = re.compile(rf"(?<![\d:])({_RATIO_ALTERNATION})(?![\d:])")
_PIXEL_SIZE_TEXT = r"\d{3,5}\s*[xX×*]\s*\d{3,5}"
_INLINE_SIZE_VALUE = rf"(?:auto|{_PIXEL_SIZE_TEXT}|{_RATIO_ALTERNATION}|\d{{3,5}})"
_LABELED_SIZE_PATTERN = re.compile(
    rf"(?i)(?:\bsize\b|尺寸|比例|画幅|\baspect\b|\bratio\b)\s*[:=：]?\s*({_INLINE_SIZE_VALUE})"
)
_LABELED_RESOLUTION_PATTERN = re.compile(
    r"(?i)(?:\bresolution\b|\bres\b|分辨率|清晰度|画质)\s*[:=：]?\s*([124]\s*[kKｋＫ])"
)
_MODEL_NAME_PATTERN = re.compile(r"^[0-9A-Za-z._:/@+-]{1,120}$")
_FRAME_COUNT_MAX = 60
_FRAME_DURATION_MAX = 2000
_N_MAX = 10

_TRUE_TEXT = frozenset({"1", "true", "yes", "on", "是", "开"})


@dataclass(frozen=True)
class DrawRequest:
    """一次生图请求解析后的结果。"""

    prompt: str
    payload: ImageRequestPayload
    size_values: list[str]
    resolution: str
    billing_units: int
    options: dict[str, str] = field(default_factory=dict)
    model: str = ""


def parse_options(text: str) -> tuple[dict[str, str], str]:
    options: dict[str, str] = {}
    tokens = str(text or "").split()
    prompt_parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--"):
            key = token[2:].strip().replace("-", "_")
            if not key:
                index += 1
                continue
            if "=" in key:
                key, value = key.split("=", 1)
                options[key] = value.strip()
            elif index + 1 < len(tokens) and not tokens[index + 1].startswith("--"):
                options[key] = tokens[index + 1].strip()
                index += 1
            else:
                options[key] = "true"
        else:
            prompt_parts.append(token)
        index += 1
    return options, " ".join(prompt_parts).strip()


def option_value(options: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = options.get(key)
        if value:
            return value
    return ""


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE_TEXT


def normalize_image_resolution(value: str | None) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).lower()
    return normalized.replace("ｋ", "k").replace("Ｋ", "k")


def normalize_size_format(value: str | None) -> str:
    normalized = re.sub(r"[\s_-]+", "", str(value or "auto")).lower()
    aliases = {
        "auto": "auto",
        "raw": "auto",
        "passthrough": "auto",
        "ratio": "ratio",
        "aspect": "ratio",
        "aspectratio": "ratio",
        "pixel": "pixels",
        "pixels": "pixels",
        "widthheight": "pixels",
        "widthxheight": "pixels",
        "single": "single",
        "shortside": "single",
        "square": "single",
    }
    return aliases.get(normalized, "auto")


def resolve_model_name(value: str | None) -> str:
    """校验并归一模型名；模型由每个会话自己选择。"""
    name = str(value or "").strip()
    if not name:
        raise ParamError("模型名不能为空，用 gpt模型列表 查看可用模型。")
    if not _MODEL_NAME_PATTERN.fullmatch(name):
        raise ParamError("模型名只能包含字母、数字和 . _ : / @ + -，长度 1-120。")
    return name


def parse_extra_params(text: str) -> dict[str, object]:
    """解析附加请求参数：k=v,k2=v2 或 JSON 对象。"""
    raw = str(text or "").strip()
    if not raw:
        return {}
    parsed: dict[str, object] = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParamError("附加请求参数不是合法 JSON。") from exc
        if not isinstance(data, dict):
            raise ParamError("附加请求参数必须是 JSON 对象。")
        for key, value in data.items():
            name = str(key).strip()
            if name:
                parsed[name] = value
        return parsed
    for chunk in re.split(r"[,;\n]+", raw):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, separator, value = chunk.partition("=")
        if not separator:
            key, separator, value = chunk.partition(":")
        if not separator:
            raise ParamError("附加请求参数要写成 k=v，多个用逗号分隔，或直接写 JSON 对象。")
        name = key.strip().lstrip("-")
        if not name:
            continue
        parsed[name] = _coerce_scalar(value.strip())
    return parsed


def _coerce_scalar(value: str) -> object:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _normalize_inline_size_value(value: str) -> str:
    raw_value = str(value or "").strip()
    if raw_value.lower() == "auto":
        return "auto"
    pixel_match = IMAGE_SIZE_PATTERN.fullmatch(raw_value)
    if pixel_match:
        return f"{int(pixel_match.group(1))}x{int(pixel_match.group(2))}"
    ratio_match = IMAGE_ASPECT_RATIO_PATTERN.fullmatch(raw_value)
    if ratio_match:
        return f"{int(ratio_match.group(1))}:{int(ratio_match.group(2))}"
    single_match = IMAGE_SINGLE_SIZE_PATTERN.fullmatch(raw_value)
    if single_match:
        return str(int(single_match.group(1)))
    return ""


def find_inline_size_option(text: str) -> tuple[str, list[tuple[int, int]]]:
    for match in _LABELED_SIZE_PATTERN.finditer(text):
        value = _normalize_inline_size_value(match.group(1))
        if value:
            return value, [match.span()]
    for match in _BARE_RATIO_PATTERN.finditer(text):
        value = _normalize_inline_size_value(match.group(1))
        if value:
            return value, [match.span()]
    for match in IMAGE_INLINE_SIZE_PATTERN.finditer(text):
        value = _normalize_inline_size_value(match.group(0))
        if value:
            return value, [match.span()]
    return "", []


def find_inline_resolution_option(text: str) -> tuple[str, list[tuple[int, int]]]:
    for match in _LABELED_RESOLUTION_PATTERN.finditer(text):
        value = normalize_image_resolution(match.group(1))
        if value in IMAGE_RESOLUTION_SHORT_SIDE:
            return value, [match.span()]
    for match in IMAGE_K_RESOLUTION_PATTERN.finditer(text):
        value = normalize_image_resolution(match.group(0))
        if value in IMAGE_RESOLUTION_SHORT_SIDE:
            return value, [match.span()]
    return "", []


def remove_text_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text.strip()
    parts: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    cleaned = re.sub(r"\s+", " ", "".join(parts))
    # 参数被剥离后常留下 -- 或空逗号，顺手收掉。
    cleaned = re.sub(r"(^|\s)-{1,2}(?=\s|$)", " ", cleaned)
    return cleaned.strip(" ,，;；。-")


def image_size_candidates(size: str | None, resolution: str | None) -> dict[str, str]:
    candidates: dict[str, str] = {}
    raw_size = str(size or "").strip()
    pixel_match = IMAGE_SIZE_PATTERN.fullmatch(raw_size)
    if pixel_match:
        width = int(pixel_match.group(1))
        height = int(pixel_match.group(2))
        pixels = f"{width}x{height}"
        divisor = math.gcd(width, height)
        candidates["raw"] = pixels
        candidates["pixels"] = pixels
        candidates["single"] = str(min(width, height))
        candidates["ratio"] = f"{width // divisor}:{height // divisor}"
        return candidates

    ratio_match = IMAGE_ASPECT_RATIO_PATTERN.fullmatch(raw_size)
    if ratio_match:
        width_ratio = int(ratio_match.group(1))
        height_ratio = int(ratio_match.group(2))
        if width_ratio <= 0 or height_ratio <= 0:
            return {"raw": raw_size} if raw_size else {}
        ratio = f"{width_ratio}:{height_ratio}"
        normalized_resolution = normalize_image_resolution(resolution) or "1k"
        mapped_pixels = RATIO_PIXEL_SIZES.get(normalized_resolution, {}).get(ratio)
        if mapped_pixels:
            width_text, height_text = mapped_pixels.split("x", 1)
            width = int(width_text)
            height = int(height_text)
        else:
            short_side = image_resolution_short_side(resolution)
            if width_ratio >= height_ratio:
                width = _ceil_to_multiple(short_side * width_ratio / height_ratio, 8)
                height = short_side
            else:
                width = short_side
                height = _ceil_to_multiple(short_side * height_ratio / width_ratio, 8)
        candidates["raw"] = ratio
        candidates["ratio"] = ratio
        candidates["pixels"] = f"{width}x{height}"
        candidates["single"] = str(min(width, height))
        return candidates

    single_match = IMAGE_SINGLE_SIZE_PATTERN.fullmatch(raw_size)
    if single_match:
        single = str(int(single_match.group(1)))
        candidates["raw"] = single
        candidates["single"] = single
        candidates["pixels"] = f"{single}x{single}"
        candidates["ratio"] = "1:1"
        return candidates

    return {"raw": raw_size} if raw_size else {}


def image_resolution_short_side(resolution: str | None) -> int:
    normalized = normalize_image_resolution(resolution)
    if normalized in IMAGE_RESOLUTION_SHORT_SIDE:
        return IMAGE_RESOLUTION_SHORT_SIDE[normalized]
    match = re.fullmatch(r"(\d{3,5})", normalized)
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"(\d)\s*k", normalized)
    if match:
        return int(match.group(1)) * 1024
    return IMAGE_RESOLUTION_SHORT_SIDE["1k"]


def _ceil_to_multiple(value: float, multiple: int) -> int:
    return math.ceil(value / multiple) * multiple


def normalize_image_size(size: str | None, resolution: str | None, size_format: str | None) -> str:
    candidates = image_size_candidates(size, resolution)
    normalized_format = normalize_size_format(size_format)
    if normalized_format == "auto":
        return candidates.get("raw", "")
    return candidates.get(normalized_format) or candidates.get("raw", "")


def normalize_submitted_size(size: str) -> str:
    """把 size 收敛成比例、像素、单边像素或 auto；不合法直接报错。"""
    value = str(size or "").strip().lower()
    if not value or value == "auto":
        return "auto"
    if IMAGE_ASPECT_RATIO_PATTERN.fullmatch(value):
        return value
    pixel_match = IMAGE_SIZE_PATTERN.fullmatch(value)
    if pixel_match:
        return f"{int(pixel_match.group(1))}x{int(pixel_match.group(2))}"
    single_match = IMAGE_SINGLE_SIZE_PATTERN.fullmatch(value)
    if single_match:
        return str(int(single_match.group(1)))
    raise ParamError("size 只支持比例（1:1）、像素（1024x1024）、单边像素或 auto。")


def billing_size_values(size: str | None, resolution: str | None) -> list[str]:
    """上游拒绝时按 [原值, auto] 重试。"""
    value = str(size or "").strip() or "auto"
    values = [value]
    if value != "auto":
        values.append("auto")
    return list(dict.fromkeys(values))


def is_image_size_error(message: str) -> bool:
    normalized = message.lower()
    mentions_size = "size" in normalized or any(marker in message for marker in ("尺寸", "画幅", "比例"))
    if not mentions_size:
        return False
    return any(
        marker in normalized
        for marker in (
            "invalid",
            "expected",
            "unsupported",
            "not support",
            "not allowed",
            "not valid",
            "only support",
            "must",
        )
    )


def apply_inline_options(options: dict[str, str], prompt: str, settings: Settings) -> tuple[dict[str, str], str]:
    resolved = dict(options)
    spans: list[tuple[int, int]] = []
    if not option_value(resolved, "size", "image_size"):
        size, size_spans = find_inline_size_option(prompt)
        if size:
            resolved["size"] = size
            spans.extend(size_spans)
    if not option_value(resolved, "resolution", "res", "image_resolution"):
        resolution, resolution_spans = find_inline_resolution_option(prompt)
        if resolution:
            resolved["resolution"] = resolution
            spans.extend(resolution_spans)
    return resolved, remove_text_spans(prompt, spans)


def infer_resolution_from_size(size: str | None) -> str:
    candidates = image_size_candidates(size, None)
    pixels = candidates.get("pixels") or candidates.get("raw", "")
    pixel_match = IMAGE_SIZE_PATTERN.fullmatch(pixels)
    if not pixel_match:
        return ""
    normalized_pixels = f"{int(pixel_match.group(1))}x{int(pixel_match.group(2))}"
    for resolution, ratio_sizes in RATIO_PIXEL_SIZES.items():
        if normalized_pixels in ratio_sizes.values():
            return resolution
    return ""


def resolve_resolution(options: dict[str, str], hint_text: str, settings: Settings) -> str:
    explicit = option_value(options, "resolution", "res", "image_resolution")
    if explicit:
        return normalize_image_resolution(explicit)
    hinted = _find_resolution_request(hint_text)
    if hinted:
        return hinted
    return normalize_image_resolution(settings.default_image_resolution)


def _find_resolution_request(text: str) -> str:
    for match in IMAGE_K_RESOLUTION_PATTERN.finditer(text):
        value = normalize_image_resolution(match.group(0))
        if value in IMAGE_RESOLUTION_SHORT_SIDE:
            return value
    if IMAGE_2048_PATTERN.search(text):
        return "2k"
    return ""


def _int_option(
    options: dict[str, str],
    keys: tuple[str, ...],
    default: int,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = option_value(options, *keys)
    if not raw:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ParamError(f"{label} 必须是整数。") from exc
    if value < minimum or value > maximum:
        raise ParamError(f"{label} 必须在 {minimum} 到 {maximum} 之间。")
    return value


def build_request(
    options: dict[str, str],
    prompt: str,
    hint_text: str,
    settings: Settings,
    *,
    default_model: str = "",
) -> DrawRequest:
    text = str(prompt or "").strip()
    if not text:
        raise ParamError("提示词不能为空。")

    resolution = resolve_resolution(options, hint_text, settings)
    model = resolve_model_name(
        option_value(options, "model", "model_name")
        or default_model
        or settings.default_image_model
        or DEFAULT_IMAGE_MODEL
    )

    raw_size = option_value(options, "size", "image_size") or settings.default_image_size
    size_format = normalize_size_format(
        option_value(options, "size_format", "image_size_format") or settings.default_image_size_format
    )
    size = normalize_submitted_size(normalize_image_size(raw_size, resolution, size_format) or "auto")

    output_format = normalize_output_format(
        option_value(options, "output_format", "format", "output") or settings.default_output_format
    )
    if _truthy(option_value(options, "gif", "animated")):
        output_format = "gif"

    # GIF 的帧数会乘上帧尺寸：默认用 auto（上游给 512x512 左右），否则很容易超出像素预算。
    if output_format == "gif" and not option_value(options, "size", "image_size"):
        size = "auto"

    body: dict[str, object] = {
        "model": model,
        "prompt": text,
        "size": size,
        "n": _int_option(options, ("n",), 1, "n", minimum=1, maximum=_N_MAX),
    }

    # 分辨率和版本只在用户明确写了 2k / --version 时才发；默认请求保持最简。
    resolution_option = option_value(options, "resolution", "res", "image_resolution")
    if resolution_option:
        if resolution not in {"1k", "2k", "4k"}:
            raise ParamError("resolution 只支持 1k / 2k / 4k。")
        body["resolution"] = resolution.upper()
    version = str(option_value(options, "version")).strip().lower()
    if version:
        if version not in {"flare", "sunburst"}:
            raise ParamError("version 只支持 flare 或 sunburst。")
        body["version"] = version

    if output_format:
        body["output_format"] = output_format

    quality = option_value(options, "quality") or settings.default_quality
    if quality:
        body["quality"] = quality
    background = option_value(options, "background") or settings.default_background
    if background:
        body["background"] = background
    moderation = option_value(options, "moderation")
    if moderation:
        body["moderation"] = moderation

    if output_format == "gif":
        complexity = option_value(options, "complexity") or settings.default_complexity
        if complexity:
            body["complexity"] = complexity
        frame_count = _int_option(
            options,
            ("frame_count", "frames", "frame"),
            settings.default_frame_count,
            "frame_count",
            minimum=0,
            maximum=_FRAME_COUNT_MAX,
        )
        if frame_count:
            body["frame_count"] = frame_count
        frame_duration = _int_option(
            options,
            ("frame_duration_ms", "frame_duration", "frame_delay", "frame_ms"),
            settings.default_frame_duration_ms,
            "frame_duration_ms",
            minimum=0,
            maximum=_FRAME_DURATION_MAX,
        )
        if frame_duration:
            body["frame_duration_ms"] = frame_duration

    output_compression = option_value(options, "output_compression", "compression")
    if output_compression:
        try:
            compression = int(output_compression)
        except ValueError as exc:
            raise ParamError("output_compression 必须是 0 到 100 的整数。") from exc
        if compression < 0 or compression > 100:
            raise ParamError("output_compression 必须是 0 到 100 的整数。")
        body["output_compression"] = compression

    response_format = option_value(options, "response_format")
    if response_format:
        body["response_format"] = response_format
    mask_url = option_value(options, "mask_url", "mask")
    if mask_url:
        body["mask_url"] = mask_url
        body["mask"] = mask_url
    if settings.image_async_enabled:
        body["async"] = True

    # 站点差异交给配置/命令的附加参数：最后合并，允许覆盖上面的默认值。
    extra_text = option_value(options, "extra", "params") or settings.extra_request_params
    for key, value in parse_extra_params(extra_text).items():
        if key == "prompt":
            continue
        body[key] = value

    payload = cast(ImageRequestPayload, body)
    return DrawRequest(
        prompt=text,
        payload=payload,
        size_values=billing_size_values(size, resolution),
        resolution=resolution,
        billing_units=RESOLUTION_BILLING_UNITS.get(resolution, 1) if resolution_option else 1,
        options=options,
        model=model,
    )


__all__ = [
    "DrawRequest",
    "apply_inline_options",
    "billing_size_values",
    "build_request",
    "image_size_candidates",
    "infer_resolution_from_size",
    "is_image_size_error",
    "normalize_image_resolution",
    "normalize_image_size",
    "normalize_size_format",
    "normalize_submitted_size",
    "option_value",
    "parse_extra_params",
    "parse_options",
    "remove_text_spans",
    "resolve_model_name",
]
