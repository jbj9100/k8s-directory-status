from __future__ import annotations
import os, subprocess, time
from dataclasses import dataclass
from typing import Dict, List, Tuple
try:
    from .utils import human_bytes, is_safe_abs_path, is_within
except ImportError:
    from utils import human_bytes, is_safe_abs_path, is_within

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

def get_dir_size_du(path: str) -> int:
    """du -s로 디렉터리 용량 빠르게 계산
    
    -s: 요약 (하위 디렉토리별 출력 안 함)
    -b: 바이트 단위
    """
    try:
        result = subprocess.run(
            ["du", "-sb", "--", path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        if result.returncode in (0, 1):
            line = result.stdout.strip()
            if line:
                size = int(line.split()[0])
                return size
        # 디버깅: stderr 출력
        if result.stderr:
            import sys
            print(f"du warning for {path}: {result.stderr.strip()}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        import sys
        print(f"du timeout for {path}", file=sys.stderr)
    except (ValueError, IndexError) as e:
        import sys
        print(f"du parse error for {path}: {e}", file=sys.stderr)
    return 0

def run_du_parallel(path: str, depth: int) -> List[DuEntry]:
    """디렉토리 스캔
    
    du -d{depth} -x -B1을 사용하여 정확하고 빠른 크기 계산
    find + 개별 du -s 방식은 du의 블록 계산 로직을 보존하지 못해 부정확
    """
    # 모든 경우에 du 명령어 직접 사용 (가장 정확하고 안정적)
    return run_du(path, depth=depth, one_fs=True, timeout_sec=15)

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
        # 병렬 처리로 초고속 스캔 (depth=1만)
        if depth == 1:
            data = run_du_parallel(path, depth)
        else:
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
