"""Credential encryption.

Each credential is encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The Fernet master
key is itself encrypted with Windows DPAPI for the current Windows user and stored next
to the database (``<db>.key``). Copying the database and key file to another machine or
user account does not let anyone decrypt the credentials, and no master password is needed.

Back up caveat: if the Windows user profile is lost (reinstall), the credentials are too.
Re-enter them; nothing else in the database depends on them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

_ENTROPY = b"automation-engine/credential-vault/v1"


class VaultError(Exception):
    pass


class KeyStore(Protocol):
    def load_or_create(self) -> bytes: ...


class StaticKeyStore:
    """Fixed key (tests, or a key supplied by the caller)."""

    def __init__(self, key: bytes | None = None) -> None:
        self.key = key or Fernet.generate_key()

    def load_or_create(self) -> bytes:
        return self.key


class DpapiKeyStore:
    """Master key file protected with Windows DPAPI (CurrentUser scope)."""

    def __init__(self, path: str | Path) -> None:
        if sys.platform != "win32":
            raise VaultError("DPAPI is only available on Windows; pass a StaticKeyStore instead")
        self.path = Path(path)

    def load_or_create(self) -> bytes:
        if self.path.exists():
            try:
                return _dpapi_unprotect(self.path.read_bytes())
            except OSError as exc:
                raise VaultError(
                    f"cannot unlock {self.path}: it was created by another Windows user or machine"
                ) from exc
        key = Fernet.generate_key()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(_dpapi_protect(key))
        return key


class Vault:
    def __init__(self, key_store: KeyStore) -> None:
        self._fernet = Fernet(key_store.load_or_create())

    def encrypt(self, data: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode("utf-8"))

    def decrypt(self, token: bytes) -> dict[str, Any]:
        try:
            return json.loads(self._fernet.decrypt(token))
        except InvalidToken:
            raise VaultError("credential cannot be decrypted: the master key does not match") from None


# ------------------------------------------------------------------ DPAPI via ctypes

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _fn in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
        # 2nd arg: description (in, protect) / description out-pointer (unprotect); always NULL here
        _fn.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPVOID, ctypes.POINTER(_BLOB),
                        wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_BLOB)]
        _fn.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def _blob(data: bytes) -> tuple[_BLOB, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _call(fn: Any, data: bytes) -> bytes:
        src, _keep = _blob(data)
        ent, _keep2 = _blob(_ENTROPY)
        out = _BLOB()
        if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None,
                  _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def _dpapi_protect(data: bytes) -> bytes:
        return _call(_crypt32.CryptProtectData, data)

    def _dpapi_unprotect(data: bytes) -> bytes:
        return _call(_crypt32.CryptUnprotectData, data)
