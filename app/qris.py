"""QRIS payment simulation store and pure-Python ISO-18004 QR Code SVG renderer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
import threading
import time
from typing import Any

from fastapi import HTTPException

QRIS_DEFAULT_TIMEOUT = 300
_PRUNE_AFTER_SECONDS = 1800

# ponytail: single-process in-memory store with global lock for ephemeral 5s QRIS simulations;
# move to Redis or a PostgreSQL table if running multiple Uvicorn workers.
_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}


def _prune_old(now_mono: float) -> None:
    stale = [sid for sid, s in _SESSIONS.items() if now_mono - s["created_mono"] > _PRUNE_AFTER_SECONDS]
    for sid in stale:
        _SESSIONS.pop(sid, None)


def _serialize_session(s: dict[str, Any], now_mono: float) -> dict[str, Any]:
    remaining = max(0.0, round(s["expires_mono"] - now_mono, 2))
    status = s["status"]
    if status == "pending" and remaining <= 0.0:
        status = "expired"
        s["status"] = "expired"
    return {
        "session_id": s["session_id"],
        "status": status,
        "amount": str(s["amount"]),
        "customer_name": s["customer_name"],
        "timeout_seconds": s["timeout_seconds"],
        "remaining_seconds": remaining if status == "pending" else 0.0,
        "created_at": s["created_at"],
        "expires_at": s["expires_at"],
        "paid_at": s["paid_at"],
        "pay_path": f"/pos/qris-pay/{s['session_id']}",
    }


def create_qris_session(
    amount: Decimal,
    customer_name: str,
    user_id: int,
    timeout_seconds: int = QRIS_DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    now_mono = time.monotonic()
    now_dt = datetime.now(timezone.utc)
    sid = f"QRIS-{secrets.token_hex(6).upper()}"
    entry = {
        "session_id": sid,
        "user_id": user_id,
        "amount": Decimal(str(amount)).quantize(Decimal("0.01")),
        "customer_name": customer_name,
        "timeout_seconds": timeout_seconds,
        "status": "pending",
        "created_mono": now_mono,
        "expires_mono": now_mono + timeout_seconds,
        "created_at": now_dt.isoformat(),
        "expires_at": (now_dt + timedelta(seconds=timeout_seconds)).isoformat(),
        "paid_at": None,
    }
    with _LOCK:
        _prune_old(now_mono)
        _SESSIONS[sid] = entry
        return _serialize_session(entry, now_mono)


def get_qris_session(session_id: str) -> dict[str, Any]:
    now_mono = time.monotonic()
    with _LOCK:
        entry = _SESSIONS.get(session_id)
        if not entry:
            raise HTTPException(status_code=404, detail="QRIS session not found")
        return _serialize_session(entry, now_mono)


def pay_qris_session(session_id: str) -> dict[str, Any]:
    now_mono = time.monotonic()
    with _LOCK:
        entry = _SESSIONS.get(session_id)
        if not entry:
            raise HTTPException(status_code=404, detail="QRIS session not found")
        if entry["status"] == "paid":
            return _serialize_session(entry, now_mono)
        if entry["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="QRIS session was cancelled")
        if entry["status"] == "expired" or now_mono >= entry["expires_mono"]:
            entry["status"] = "expired"
            raise HTTPException(status_code=410, detail="QRIS session expired (timeout)")
        entry["status"] = "paid"
        entry["paid_at"] = datetime.now(timezone.utc).isoformat()
        return _serialize_session(entry, now_mono)


def cancel_qris_session(session_id: str) -> dict[str, Any]:
    now_mono = time.monotonic()
    with _LOCK:
        entry = _SESSIONS.get(session_id)
        if not entry:
            raise HTTPException(status_code=404, detail="QRIS session not found")
        if entry["status"] == "pending":
            entry["status"] = "cancelled"
        return _serialize_session(entry, now_mono)


# --- Minimal ISO-18004 QR Code (Byte mode, ECC Level L, Versions 1..5, up to 106 UTF-8 bytes) ---
# (version, size, data_codewords, ec_codewords, alignment_centers)
_QR_VERSIONS: list[tuple[int, int, int, int, list[int]]] = [
    (1, 21, 19, 7, []),
    (2, 25, 34, 10, [6, 18]),
    (3, 29, 55, 15, [6, 22]),
    (4, 33, 80, 20, [6, 26]),
    (5, 37, 108, 26, [6, 30]),
]

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_encode(data: list[int], ec_len: int) -> list[int]:
    gen = [1]
    for i in range(ec_len):
        factor = [1, _GF_EXP[i]]
        nxt = [0] * (len(gen) + 1)
        for j, a in enumerate(gen):
            for k, b in enumerate(factor):
                nxt[j + k] ^= _gf_mul(a, b)
        gen = nxt
    msg = data + [0] * ec_len
    for i in range(len(data)):
        coef = msg[i]
        if coef != 0:
            for j in range(1, len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data) :]


def _format_bits_ecc_l(mask: int) -> int:
    # ECC L = 01 (5-bit payload: (0b01 << 3) | mask)
    data = (0b01 << 3) | mask
    rem = data << 10
    for shift in range(4, -1, -1):
        if rem & (1 << (shift + 10)):
            rem ^= 0x537 << shift
    return ((data << 10) | rem) ^ 0x5412


def _make_qr_matrix(text: str) -> list[list[bool]]:
    payload = text.encode("utf-8")
    spec = None
    for v in _QR_VERSIONS:
        if len(payload) + 2 <= v[2]:
            spec = v
            break
    if spec is None:
        raise ValueError("QR payload exceeds Version 5 ECC-L capacity (106 bytes)")

    ver, size, data_cw, ec_cw, align = spec
    bits: list[int] = []

    def append_bits(val: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            bits.append((val >> shift) & 1)

    append_bits(0b0100, 4)  # Byte mode
    append_bits(len(payload), 8)
    for b in payload:
        append_bits(b, 8)
    cap_bits = data_cw * 8
    append_bits(0, min(4, cap_bits - len(bits)))
    while len(bits) % 8 != 0:
        bits.append(0)
    codewords = [
        int("".join(str(b) for b in bits[i : i + 8]), 2) for i in range(0, len(bits), 8)
    ]
    pad_toggle = 0
    while len(codewords) < data_cw:
        codewords.append(0xEC if pad_toggle == 0 else 0x11)
        pad_toggle ^= 1

    all_cw = codewords + _rs_encode(codewords, ec_cw)
    all_bits: list[int] = []
    for cw in all_cw:
        for shift in range(7, -1, -1):
            all_bits.append((cw >> shift) & 1)

    mat: list[list[bool]] = [[False] * size for _ in range(size)]
    func: list[list[bool]] = [[False] * size for _ in range(size)]

    def set_fn(r: int, c: int, dark: bool) -> None:
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = dark
            func[r][c] = True

    # Finder patterns + separators
    for fr, fc in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = fr + dr, fc + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = 0 <= dr <= 6 and 0 <= dc <= 6
                    on_border = dr in (0, 6) or dc in (0, 6)
                    in_center = 2 <= dr <= 4 and 2 <= dc <= 4
                    set_fn(r, c, in_outer and (on_border or in_center))

    # Alignment patterns
    for ar in align:
        for ac in align:
            if func[ar][ac]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    dark = max(abs(dr), abs(dc)) != 1
                    set_fn(ar + dr, ac + dc, dark)

    # Timing patterns & dark module
    for i in range(8, size - 8):
        if not func[6][i]:
            set_fn(6, i, i % 2 == 0)
        if not func[i][6]:
            set_fn(i, 6, i % 2 == 0)
    set_fn(4 * ver + 9, 8, True)

    # Reserve format info cells
    for i in range(9):
        if i != 6:
            set_fn(8, i, False)
            set_fn(i, 8, False)
    for i in range(8):
        set_fn(8, size - 1 - i, False)
    for i in range(7):
        set_fn(size - 1 - i, 8, False)

    # Zig-zag data placement
    bit_idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not func[r][c]:
                    mat[r][c] = bool(all_bits[bit_idx]) if bit_idx < len(all_bits) else False
                    bit_idx += 1
        col -= 2
        upward = not upward

    # Choose lowest-penalty mask (masks 0..7)
    mask_fns = [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
        lambda r, c: ((r * c) % 2) + ((r * c) % 3) == 0,
        lambda r, c: (((r * c) % 2) + ((r * c) % 3)) % 2 == 0,
        lambda r, c: (((r + c) % 2) + ((r * c) % 3)) % 2 == 0,
    ]

    best_mat = mat
    best_pen = 10**9
    for mask_id, fn in enumerate(mask_fns):
        cand = [row[:] for row in mat]
        for r in range(size):
            for c in range(size):
                if not func[r][c] and fn(r, c):
                    cand[r][c] = not cand[r][c]
        fmt = _format_bits_ecc_l(mask_id)
        # Write format bits (MSB bit 14 -> LSB bit 0)
        c1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
              (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        c2 = [(size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8),
              (size - 5, 8), (size - 6, 8), (size - 7, 8),
              (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5),
              (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1)]
        for i in range(15):
            bit = bool((fmt >> (14 - i)) & 1)
            r1, col1 = c1[i]
            r2, col2 = c2[i]
            cand[r1][col1] = bit
            cand[r2][col2] = bit

        # Lightweight penalty: run lengths + 2x2 blocks + dark ratio balance
        pen = 0
        dark_total = 0
        for r in range(size):
            run_r = 1
            run_c = 1
            for c in range(size):
                if cand[r][c]:
                    dark_total += 1
                if c > 0:
                    if cand[r][c] == cand[r][c - 1]:
                        run_r += 1
                    else:
                        if run_r >= 5:
                            pen += 3 + (run_r - 5)
                        run_r = 1
                    if cand[c][r] == cand[c - 1][r]:
                        run_c += 1
                    else:
                        if run_c >= 5:
                            pen += 3 + (run_c - 5)
                        run_c = 1
                if r + 1 < size and c + 1 < size:
                    v0 = cand[r][c]
                    if cand[r][c + 1] == v0 and cand[r + 1][c] == v0 and cand[r + 1][c + 1] == v0:
                        pen += 3
            if run_r >= 5:
                pen += 3 + (run_r - 5)
            if run_c >= 5:
                pen += 3 + (run_c - 5)
        pct = abs((dark_total * 100) // (size * size) - 50) // 5
        pen += pct * 10
        if pen < best_pen:
            best_pen = pen
            best_mat = cand

    return best_mat


def render_qr_svg(text: str, quiet_zone: int = 3) -> str:
    matrix = _make_qr_matrix(text)
    size = len(matrix)
    total = size + quiet_zone * 2
    parts: list[str] = []
    for r, row in enumerate(matrix):
        y = r + quiet_zone
        c = 0
        while c < size:
            if row[c]:
                start = c
                while c < size and row[c]:
                    c += 1
                parts.append(f"M{start + quiet_zone} {y}h{c - start}v1h-{c - start}z")
            else:
                c += 1
    d = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="210" height="210" shape-rendering="crispEdges" role="img" aria-label="QRIS payment QR code">'
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>'
        f'<path d="{d}" fill="#16241b"/>'
        f"</svg>"
    )
