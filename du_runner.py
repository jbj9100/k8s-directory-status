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

def get_dir_size_fast(path: str) -> int:
    """디렉터리 용량을 빠르게 계산 (심볼릭 링크 무시)"""
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += get_dir_size_fast(entry.path)
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return total

def run_du_parallel(path: str, depth: int) -> List[DuEntry]:
    """병렬 처리로 초고속 디렉터리 스캔 (depth=1만 지원)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if depth != 1:
        # depth > 1은 du 사용 (호환성)
        return run_du(path, depth, one_fs=True, timeout_sec=15)
    
    entries = []
    total_size = 0
    
    # 1단계: 하위 디렉터리 목록 수집
    subdirs = []
    files_size = 0
    
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        files_size += entry.stat(follow_symlinks=False).st_size
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    
    total_size += files_size
    
    # 2단계: 병렬로 하위 디렉터리 스캔 (최대 10개 동시)
    if subdirs:
        with ThreadPoolExecutor(max_workers=min(10, len(subdirs))) as executor:
            # 각 디렉터리를 별도 스레드에서 스캔
            future_to_path = {
                executor.submit(get_dir_size_fast, subdir): subdir 
                for subdir in subdirs
            }
            
            for future in as_completed(future_to_path):
                subdir_path = future_to_path[future]
                try:
                    size = future.result()
                    entries.append(DuEntry(path=subdir_path, bytes=size))
                    total_size += size
                except Exception:
                    # 에러 무시하고 계속
                    pass
    
    # 부모 디렉터리 총합 추가
    entries.append(DuEntry(path=path, bytes=total_size))
    return entries

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
