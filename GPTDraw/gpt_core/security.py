"""密钥密文存储。"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..gpt_paths import TOKEN_KEY_PATH


class CipherError(RuntimeError):
    """密钥或密文不可用，需要重新绑定。"""


def _read_key(path: Path) -> bytes:
    data = path.read_bytes().strip()
    if not data:
        raise CipherError("密钥文件为空，请删除 data/GPTDraw/token.key 后重新绑定。")
    return data


def _load_or_create_key() -> bytes:
    path = TOKEN_KEY_PATH
    if path.exists():
        return _read_key(path)
    key = Fernet.generate_key()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_key(path)
    with os.fdopen(descriptor, "wb") as file:
        file.write(key)
    return key


def encrypt_key(token: str) -> str:
    key = _load_or_create_key()
    return Fernet(key).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_key(cipher: str) -> str:
    key = _load_or_create_key()
    try:
        return Fernet(key).decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CipherError("密钥密文无法解密，请重新绑定密钥。") from exc


__all__ = ["CipherError", "decrypt_key", "encrypt_key"]
