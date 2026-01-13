from __future__ import annotations
import os

def human_bytes(n: int) -> str:
    if n is None:
        return "-"
    units = ["B","KiB","MiB","GiB","TiB","PiB"]
    v = float(max(n, 0))
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{int(v)} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024.0
    return f"{v:.1f} PiB"

def is_safe_abs_path(p: str) -> bool:
    if not p or "\x00" in p:
        return False
    if not os.path.isabs(p):
        return False
    # Windows (C:\) 및 Linux (/) 모두 지원
    return True

def is_within(base: str, target: str) -> bool:
    base = os.path.normpath(base)
    target = os.path.normpath(target)
    if base == "/":
        return True
    return target == base or target.startswith(base + os.sep)
