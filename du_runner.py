from __future__ import annotations
import os, subprocess, time
from dataclasses import dataclass
from typing import Dict, List, Tuple
from .utils import human_bytes, is_safe_abs_path, is_within

@dataclass(frozen=True)
class DuEntry:
    path: str
    bytes: int

class DuCache:
    def __init__(self, ttl_sec: int = 20):
        self.ttl_sec = ttl_sec
        self._cache: Dict[Tuple[str,int,bool], Tuple[float, List[DuEntry]]] = {}

    def get(self, key):
        v = self._cache.get(key)
        if not v:
            return None
        ts, data = v
        if (time.time() - ts) > self.ttl_sec:
            self._cache.pop(key, None)
            return None
        return data

    def set(self, key, data):
        self._cache[key] = (time.time(), data)

def run_du(path: str, depth: int, one_fs: bool, timeout_sec: int) -> List[DuEntry]:
    cmd = ["du", "-B1", f"-d{depth}"]
    if one_fs:
        cmd.append("-x")
    cmd.extend(["--", path])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)
    if p.returncode not in (0, 1):
        raise RuntimeError(p.stderr.strip() or f"du failed ({p.returncode})")
    out: List[DuEntry] = []
    for line in p.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            b = int(parts[0])
        except ValueError:
            continue
        out.append(DuEntry(path=parts[1], bytes=b))
    return out

def list_children_sizes(path: str, depth: int, cache: DuCache, timeout_sec: int, one_fs: bool, allowed_roots: List[str]) -> Dict:
    if not is_safe_abs_path(path):
        raise ValueError("path must be an absolute path")
    if allowed_roots:
        if not any(is_within(r, path) for r in allowed_roots):
            raise PermissionError("path is outside allowed roots")

    key = (os.path.normpath(path), depth, one_fs)
    data = cache.get(key)
    if data is None:
        data = run_du(path, depth=depth, one_fs=one_fs, timeout_sec=timeout_sec)
        cache.set(key, data)

    norm = os.path.normpath(path)
    total = None
    children = []
    for e in data:
        if os.path.normpath(e.path) == norm:
            total = e.bytes
        else:
            children.append(e)
    children.sort(key=lambda x: x.bytes, reverse=True)

    return {
        "path": norm,
        "total_bytes": total,
        "total_human": human_bytes(total or 0),
        "entries": [
            {"path": e.path, "name": os.path.basename(e.path) or e.path, "bytes": e.bytes, "human": human_bytes(e.bytes)}
            for e in children
        ],
    }
