from __future__ import annotations
import os
import subprocess
from typing import Optional, Tuple

try:
    from .utils import human_bytes
except ImportError:
    from utils import human_bytes


def extract_overlay_upperdir(mountpoint: str) -> Optional[str]:
    """
    overlay upperdir 추출
    
    mountpoint: df에서 가져온 경로 (예: /host/run/containerd/.../rootfs)
    mountinfo에는 호스트 경로로 저장됨 (예: /run/containerd/.../rootfs)
    """
    # /host prefix 제거 (mountinfo는 호스트 경로 기준)
    search_mp = mountpoint
    if search_mp.startswith("/host"):
        search_mp = mountpoint[5:]  # /host 제거
    
    candidates = ["/host/proc/1/mountinfo", "/proc/1/mountinfo"]
    
    mountinfo_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            mountinfo_path = candidate
            break
    
    if not mountinfo_path:
        return None
    
    try:
        with open(mountinfo_path, "r") as f:
            for line in f:
                # mountinfo에는 호스트 경로로 저장됨
                if f" {search_mp} " not in line:
                    continue
                if " - overlay " not in line:
                    continue
                
                parts = line.split(" - overlay overlay ", 1)
                if len(parts) != 2:
                    continue
                
                opts = parts[1].strip()
                for opt in opts.split(","):
                    if opt.startswith("upperdir="):
                        return opt[len("upperdir="):]
        return None
    except Exception:
        return None


def get_actual_mount_size(mountpoint: str, fstype: str = "") -> Tuple[int, str, str]:
    """
    실제 디스크 사용량 조회
    - overlay: upperdir만 (각 Pod의 writable layer) ← 범인 찾기!
    - 일반: 경로 그대로
    """
    if mountpoint in ("/", "/host"):
        return -1, "N/A", "skip"

    timeout_sec = int(os.getenv("DU_TIMEOUT_SEC", "60"))  # 기본 60초
    
    target_path = mountpoint
    
    # overlay면 upperdir만 조회 (핵심!)
    if fstype == "overlay":
        upperdir = extract_overlay_upperdir(mountpoint)
        
        if not upperdir:
            # upperdir 못 찾으면 0 (공유 레이어만 있는 경우)
            return 0, "0 B", "ok"
        
        # upperdir는 호스트 경로이므로 /host prefix 추가
        target_path = "/host" + upperdir
    else:
        # 일반 마운트는 /host prefix 보정
        if not os.path.exists(target_path) and os.path.exists("/host" + mountpoint):
            target_path = "/host" + mountpoint

    if not os.path.exists(target_path):
        return -1, "Not found", "error"

    try:
        r = subprocess.run(
            ["du", "-sx", "-B1", "--", target_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        
        if r.returncode in (0, 1) and r.stdout.strip():
            size_bytes = int(r.stdout.split()[0])
            return size_bytes, human_bytes(size_bytes), "ok"

        err = (r.stderr or "").strip()
        return -1, f"du error: {err[:80]}", "error"

    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout_sec}s)", "error"
    except Exception as e:
        return -1, f"Error: {e}", "error"
