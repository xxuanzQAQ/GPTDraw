# ruff: noqa: E402, F401, I001
"""GPTDraw 生图的 GsCore 插件入口。

``Plugins(...)`` 必须先执行，之后的有序导入负责注册数据库模型、配置与命令。
``gpt_database.models`` 需要早于 core 的 ``create_all`` 钩子，因此这里显式导入。
"""

from gsuid_core.config import plugin_config_store
from gsuid_core.sv import Plugins

_PLUGIN_KEYS = {
    "name",
    "pm",
    "priority",
    "enabled",
    "area",
    "black_list",
    "white_list",
    "prefix",
    "force_prefix",
    "disable_force_prefix",
    "allow_empty_prefix",
    "sv",
    "alias",
}


def _sanitize_legacy_plugin_config() -> None:
    """清掉旧配置里不属于 ``Plugins`` 参数的键，避免加载时抛 unexpected keyword。"""
    data = plugin_config_store.get("GPTDraw")
    if not data:
        return
    cleaned = {key: value for key, value in data.items() if key in _PLUGIN_KEYS}
    # 本插件只允许 gpt / GPT 前缀触发，不允许旧配置打开无前缀或关掉强制前缀。
    cleaned["allow_empty_prefix"] = False
    cleaned["disable_force_prefix"] = False
    if cleaned == data:
        return
    plugin_config_store.set("GPTDraw", cleaned)
    plugin_config_store.save("GPTDraw")


_sanitize_legacy_plugin_config()

Plugins(
    name="GPTDraw",
    force_prefix=["gpt", "GPT"],
    allow_empty_prefix=False,
    alias=["GPT生图", "AI图片"],
)

from . import gpt_paths  # noqa: E402,F401
from . import gpt_config  # noqa: E402,F401
from . import gpt_database  # noqa: E402,F401
from . import gpt_core  # noqa: E402,F401
from . import gpt_commands  # noqa: E402,F401
from .gpt_commands.help import register_plugin_help  # noqa: E402

register_plugin_help()
