"""插件文件路径与运行时目录。"""

from pathlib import Path

from gsuid_core.data_store import get_res_path

PACKAGE_DIR = Path(__file__).resolve().parents[0]
PLUGIN_DIR = Path(__file__).resolve().parents[1]

MAIN_PATH = get_res_path("GPTDraw")
CONFIG_PATH = MAIN_PATH / "config.json"
TOKEN_KEY_PATH = MAIN_PATH / "token.key"
IMAGE_CACHE_PATH = MAIN_PATH / "images"

for _path in (MAIN_PATH, IMAGE_CACHE_PATH):
    _path.mkdir(parents=True, exist_ok=True)

__all__ = [
    "CONFIG_PATH",
    "IMAGE_CACHE_PATH",
    "MAIN_PATH",
    "PACKAGE_DIR",
    "PLUGIN_DIR",
    "TOKEN_KEY_PATH",
]
