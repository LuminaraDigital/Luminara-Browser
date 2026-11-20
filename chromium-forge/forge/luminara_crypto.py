"""Hardware/OS-Bound Cryptography & Ephemeral Session Signing (`forge/luminara_crypto.py`).

Zero-dependency cryptographic layer for Luminara Browser (`v3.0.0`):
1. `dpapi_protect` / `dpapi_unprotect`: Win64-safe `ctypes` Windows DPAPI (`Crypt32.dll`)
   with explicit pointer `.argtypes` / `.restype` binding keys to the Windows user/machine.
2. `aead_seal` / `aead_open`: Pure-stdlib Encrypt-then-MAC (`HKDF-SHA256` + vectorized
   `SHA-256-CTR` + `HMAC-SHA256` with length-prefixed AAD) for cross-platform/USB portability.
3. `LuminaraEnvelopeCipher`: Wraps vault secrets with origin-bound AAD (`luminara:vault:v2:<origin>`)
   using `0o600` atomic key-store writes (`atomic_write_private`).
4. `EphemeralSessionSigner`: Short-lived HMAC-SHA256 session tokens + cryptographic receipt
   authenticator (`LUM-SIG-v2`).
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import time
from typing import Any

from .http_base import atomic_write_private

ENCODING = "utf-8"
ENVELOPE_VERSION = 2
PBKDF2_ITERATIONS = 310_000


class CryptoError(RuntimeError):
    """Raised when encryption, decryption, AAD authentication, or key unwrapping fails."""


# ---------------------------------------------------------------------------
# 1. Native Win64-Safe Windows DPAPI (`Crypt32.dll`)
# ---------------------------------------------------------------------------

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_DPAPI_FUNCS_INITIALIZED = False


def dpapi_available() -> bool:
    return os.name == "nt" and hasattr(ctypes, "windll")


def _ensure_dpapi_prototypes() -> tuple[Any, Any]:
    global _DPAPI_FUNCS_INITIALIZED
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not _DPAPI_FUNCS_INITIALIZED:
        p_blob = ctypes.POINTER(_DATA_BLOB)
        crypt32.CryptProtectData.argtypes = [
            p_blob,
            wintypes.LPCWSTR,
            p_blob,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            p_blob,
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            p_blob,
            ctypes.c_void_p,
            p_blob,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            p_blob,
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        _DPAPI_FUNCS_INITIALIZED = True
    return crypt32, kernel32


def dpapi_protect(plaintext: bytes, *, entropy: bytes | None = b"LuminaraBrowserVaultV2") -> bytes:
    """Encrypt bytes using Windows DPAPI (`CryptProtectData`, current-user scope)."""
    if not dpapi_available():
        raise CryptoError("Windows DPAPI is not available on this platform")
    crypt32, kernel32 = _ensure_dpapi_prototypes()
    in_buf = ctypes.create_string_buffer(plaintext, len(plaintext))
    in_blob = _DATA_BLOB(len(plaintext), in_buf)
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy)) if entropy else None
    ent_blob = _DATA_BLOB(len(entropy), ent_buf) if (entropy and ent_buf is not None) else None
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "LuminaraVaultKey",
        ctypes.byref(ent_blob) if ent_blob is not None else None,
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    )
    if not ok:
        raise CryptoError(f"CryptProtectData failed (err={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def dpapi_unprotect(ciphertext: bytes, *, entropy: bytes | None = b"LuminaraBrowserVaultV2") -> bytes:
    """Decrypt bytes previously protected with `dpapi_protect`."""
    if not dpapi_available():
        raise CryptoError("Windows DPAPI is not available on this platform")
    crypt32, kernel32 = _ensure_dpapi_prototypes()
    in_buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
    in_blob = _DATA_BLOB(len(ciphertext), in_buf)
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy)) if entropy else None
    ent_blob = _DATA_BLOB(len(entropy), ent_buf) if (entropy and ent_buf is not None) else None
    out_blob = _DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(ent_blob) if ent_blob is not None else None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise CryptoError(f"CryptUnprotectData failed (err={ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


# ---------------------------------------------------------------------------
# 2. Pure-Stdlib AEAD (`HKDF-SHA256` + Vectorized `CTR-HMAC-SHA256`)
# ---------------------------------------------------------------------------

def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 64) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out = bytearray()
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor_keystream(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    """Generate SHA-256-CTR keystream and XOR in C-speed big-int blocks."""
    total = len(data)
    if total == 0:
        return b""
    blocks = (total + 31) // 32
    ks = b"".join(
        hmac.new(enc_key, nonce + struct.pack(">Q", c), hashlib.sha256).digest()
        for c in range(blocks)
    )[:total]
    return (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(total, "big")


def aead_seal(key: bytes, plaintext: bytes, *, aad: bytes = b"") -> dict[str, str]:
    """Encrypt and authenticate `plaintext` bound cryptographically to `aad`."""
    if len(key) < 32:
        raise CryptoError("AEAD master key must be at least 32 bytes")
    nonce = secrets.token_bytes(16)
    derived = _hkdf_sha256(key, nonce, b"luminara-aead-v2", 64)
    enc_key, mac_key = derived[:32], derived[32:]
    ct = _xor_keystream(enc_key, nonce, plaintext)
    mac_input = (
        b"LUM-AEAD-V2"
        + nonce
        + struct.pack(">Q", len(aad))
        + aad
        + struct.pack(">Q", len(ct))
        + ct
    )
    tag = hmac.new(mac_key, mac_input, hashlib.sha256).digest()
    return {
        "alg": "HKDF-SHA256-CTR-HMAC",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def aead_open(key: bytes, blob: dict[str, str], *, aad: bytes = b"") -> bytes:
    """Authenticate `aad` + ciphertext tag in constant time and decrypt."""
    if len(key) < 32:
        raise CryptoError("AEAD master key must be at least 32 bytes")
    try:
        nonce = base64.b64decode(blob["nonce"])
        ct = base64.b64decode(blob["ct"])
        tag = base64.b64decode(blob["tag"])
    except Exception as exc:  # noqa: BLE001
        raise CryptoError(f"Malformed AEAD envelope: {exc}") from exc

    derived = _hkdf_sha256(key, nonce, b"luminara-aead-v2", 64)
    enc_key, mac_key = derived[:32], derived[32:]
    mac_input = (
        b"LUM-AEAD-V2"
        + nonce
        + struct.pack(">Q", len(aad))
        + aad
        + struct.pack(">Q", len(ct))
        + ct
    )
    expected_tag = hmac.new(mac_key, mac_input, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise CryptoError("AEAD authentication tag mismatch (tampered ciphertext or wrong origin AAD)")
    return _xor_keystream(enc_key, nonce, ct)


# ---------------------------------------------------------------------------
# 3. Vault Key Management (DPAPI Desktop Default + Passphrase USB Roaming)
# ---------------------------------------------------------------------------

class LuminaraEnvelopeCipher:
    """Manages a 256-bit data encryption key (DEK) wrapped by Windows DPAPI or PBKDF2 passphrase."""

    def __init__(
        self,
        key_store_path: Path,
        *,
        passphrase: str | None = None,
        prefer_dpapi: bool = True,
    ) -> None:
        self.key_store_path = key_store_path.resolve()
        self.key_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.passphrase = passphrase
        self.prefer_dpapi = prefer_dpapi
        self.protection_mode = "unknown"
        self._dek = self._load_or_create_dek()

    def _derive_passphrase_kek(self, passphrase: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", passphrase.encode(ENCODING), salt, PBKDF2_ITERATIONS, dklen=32)

    def _load_or_create_dek(self) -> bytes:
        if self.key_store_path.exists():
            meta = json.loads(self.key_store_path.read_text(encoding=ENCODING))
            mode = meta.get("mode")
            if mode == "dpapi":
                raw = base64.b64decode(meta["wrapped_dek"])
                self.protection_mode = "dpapi"
                return dpapi_unprotect(raw)
            if mode == "passphrase":
                if not self.passphrase:
                    raise CryptoError("Vault key is passphrase-protected; provide passphrase to unlock")
                salt = base64.b64decode(meta["salt"])
                kek = self._derive_passphrase_kek(self.passphrase, salt)
                self.protection_mode = "passphrase"
                return aead_open(kek, meta["wrapped_dek"], aad=b"luminara:dek:v2")
            if mode == "local_file_key":
                self.protection_mode = "local_file_key"
                return base64.b64decode(meta["wrapped_dek"])
            raise CryptoError(f"Unsupported vault key store mode: {mode!r}")

        dek = secrets.token_bytes(32)
        if self.passphrase:
            salt = secrets.token_bytes(16)
            kek = self._derive_passphrase_kek(self.passphrase, salt)
            wrapped = aead_seal(kek, dek, aad=b"luminara:dek:v2")
            payload: dict[str, Any] = {
                "version": ENVELOPE_VERSION,
                "mode": "passphrase",
                "kdf": f"PBKDF2-HMAC-SHA256-{PBKDF2_ITERATIONS}",
                "salt": base64.b64encode(salt).decode("ascii"),
                "wrapped_dek": wrapped,
            }
            self.protection_mode = "passphrase"
        elif self.prefer_dpapi and dpapi_available():
            wrapped_bytes = dpapi_protect(dek)
            payload = {
                "version": ENVELOPE_VERSION,
                "mode": "dpapi",
                "wrapped_dek": base64.b64encode(wrapped_bytes).decode("ascii"),
            }
            self.protection_mode = "dpapi"
        else:
            payload = {
                "version": ENVELOPE_VERSION,
                "mode": "local_file_key",
                "wrapped_dek": base64.b64encode(dek).decode("ascii"),
            }
            self.protection_mode = "local_file_key"

        atomic_write_private(self.key_store_path, json.dumps(payload, indent=2) + "\n")
        return dek

    def seal_json(self, obj: dict[str, Any], *, aad_context: str) -> dict[str, str]:
        raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(ENCODING)
        return aead_seal(self._dek, raw, aad=aad_context.encode(ENCODING))

    def open_json(self, envelope: dict[str, str], *, aad_context: str) -> dict[str, Any]:
        raw = aead_open(self._dek, envelope, aad=aad_context.encode(ENCODING))
        parsed = json.loads(raw.decode(ENCODING))
        if not isinstance(parsed, dict):
            raise CryptoError("Decrypted vault payload is not a JSON object")
        return parsed


# ---------------------------------------------------------------------------
# 4. Ephemeral Session Tokens & Cryptographic Receipt Authenticator
# ---------------------------------------------------------------------------

class EphemeralSessionSigner:
    """Issues and verifies short-lived HMAC-SHA256 session tokens and receipt MACs."""

    def __init__(self, secret_key: bytes | None = None, *, default_ttl_sec: int = 900) -> None:
        self._key = secret_key or secrets.token_bytes(32)
        self.default_ttl_sec = max(30, int(default_ttl_sec))
        self.key_id = hashlib.sha256(self._key).hexdigest()[:12]

    def issue_token(self, scope: str = "ui", ttl_sec: int | None = None) -> str:
        clean_scope = (scope or "").strip()
        if (
            not clean_scope
            or len(clean_scope) > 32
            or not clean_scope.isascii()
            or not all(c.isalnum() or c in "_-" for c in clean_scope)
        ):
            raise ValueError(f"Invalid session token scope: {scope!r}")
        raw_ttl = self.default_ttl_sec if ttl_sec is None else int(ttl_sec)
        bounded_ttl = max(10, min(3600, raw_ttl))
        exp = int(time.time()) + bounded_ttl
        nonce = secrets.token_hex(8)
        body = f"lum2.{clean_scope}.{exp}.{nonce}"
        sig = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{sig}"

    def verify_token(self, token: str, *, required_scope: str | None = None, now: float | None = None) -> bool:
        parts = (token or "").strip().split(".")
        if len(parts) != 5 or parts[0] != "lum2":
            return False
        _, scope, exp_s, nonce, sig = parts
        if required_scope and scope != required_scope:
            return False
        if not exp_s.isdigit():
            return False
        cur = time.time() if now is None else now
        if int(exp_s) < int(cur):
            return False
        body = f"lum2.{scope}.{exp_s}.{nonce}"
        expected = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected)

    def sign_receipt_digest(self, sha256_hex: str) -> str:
        mac = hmac.new(self._key, f"LUM-SIG-V2:{sha256_hex}".encode("ascii"), hashlib.sha256).hexdigest()
        return f"lum-hmac256:{self.key_id}:{mac[:40]}"

    def verify_receipt_signature(self, sha256_hex: str, signature: str) -> bool:
        expected = self.sign_receipt_digest(sha256_hex)
        return hmac.compare_digest(signature or "", expected)
