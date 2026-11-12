"""GPTDraw 纯逻辑定向测试：参数解析、模型选择、响应解析与预设条目。"""

from __future__ import annotations

from GPTDraw.GPTDraw.gpt_core.api import extract_urls
from GPTDraw.GPTDraw.gpt_core.common import ParamError, mask_key, validate_preset_name, normalize_preset_name
from GPTDraw.GPTDraw.gpt_core.models import ModelInfo, match_model, parse_models, filter_models
from GPTDraw.GPTDraw.gpt_core.params import (
    build_request,
    parse_options,
    parse_extra_params,
    resolve_model_name,
    is_image_size_error,
    apply_inline_options,
    image_size_candidates,
)
from GPTDraw.GPTDraw.gpt_core.presets import PresetEntry, combine_prompt, _parse_api_item
from GPTDraw.GPTDraw.gpt_core.settings import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "api_base_url": "http://localhost:3000/v1",
        "request_timeout": 300,
        "max_concurrent": 2,
        "allow_private_reference_urls": True,
        "billing_request_path": "/images/generations",
        "image_request_mode": "images_generations",
        "image_async_enabled": True,
        "image_task_request_path": "/v1/images/generations/{task_id}",
        "poll_interval": 8,
        "poll_timeout": 360,
        "default_image_model": "gpt-image-2.6-sunburst",
        "model_list_filter": "image",
        "model_cache_ttl": 120,
        "default_image_size": "1:1",
        "default_image_size_format": "ratio",
        "default_image_resolution": "1k",
        "default_output_format": "png",
        "default_quality": "",
        "default_background": "",
        "default_complexity": "low",
        "default_frame_count": 9,
        "default_frame_duration_ms": 200,
        "extra_request_params": "",
        "preset_api_base_url": "",
        "preset_api_timeout": 8,
        "preset_api_refresh_interval": 60,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_parse_options_and_inline_size() -> None:
    settings = make_settings()
    options, prompt = parse_options("一只橘猫 --quality high --size=16:9 --n 2")
    assert options == {"quality": "high", "size": "16:9", "n": "2"}
    assert prompt == "一只橘猫"

    options, prompt = apply_inline_options({}, "赛博朋克城市 2k --size 3:2", settings)
    assert prompt == "赛博朋克城市"
    assert options["size"] == "3:2"
    assert options["resolution"] == "2k"


def test_build_request_uses_selected_model() -> None:
    settings = make_settings()
    default = build_request({}, "一只猫", "一只猫", settings)
    assert default.payload["model"] == "gpt-image-2.6-sunburst"
    assert default.payload["size"] == "1:1"
    assert default.payload["n"] == 1
    assert default.payload["output_format"] == "png"
    assert "resolution" not in default.payload
    assert "version" not in default.payload
    assert "quality" not in default.payload
    assert default.billing_units == 1
    assert default.size_values == ["1:1", "auto"]

    selected = build_request({}, "一只猫", "一只猫", settings, default_model="gpt-image-2.6-sunburst-native")
    assert selected.payload["model"] == "gpt-image-2.6-sunburst-native"
    assert selected.model == "gpt-image-2.6-sunburst-native"

    override = build_request(
        {"model": "gpt-image-2.5-ext-2k"}, "一只猫", "一只猫", settings, default_model="gpt-image-2.6-sunburst-native"
    )
    assert override.payload["model"] == "gpt-image-2.5-ext-2k"


def test_optional_resolution_and_version() -> None:
    settings = make_settings()
    two_k = build_request({"resolution": "2k", "size": "16:9"}, "一只猫", "一只猫", settings)
    assert two_k.payload["size"] == "16:9"
    assert two_k.payload["resolution"] == "2K"
    assert two_k.billing_units == 2

    four_k = build_request({"resolution": "4k"}, "一只猫", "一只猫", settings)
    assert four_k.payload["resolution"] == "4K"
    assert four_k.billing_units == 3

    sunburst = build_request({"version": "sunburst"}, "一只猫", "一只猫", settings)
    assert sunburst.payload["version"] == "sunburst"

    for options in ({"version": "v2"}, {"resolution": "8k"}):
        try:
            build_request(options, "一只猫", "一只猫", settings)
        except ParamError:
            continue
        raise AssertionError(f"{options} 应该被拒绝")


