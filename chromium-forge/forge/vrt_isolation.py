"""Clean-room Hermetic Declared-Origin Lock & Pure-Stdlib PNG Visual Regression (`forge/vrt_isolation.py`).

Reconstructs the hermetic browser isolation and visual regression primitives of
`perplexityai/rules_web_e2e` (`runtime/isolation.ts`, `runtime/declared-inputs-hook.ts`,
`runtime/visuals.ts`, `runtime/baselines.ts`) in 100% Python `>=3.11` stdlib:
1. **Declared-Origin Network Lock** (`Fetch.enable` via `MultiplexedCDPPool`):
   - Locks a `target_id` to an explicit set of `declared_origins` (`https://host[:port]`).
   - Continues declared-origin and safe local scheme (`data:`, `blob:`, `about:blank`) requests
     inline in $O(1)$ while aborting undeclared third-party network egress with
     `Fetch.failRequest(errorReason="BlockedByClient")` and recording violation telemetry.
2. **Pure-Stdlib RFC 2083 PNG Codec & Pixel-Diff Comparator**:
   - Decodes 8-bit Grayscale, RGB, and RGBA PNGs (reconstructing Sub, Up, Average, and Paeth
     scanlines via `struct` + `zlib` with a 64 MiB decompression-bomb cap).
   - Computes exact pixel mismatch counts, mismatch ratio, RMSE, bounding box of visual drift,
     and emits a valid RGBA diff PNG highlighting changed pixels in high-contrast coral.
"""

from __future__ import annotations

import base64
import binascii
import math
from pathlib import Path
import re
import struct
import threading
import time
from typing import Any
import urllib.parse
import zlib

from .cdp_client import CDPBridge
from .luminara_security import DEFAULT_REDACTOR, LuminaraRedactor

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_BASELINE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-]{0,80}$")
_SAFE_INLINE_SCHEMES = frozenset({"about", "data", "blob"})


def normalize_origin(url_or_origin: str) -> str:
    raw = (url_or_origin or "").strip()
    if not raw:
        raise ValueError("Origin must be non-empty")
    parsed = urllib.parse.urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Expected http(s)://host[:port] origin, got {url_or_origin!r}")
    host = parsed.hostname.lower().rstrip(".")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}:{port}" if (port and port != default_port) else f"{scheme}://{host}"


