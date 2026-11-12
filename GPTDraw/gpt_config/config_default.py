"""GPTDraw 插件配置项。

余额、消耗排行与总余额相关配置已移除：这些能力由 NewAPI 看板插件负责。
"""

from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsDivider,
    GsIntConfig,
    GsStrConfig,
    GsBoolConfig,
)

CONFIG_DEFAULT: dict[str, GSC] = {
    "api_divider": GsDivider("New API 接口", ""),
    "api_base_url": GsStrConfig(
        "New API 地址",
        "生图统一使用的 New API 地址，例如 http://127.0.0.1:3000/v1。",
        "http://localhost:3000/v1",
    ),
    "request_timeout": GsIntConfig(
        "请求超时（秒）",
        "单次提交或查询 New API 的超时时间。",
        300,
        max_value=900,
    ),
    "max_concurrent": GsIntConfig(
        "最大并发请求",
        "同时向 New API 发起的生图请求数上限。",
        2,
        max_value=10,
    ),
    "allow_private_reference_urls": GsBoolConfig(
        "允许内网参考图链接",
        "关闭后 --images 只接受公网 URL 或 data:image；开启后内网 URL 也会原样交给 New API。",
        True,
    ),
    "request_divider": GsDivider("请求方式", ""),
    "billing_request_path": GsStrConfig(
        "图片生成请求路径",
        "Images API 渠道填 /images/generations；聊天式绘图渠道可填 /chat/completions。",
        "/images/generations",
    ),
    "image_request_mode": GsStrConfig(
        "图片请求体模式",
        "auto 按请求路径选择：/images/generations 走 Images API，/chat/completions 走 messages 并从回复解析图片链接。",
        "auto",
        options=["auto", "images_generations", "chat_completions"],
    ),
    "image_async_enabled": GsBoolConfig(
        "启用 New API 图片异步任务",
        "仅 Images API 模式有效；开启后提交时携带 async=true，由 New API 后台生成并轮询。",
        True,
    ),
    "image_task_request_path": GsStrConfig(
        "图片异步任务查询路径",
        "查询 New API 内部图片任务；{task_id} 会替换为任务 ID。",
        "/v1/images/generations/{task_id}",
    ),
    "poll_interval": GsIntConfig(
        "异步任务轮询间隔（秒）",
        "拿到 task_id 后查询结果的间隔。",
        8,
        max_value=120,
    ),
    "poll_timeout": GsIntConfig(
        "异步任务轮询超时（秒）",
        "拿到 task_id 后最多等待的秒数。",
        360,
        max_value=1800,
    ),
    "model_divider": GsDivider("模型选择", ""),
    "default_image_model": GsStrConfig(
        "默认模型",
        "没有用「gpt切换模型」选过模型时使用；可随时用 gpt模型列表 查看可用模型。",
        "gpt-image-2.6-sunburst",
    ),
    "model_list_filter": GsStrConfig(
        "模型列表筛选词",
        "gpt模型列表 只显示名称包含这些关键字的模型，多个用逗号分隔；填 all 显示全部。",
        "image",
    ),
    "model_cache_ttl": GsIntConfig(
        "模型列表缓存（秒）",
        "同一把密钥重复查询模型列表的缓存时间。",
        120,
        max_value=3600,
    ),
    "default_divider": GsDivider("默认生图参数", ""),
    "default_image_size": GsStrConfig(
        "默认图片尺寸",
        "可填比例（1:1、16:9 等）、像素（1024x1024）、单边像素或 auto；填像素会按尺寸格式换算。",
        "1:1",
    ),
    "default_image_size_format": GsStrConfig(
        "默认尺寸提交格式",
        "ratio 提交比例；pixels 提交像素；single 提交单边像素；auto 原样提交。",
        "ratio",
        options=["ratio", "pixels", "single", "auto"],
    ),
    "default_image_resolution": GsStrConfig(
        "默认分辨率基准",
        "只用于把比例换算成像素尺寸（1k / 2k / 4k），不再影响模型选择。",
        "1k",
        options=["1k", "2k", "4k"],
    ),
    "default_output_format": GsStrConfig(
        "默认输出格式",
        "png / jpeg / webp / gif；留空则不发送该字段，交给上游决定。选 gif 时自动带上帧参数。",
        "png",
        options=["", "png", "jpeg", "webp", "gif", "auto"],
    ),
    "default_quality": GsStrConfig(
        "默认质量",
        "auto / low / medium / high；留空则不发送该字段。",
        "",
        options=["", "auto", "low", "medium", "high"],
    ),
    "default_background": GsStrConfig(
        "默认背景",
        "auto / opaque / transparent；留空则不发送该字段。",
        "",
        options=["", "auto", "opaque", "transparent"],
    ),
    "default_complexity": GsStrConfig(
        "GIF 动画复杂度",
        "生成 GIF 时的 complexity：low / medium / high；留空则不发送。",
        "low",
        options=["", "low", "medium", "high"],
    ),
    "default_frame_count": GsIntConfig(
        "GIF 默认帧数",
        "生成 GIF 时的帧数；0 表示不发送该字段。",
        9,
        max_value=60,
    ),
    "default_frame_duration_ms": GsIntConfig(
        "GIF 默认帧间隔（毫秒）",
        "生成 GIF 时每帧的时长；0 表示不发送该字段。",
        200,
        max_value=2000,
    ),
    "extra_request_params": GsStrConfig(
        "附加请求参数",
        "以 k=v,k2=v2 或 JSON 对象写进每次请求体，例如 version=flare,resolution=2K；留空不加。",
        "",
    ),
    "preset_divider": GsDivider("预设与提示词库", ""),
    "preset_api_base_url": GsStrConfig(
        "提示词库 API 地址",
        "插件会调用 /api/presets 与 /api/presets/{name}，只同步标记为预设的内容；留空则只用本地预设。",
        "http://127.0.0.1:19731",
    ),
    "preset_api_timeout": GsIntConfig("提示词库 API 超时（秒）", "请求提示词库接口的超时时间。", 8, max_value=60),
    "preset_api_refresh_interval": GsIntConfig(
        "预设同步间隔（秒）",
        "后台刷新远程预设缓存的间隔；新上传预设后可用「gpt重载预设库」立即拉取。",
        60,
        max_value=3600,
    ),
}