def test_model_name_validation() -> None:
    assert resolve_model_name(" gpt-image-2.6-sunburst-native ") == "gpt-image-2.6-sunburst-native"
    for bad in ("", "带 空格", "x" * 121):
        try:
            resolve_model_name(bad)
        except ParamError:
            continue
        raise AssertionError(f"{bad!r} 应该被拒绝")


def test_n_allows_multiple() -> None:
    settings = make_settings()
    assert build_request({"n": "2"}, "一只猫", "一只猫", settings).payload["n"] == 2
    for bad in ("0", "11", "abc"):
        try:
            build_request({"n": bad}, "一只猫", "一只猫", settings)
        except ParamError:
            continue
        raise AssertionError(f"n={bad} 应该被拒绝")


def test_gif_payload() -> None:
    settings = make_settings()
    gif = build_request({"format": "gif"}, "小橘猫挥手", "小橘猫挥手", settings)
    assert gif.payload["output_format"] == "gif"
    assert gif.payload["size"] == "auto"
    assert gif.payload["complexity"] == "low"
    assert gif.payload["frame_count"] == 9
    assert gif.payload["frame_duration_ms"] == 200

    custom = build_request(
        {"gif": "true", "frame_count": "16", "frame_duration": "120", "complexity": "high"},
        "小橘猫挥手",
        "小橘猫挥手",
        settings,
    )
    assert custom.payload["output_format"] == "gif"
    assert custom.payload["frame_count"] == 16
    assert custom.payload["frame_duration_ms"] == 120
    assert custom.payload["complexity"] == "high"

    explicit_size = build_request(
        {"format": "gif", "size": "512x512", "size_format": "pixels"}, "小橘猫挥手", "小橘猫挥手", settings
    )
    assert explicit_size.payload["size"] == "512x512"

    plain = build_request({}, "小橘猫挥手", "小橘猫挥手", settings)
    assert "frame_count" not in plain.payload
    assert "complexity" not in plain.payload


def test_extra_params() -> None:
    settings = make_settings()
    extra = build_request({"extra": "version=flare,resolution=2K,seed=42"}, "一只猫", "一只猫", settings)
    assert extra.payload["version"] == "flare"
    assert extra.payload["resolution"] == "2K"
    assert extra.payload["seed"] == 42

    from_config = make_settings(extra_request_params='{"quality": "high", "n": 2}')
    merged = build_request({}, "一只猫", "一只猫", from_config)
    assert merged.payload["quality"] == "high"
    assert merged.payload["n"] == 2

    assert parse_extra_params("") == {}
    for bad in ("{not json", "seed"):
        try:
            parse_extra_params(bad)
        except ParamError:
            continue
        raise AssertionError(f"{bad!r} 应该被拒绝")


def test_size_formats_and_helpers() -> None:
    settings = make_settings()
    pixels = build_request({"size": "16:9", "size_format": "pixels", "resolution": "2k"}, "猫", "猫", settings)
    assert pixels.payload["size"] == "2048x1152"

    auto = build_request({"size": "auto"}, "一只猫", "一只猫", settings)
    assert auto.payload["size"] == "auto"

    normalized = build_request({"size": "1024X1024", "size_format": "pixels"}, "一只猫", "一只猫", settings)
    assert normalized.payload["size"] == "1024x1024"

    try:
        build_request({"size": "很大"}, "一只猫", "一只猫", settings)
    except ParamError:
        pass
    else:
        raise AssertionError("非法尺寸应该报错")

    assert image_size_candidates("16:9", "2k")["pixels"] == "2048x1152"
    assert image_size_candidates("2048x2048", None)["ratio"] == "1:1"
    assert is_image_size_error("Invalid size: 1536x864")
    assert not is_image_size_error("invalid api key")


