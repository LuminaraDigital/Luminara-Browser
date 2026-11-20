"""Zero-Telemetry Opt-In Cryptographic Update Manifest Verifier (`forge/updater.py`).

Unlike Chrome's background Omaha/GoogleUpdate daemon (which phones home silently),
Luminara Browser never performs automatic background network pings. Users or admins
explicitly invoke `python -m forge check-updates --manifest <path-or-url>` to verify
release SHA-256 + HMAC signature authenticity before upgrading.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
import urllib.request

from .cdp_client import validate_navigation_url

ENCODING = "utf-8"
MAX_MANIFEST_BYTES = 1024 * 1024  # 1 MiB safety cap


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Serialize release manifest deterministically excluding `signature` and `manifest_sha256`."""
    payload = {k: v for k, v in manifest.items() if k not in ("signature", "manifest_sha256")}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(ENCODING)


def sign_release_manifest(manifest: dict[str, Any], signing_key: bytes) -> dict[str, Any]:
    """Attach an authenticated HMAC-SHA256 signature + SHA-256 digest to a release manifest."""
    canon = canonical_manifest_bytes(manifest)
    digest = hashlib.sha256(canon).hexdigest()
    sig = hmac.new(signing_key, b"luminara-release-v3:" + canon, hashlib.sha256).hexdigest()
    out = dict(manifest)
    out["manifest_sha256"] = digest
    out["signature"] = f"hmac-sha256:{sig}"
    return out


def verify_release_manifest(
    manifest: dict[str, Any],
    *,
    signing_key: bytes | None = None,
    allow_unsigned: bool = False,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    """Verify release manifest schema, signature, and optional artifact SHA-256."""
    errors: list[str] = []
    for req in ("version", "chromium_version", "artifact_name", "artifact_sha256"):
        if not str(manifest.get(req) or "").strip():
            errors.append(f"Missing required manifest field: {req}")

    canon = canonical_manifest_bytes(manifest)
    if manifest.get("manifest_sha256"):
        expected_digest = hashlib.sha256(canon).hexdigest()
        if not hmac.compare_digest(str(manifest["manifest_sha256"]), expected_digest):
            errors.append("manifest_sha256 mismatch")

    sig_verified = False
    if signing_key is not None:
        sig_str = str(manifest.get("signature") or "")
        if not sig_str.startswith("hmac-sha256:"):
            errors.append("Missing or unsupported signature scheme")
        else:
            expected_sig = "hmac-sha256:" + hmac.new(signing_key, b"luminara-release-v3:" + canon, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig_str, expected_sig):
                errors.append("Cryptographic release signature mismatch")
            else:
                sig_verified = True
    elif not allow_unsigned:
        errors.append("No signing_key provided (pass --signing-key-hex / LUMINARA_RELEASE_KEY_HEX or --allow-unsigned)")

    artifact_verified = False
    if artifact_path is not None:
        if not artifact_path.exists():
            errors.append(f"Artifact file not found: {artifact_path}")
        else:
            h = hashlib.sha256()
            with artifact_path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if not hmac.compare_digest(actual.lower(), str(manifest.get("artifact_sha256") or "").lower()):
                errors.append(f"Artifact SHA-256 mismatch (expected {manifest.get('artifact_sha256')}, got {actual})")
            else:
                artifact_verified = True

    return {
        "valid": len(errors) == 0,
        "version": str(manifest.get("version") or ""),
        "chromium_version": str(manifest.get("chromium_version") or ""),
        "signature_verified": sig_verified,
        "artifact_verified": artifact_verified,
        "errors": errors,
    }


def _assert_public_https_host(url: str) -> None:
    import ipaddress
    import socket

    validate_navigation_url(url, allow_file=False)
    host = (urllib.parse.urlparse(url).hostname or "").rstrip(".").strip()
    if not host:
        raise ValueError("Invalid HTTPS manifest hostname")
    for _fam, _type, _proto, _canon, sockaddr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"Blocked manifest resolution to non-public IP: {ip}")


class _HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not newurl.lower().startswith("https://"):
            raise ValueError(f"Blocked insecure non-HTTPS manifest redirect: {newurl}")
        _assert_public_https_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_manifest_source(source: str) -> dict[str, Any]:
    """Load a release manifest from a local JSON path or SSRF-checked HTTPS URL (<= 1 MiB)."""
    cleaned = (source or "").strip()
    if cleaned.startswith("https://"):
        _assert_public_https_host(cleaned)
        opener = urllib.request.build_opener(_HTTPSOnlyRedirectHandler())
        with opener.open(cleaned, timeout=15.0) as resp:
            raw = resp.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ValueError("Release manifest exceeds 1 MiB safety limit")
            return json.loads(raw.decode(ENCODING))
    p = Path(cleaned)
    if p.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Local release manifest exceeds 1 MiB safety limit")
    return json.loads(p.read_text(encoding=ENCODING))
