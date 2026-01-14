from __future__ import annotations
import os
import subprocess
from typing import Tuple

try:
    from .utils import human_bytes
except ImportError:
    from utils import human_bytes


def get_actual_mount_size(mountpoint: str, fstype: str = "") -> Tuple[int, str, str]:
    """
    df로 나온 mountpoint 경로에 대해 단순히 du 실행
    
    Returns:
        (bytes, human, status)
        status: "ok" | "skip" | "error"
    """
    # 루트는 du로 재면 너무 큼 -> skip 처리
    if mountpoint in ("/", "/host"):
        return -1, "N/A", "skip"

    timeout_sec = int(os.getenv("DU_TIMEOUT_SEC", "15"))

    # mountpoint가 컨테이너 내부에 없고 /host로만 존재하면 /host prefix 추가
    target_path = mountpoint
    if not os.path.exists(target_path) and os.path.exists("/host" + mountpoint):
        target_path = "/host" + mountpoint

    # 경로 존재 확인
    if not os.path.exists(target_path):
        return -1, "Path not found", "error"

    try:
        # 단순히 du -sh 실행 (df 경로 그대로)
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

        # du 실패
        err = (r.stderr or "").strip()
        return -1, f"du error: {err[:80]}", "error"

    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout_sec}s)", "error"
    except Exception as e:
        return -1, f"Error: {e}", "error"