def test_model_list_helpers() -> None:
    models = parse_models(
        {
            "data": [
                {"id": "gpt-image-2.6-sunburst-native", "owned_by": "new-api"},
                {"id": "gpt-image-2.5-ext-2k"},
                {"id": "gpt-4o-mini"},
                "gpt-image-2.6-flare",
                {"id": "gpt-image-2.6-sunburst-native"},
            ]
        }
    )
    ids = [model.id for model in models]
    assert ids == [
        "gpt-4o-mini",
        "gpt-image-2.5-ext-2k",
        "gpt-image-2.6-flare",
        "gpt-image-2.6-sunburst-native",
    ]
    assert parse_models({"models": [{"name": "foo"}]})[0].id == "foo"
    assert parse_models({"nope": 1}) == []

    assert [model.id for model in filter_models(models, "image")] == ids[1:]
    assert [model.id for model in filter_models(models, "全部")] == ids
    assert filter_models(models, "sunburst")[0].id == "gpt-image-2.6-sunburst-native"

    listed = [ModelInfo(id=model) for model in ("a-model", "b-model-ext", "c-model-ext")]
    assert match_model(listed, "2") == "b-model-ext"
    assert match_model(listed, "a-model") == "a-model"
    assert match_model(listed, "b-model") == "b-model-ext"
    for bad in ("9", "model"):
        try:
            match_model(listed, bad)
        except ParamError:
            continue
        raise AssertionError(f"{bad!r} 应该被拒绝（序号越界或匹配多个）")


def test_extract_urls() -> None:
    urls = extract_urls(
        {
            "data": [
                {"url": "https://cdn.example.com/a.png"},
                {"b64_json": "QUJD", "mime_type": "image/png"},
            ]
        }
    )
    assert urls == ["https://cdn.example.com/a.png", "data:image/png;base64,QUJD"]
    assert extract_urls({"task_id": "t-1", "status": "queued"}) == []


def test_preset_entry_and_prompt() -> None:
    entry = _parse_api_item({"name": " 小猫 ", "prompt": "a cat", "entry_type": "preset", "reply": "喵"})
    assert entry is not None
    assert (entry.name, entry.source, entry.reply) == ("小猫", "remote", "喵")
    assert _parse_api_item({"name": "主题", "prompt": "x", "entry_type": "prompt_share"}) is None
    preset = PresetEntry(name="小猫", prompt="a cat", reply="", image="", source="local")
    assert combine_prompt(preset, "戴帽子") == "a cat 戴帽子"
    assert combine_prompt(preset, "") == "a cat"


def test_name_and_mask() -> None:
    assert normalize_preset_name("/#小猫") == "小猫"
    assert validate_preset_name("小猫-1") == "小猫-1"
    try:
        validate_preset_name("有 空格")
    except ParamError:
        pass
    else:
        raise AssertionError("带空格的预设名应该报错")
    assert mask_key("sk-12345678") == "****5678"


def test_inline_references() -> None:
    import io
    import asyncio
    import tempfile
    from pathlib import Path

    from PIL import Image

    from GPTDraw.GPTDraw.gpt_core.service import inline_references
    from GPTDraw.GPTDraw.gpt_core.image_input import to_data_url

    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buffer, "PNG")
    raw = buffer.getvalue()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ref.png"
        path.write_bytes(raw)
        inlined = asyncio.run(inline_references([str(path)]))
        assert inlined is not None and len(inlined) == 1
        assert inlined[0] == to_data_url(raw)
        # 已经是 data URL 的不改写
        assert asyncio.run(inline_references([to_data_url(raw)])) is None
        # 读不到的引用直接放弃，交给后面的兜底
        assert asyncio.run(inline_references(["https://example.invalid/none.png"])) is None

