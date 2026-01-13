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
    """du -s로 디렉터리 용량 빠르게 계산"""
    try:
        result = subprocess.run(
            ["du", "-sb", "--", path],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode in (0, 1):
            line = result.stdout.strip()
            if line:
                return int(line.split()[0])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return 0

def run_du_parallel(path: str, depth: int) -> List[DuEntry]:
    """병렬 처리로 초고속 디렉토리 스캔 (depth=1만 지원)
    
    find로 디렉토리 목록을 빠르게 얻은 후, 병렬로 du -s 실행하여
    속도와 정확성(권한 문제 없음)을 모두 확보
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if depth != 1:
        # depth > 1은 기존 du 방식 사용
        return run_du(path, depth, one_fs=True, timeout_sec=15)
    
    # 1단계: find로 직계 하위 디렉토리/파일 목록만 빠르게 조회
    # -maxdepth 1: 바로 아래 항목만, -mindepth 1: 자기 자신 제외
    try:
        find_cmd = ["find", path, "-maxdepth", "1", "-mindepth", "1"]
        result = subprocess.run(
            find_cmd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        
        if result.returncode not in (0, 1):
            # find 실패 시 폴백
            return run_du(path, depth=1, one_fs=True, timeout_sec=15)
        
        items = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        
    except (subprocess.TimeoutExpired, Exception):
        # find 실패 시 폴백
        return run_du(path, depth=1, one_fs=True, timeout_sec=15)
    
    if not items:
        # 빈 디렉토리인 경우
        return [DuEntry(path=path, bytes=0)]
    
    # 2단계: 디렉토리는 du -s로, 파일은 du -b로 병렬 조회
    entries = []
    total_size = 0
    
    with ThreadPoolExecutor(max_workers=min(20, len(items))) as executor:
        future_to_path = {
            executor.submit(get_dir_size_du, item): item 
            for item in items
        }
        
        for future in as_completed(future_to_path):
            item_path = future_to_path[future]
            try:
                size = future.result()
                if size >= 0:  # 0도 포함 (빈 디렉토리)
                    entries.append(DuEntry(path=item_path, bytes=size))
                    total_size += size
            except Exception:
                # 개별 항목 실패는 무시
                pass
    
    # 부모 디렉토리 총합 추가
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