def validate_baseline_id(baseline_id: str) -> str:
    clean = (baseline_id or "").strip()
    if clean.endswith(".png"):
        clean = clean[:-4]
    if not _BASELINE_NAME_RE.match(clean) or ".." in clean:
        raise ValueError(f"Invalid baseline_id {baseline_id!r}")
    return clean


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def encode_rgba_png(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """Encode raw `width * height * 4` RGBA bytes into a standard RFC 2083 PNG."""
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("Invalid RGBA buffer dimensions")
    stride = width * 4
    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)  # Filter 0 (None)
        row_start = y * stride
        raw_scanlines.extend(rgba[row_start : row_start + stride])

    def _chunk(ctype: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_scanlines), level=6)
    return PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def decode_png_to_rgba(png_bytes: bytes) -> tuple[int, int, bytes]:
    """Decode an 8-bit Non-Interlaced Grayscale/RGB/RGBA PNG to raw RGBA bytes (`zlib`-bounded)."""
    if len(png_bytes) < 33 or not png_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("Input is not a valid PNG file")

    pos = 8
    width = height = bit_depth = color_type = interlace = -1
    idat_parts: list[bytes] = []
    while pos + 8 <= len(png_bytes):
        length, ctype = struct.unpack(">I4s", png_bytes[pos : pos + 8])
        pos += 8
        if pos + length + 4 > len(png_bytes):
            raise ValueError("Truncated PNG chunk")
        cdata = png_bytes[pos : pos + length]
        pos += length + 4
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(">IIBBBBB", cdata)
        elif ctype == b"IDAT":
            idat_parts.append(cdata)
        elif ctype == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise ValueError("PNG missing valid IHDR")
    if bit_depth != 8 or interlace != 0 or color_type not in (0, 2, 6):
        raise ValueError(f"Unsupported PNG format (bit_depth={bit_depth}, color_type={color_type}, interlace={interlace})")

    channels = {0: 1, 2: 3, 6: 4}[color_type]
    stride = width * channels
    expected_raw = height * (1 + stride)
    if expected_raw > MAX_PNG_DECOMPRESSED_BYTES:
        raise ValueError("PNG exceeds 64 MiB decompressed pixel guard")

    decomp = zlib.decompressobj()
    raw = decomp.decompress(b"".join(idat_parts), MAX_PNG_DECOMPRESSED_BYTES + 1)
    if len(raw) > MAX_PNG_DECOMPRESSED_BYTES or len(raw) < expected_raw:
        raise ValueError("Corrupt or oversized PNG IDAT stream")

    prev_row = bytearray(stride)
    cur_row = bytearray(stride)
    out_rgba = bytearray(width * height * 4)
    in_off = 0
    out_off = 0

    for _y in range(height):
        ftype = raw[in_off]
        in_off += 1
        scan = raw[in_off : in_off + stride]
        in_off += stride
        if ftype == 0:
            cur_row[:] = scan
        elif ftype == 1:
            for i in range(stride):
                left = cur_row[i - channels] if i >= channels else 0
                cur_row[i] = (scan[i] + left) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                cur_row[i] = (scan[i] + prev_row[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = cur_row[i - channels] if i >= channels else 0
                cur_row[i] = (scan[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = cur_row[i - channels] if i >= channels else 0
                up = prev_row[i]
                up_left = prev_row[i - channels] if i >= channels else 0
                cur_row[i] = (scan[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"Unsupported PNG scanline filter: {ftype}")

        if color_type == 6:
            out_rgba[out_off : out_off + width * 4] = cur_row
            out_off += width * 4
        elif color_type == 2:
            for px in range(0, stride, 3):
                out_rgba[out_off] = cur_row[px]
                out_rgba[out_off + 1] = cur_row[px + 1]
                out_rgba[out_off + 2] = cur_row[px + 2]
                out_rgba[out_off + 3] = 255
                out_off += 4
        else:
            for px in range(stride):
                g = cur_row[px]
                out_rgba[out_off : out_off + 4] = bytes((g, g, g, 255))
                out_off += 4
        prev_row[:] = cur_row

    return width, height, bytes(out_rgba)


def compare_png_bytes(
    baseline_png: bytes,
    candidate_png: bytes,
    *,
    channel_tolerance: int = 4,
    max_mismatch_ratio: float = 0.01,
) -> dict[str, Any]:
    """Compare two PNG images pixel-by-pixel and return exact diff metrics + RGBA diff PNG."""
    bw, bh, b_rgba = decode_png_to_rgba(baseline_png)
    cw, ch, c_rgba = decode_png_to_rgba(candidate_png)
    if (bw, bh) != (cw, ch):
        return {
            "passed": False,
            "dimension_mismatch": True,
            "baseline_size": [bw, bh],
            "candidate_size": [cw, ch],
            "diff_pixels": bw * bh,
            "total_pixels": bw * bh,
            "mismatch_ratio": 1.0,
            "rmse": 255.0,
            "diff_bounding_box": None,
            "diff_png_bytes": None,
        }

    total_px = bw * bh
    diff_px = 0
    sq_err_sum = 0.0
    tol = max(0, int(channel_tolerance))
    min_x, min_y = bw, bh
    max_x, max_y = -1, -1
    diff_buf = bytearray(total_px * 4)

    for idx in range(total_px):
        off = idx * 4
        dr = abs(b_rgba[off] - c_rgba[off])
        dg = abs(b_rgba[off + 1] - c_rgba[off + 1])
        db = abs(b_rgba[off + 2] - c_rgba[off + 2])
        da = abs(b_rgba[off + 3] - c_rgba[off + 3])
        sq_err_sum += (dr * dr + dg * dg + db * db + da * da) / 4.0
        if max(dr, dg, db, da) > tol:
            diff_px += 1
            x = idx % bw
            y = idx // bw
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
            diff_buf[off : off + 4] = b"\xff\x4d\x4f\xff"
        else:
            lum = (c_rgba[off] + c_rgba[off + 1] + c_rgba[off + 2]) // 9
            diff_buf[off : off + 4] = bytes((lum, lum, lum, 255))

    ratio = round(diff_px / total_px, 6) if total_px else 0.0
    rmse = round(math.sqrt(sq_err_sum / total_px), 4) if total_px else 0.0
    bbox = {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y} if diff_px > 0 else None
    return {
        "passed": ratio <= float(max_mismatch_ratio),
        "dimension_mismatch": False,
        "width": bw,
        "height": bh,
        "diff_pixels": diff_px,
        "total_pixels": total_px,
        "mismatch_ratio": ratio,
        "max_mismatch_ratio": float(max_mismatch_ratio),
        "rmse": rmse,
        "diff_bounding_box": bbox,
        "diff_png_bytes": encode_rgba_png(bw, bh, diff_buf),
    }


class VRTIsolationManager:
    """Manages per-tab declared-origin network allowlists and visual regression baselines."""

    def __init__(
        self,
        cdp: CDPBridge,
        baselines_dir: Path,
        *,
        redactor: LuminaraRedactor | None = None,
    ) -> None:
        self.cdp = cdp
        self.baselines_dir = baselines_dir.resolve()
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor or DEFAULT_REDACTOR
        self._lock = threading.Lock()
        self._origin_locks: dict[str, set[str]] = {}
        self._blocked_requests: list[dict[str, Any]] = []
        self._total_blocked_egress = 0
        self._vrt_history: list[dict[str, Any]] = []
        if hasattr(self.cdp, "register_fetch_hook"):
            self._unsub = self.cdp.register_fetch_hook(10, "vrt", self._evaluate_fetch_hook)
        else:
            self._unsub = self.cdp.mux.subscribe("Fetch.requestPaused", self._on_standalone_fetch_paused)
        self._unsub_detach = self.cdp.mux.subscribe("Target.detachedFromTarget", self._on_detached)

    def close(self) -> None:
        for fn in (self._unsub, self._unsub_detach):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def _on_detached(self, event: dict[str, Any]) -> None:
        tid = str(event.get("target_id") or "")
        if tid:
            with self._lock:
                self._origin_locks.pop(tid, None)

    def is_request_allowed(self, target_id: str, url: str) -> bool:
        with self._lock:
            allowed = self._origin_locks.get(target_id)
            if allowed is None:
                return True
            allowed_copy = set(allowed)
        parsed = urllib.parse.urlparse(url or "")
        scheme = parsed.scheme.lower()
        if scheme in _SAFE_INLINE_SCHEMES:
            return True
        if scheme in ("http", "https") and parsed.hostname:
            try:
                return normalize_origin(url) in allowed_copy
            except ValueError:
                return False
        return False

    def _evaluate_fetch_hook(self, event: dict[str, Any]) -> str | None:
        """Priority-10 hook on `CDPBridge`: blocks undeclared origins before `NetworkMutationFirewall`."""
        target_id = str(event.get("target_id") or "")
        with self._lock:
            has_lock = target_id in self._origin_locks
        if not has_lock:
            return None
        params = event.get("params") or {}
        req = params.get("request") or {}
        url = str(req.get("url") or "")
        method = str(req.get("method") or "GET").upper()
        if self.is_request_allowed(target_id, url):
            return None

        with self._lock:
            self._total_blocked_egress += 1
            self._blocked_requests.append(
                {
                    "ts_ms": int(time.time() * 1000),
                    "target_id": target_id,
                    "method": method,
                    "url": self.redactor.redact_text(url)[:300],
                    "reason": "undeclared_origin_blocked",
                }
            )
            if len(self._blocked_requests) > 200:
                self._blocked_requests = self._blocked_requests[-200:]
        return "FAIL"

    def _on_standalone_fetch_paused(self, event: dict[str, Any]) -> None:
        """Fallback for lightweight mock CDP stubs in unit tests."""
        params = event.get("params") or {}
        session_id = str(event.get("session_id") or "")
        request_id = str(params.get("requestId") or "")
        if not session_id or not request_id:
            return
        verdict = self._evaluate_fetch_hook(event)
        send_fn = getattr(self.cdp.mux, "send_command_async", None) or getattr(self.cdp.mux, "send", None)
        if not callable(send_fn):
            return
        try:
            if verdict == "FAIL":
                send_fn("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}, session_id=session_id)
            else:
                send_fn("Fetch.continueRequest", {"requestId": request_id}, session_id=session_id)
        except Exception:  # noqa: BLE001
            pass

    def lock_origins(self, target_id: str | None, declared_origins: list[str]) -> dict[str, Any]:
        if not declared_origins:
            raise ValueError("declared_origins must contain at least one http(s) origin")
        normalized = sorted({normalize_origin(o) for o in declared_origins})
        tid = self.cdp._pick_target_id(target_id)
        with self._lock:
            self._origin_locks[tid] = set(normalized)
        if hasattr(self.cdp, "set_fetch_interception"):
            self.cdp.set_fetch_interception(tid, "vrt", enabled=True, url_pattern="*")
        else:
            self.cdp.run_session(
                tid,
                [("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})],
            )
        return {"ok": True, "target_id": tid, "declared_origins": normalized}

    def unlock_origins(self, target_id: str | None) -> dict[str, Any]:
        tid = self.cdp._pick_target_id(target_id)
        with self._lock:
            self._origin_locks.pop(tid, None)
        if hasattr(self.cdp, "set_fetch_interception"):
            self.cdp.set_fetch_interception(tid, "vrt", enabled=False)
        else:
            try:
                self.cdp.run_session(tid, [("Fetch.disable", {})])
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "target_id": tid, "locked": False}

    def capture_baseline(self, baseline_id: str, *, target_id: str | None = None, png_bytes: bytes | None = None) -> dict[str, Any]:
        bid = validate_baseline_id(baseline_id)
        if png_bytes is None:
            resolved_tid, b64 = self.cdp.capture_screenshot(target_id, fmt="png", quality=100)
            raw_png = base64.b64decode(b64)
        else:
            resolved_tid = target_id or ""
            raw_png = png_bytes
        w, h, _ = decode_png_to_rgba(raw_png)
        out_path = self.baselines_dir / f"{bid}.png"
        out_path.write_bytes(raw_png)
        return {
            "ok": True,
            "baseline_id": bid,
            "target_id": resolved_tid,
            "width": w,
            "height": h,
            "bytes": len(raw_png),
            "path": str(out_path),
        }

    def compare_vrt(
        self,
        baseline_id: str,
        *,
        target_id: str | None = None,
        candidate_png_bytes: bytes | None = None,
        max_mismatch_ratio: float = 0.01,
    ) -> dict[str, Any]:
        bid = validate_baseline_id(baseline_id)
        base_path = self.baselines_dir / f"{bid}.png"
        if not base_path.is_file():
            raise ValueError(f"Baseline {bid!r} does not exist; call capture_baseline first")
        if candidate_png_bytes is None:
            resolved_tid, b64 = self.cdp.capture_screenshot(target_id, fmt="png", quality=100)
            cand_png = base64.b64decode(b64)
        else:
            resolved_tid = target_id or ""
            cand_png = candidate_png_bytes

        cmp_res = compare_png_bytes(
            base_path.read_bytes(),
            cand_png,
            max_mismatch_ratio=max_mismatch_ratio,
        )
        diff_bytes = cmp_res.pop("diff_png_bytes", None)
        diff_path_str = ""
        if diff_bytes and cmp_res["diff_pixels"] > 0:
            diff_path = self.baselines_dir / f"{bid}.diff.png"
            diff_path.write_bytes(diff_bytes)
            diff_path_str = str(diff_path)

        entry = {
            "baseline_id": bid,
            "target_id": resolved_tid,
            "ts_ms": int(time.time() * 1000),
            "diff_path": diff_path_str,
            **cmp_res,
        }
        with self._lock:
            self._vrt_history.append(entry)
            if len(self._vrt_history) > 100:
                self._vrt_history = self._vrt_history[-100:]
        return {"ok": True, **entry}

    def status(self) -> dict[str, Any]:
        with self._lock:
            locks = {tid: sorted(origs) for tid, origs in self._origin_locks.items()}
            blocked = list(self._blocked_requests[-25:])
            total_blocked = self._total_blocked_egress
            recent_vrt = list(self._vrt_history[-15:])
        baselines = sorted(
            p.stem for p in self.baselines_dir.glob("*.png") if not p.name.endswith(".diff.png")
        )
        return {
            "origin_locks": locks,
            "blocked_egress_count": total_blocked,
            "recent_blocked_egress": blocked,
            "baselines": baselines,
            "recent_comparisons": recent_vrt,
        }
