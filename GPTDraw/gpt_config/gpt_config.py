"""配置单例。"""

from gsuid_core.utils.plugins_config.gs_config import StringConfig

from ..gpt_paths import CONFIG_PATH
from .config_default import CONFIG_DEFAULT

CONFIG = StringConfig("GPTDraw", CONFIG_PATH, CONFIG_DEFAULT)

__all__ = ["CONFIG", "CONFIG_DEFAULT"]
