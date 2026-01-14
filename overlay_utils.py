from __future__ import annotations
import os
import subprocess
from typing import Optional, Tuple

try:
    from .utils import human_bytes
except ImportError:
    from utils import human_bytes


MOUNTINFO_PATH = "/host/proc/1/mountinfo"


def _strip_host_prefix(p: str) -> str:
    """'/host/...' -> '...' 변환"""
    return p[5:] if p.startswith("/host/") else p


def extract_overlay_upperdir(host_mountpoint: str) -> Optional[str]:
    """
    host mountpoint(예: /run/containerd/.../rootfs) 기준으로
    /host/proc/1/mountinfo에서 upperdir 추출
    
    Args:
        host_mountpoint: 호스트 경로 (예: /run/containerd/.../rootfs)
    
    Returns:
        upperdir 경로 또는 None
    """
    # mountinfo 파일 여러 후보 시도
    mountinfo_candidates = [
        "/host/proc/1/mountinfo",
        "/proc/1/mountinfo",
        "/host/proc/self/mountinfo"
    ]
    
    mountinfo_path = None
    for candidate in mountinfo_candidates:
        if os.path.exists(candidate):
            mountinfo_path = candidate
            break
    
    if not mountinfo_path:
        print(f"[WARN] mountinfo not found in candidates: {mountinfo_candidates}")
        return None
    
    try:
        with open(mountinfo_path, "r") as f:
            for line in f:
                # mountinfo의 mountpoint 필드에 정확히 매칭되는 라인만
                if f" {host_mountpoint} " not in line:
                    continue
                if " - overlay " not in line:
                    continue

                # "... - overlay overlay rw,relatime,lowerdir=...,upperdir=/xxx,workdir=/yyy"
                parts = line.split(" - overlay overlay ", 1)
                if len(parts) != 2:
                    continue
                opts = parts[1].strip()
                for opt in opts.split(","):
                    if opt.startswith("upperdir="):
                        upperdir = opt[len("upperdir="):]
                        print(f"[DEBUG] Found upperdir for {host_mountpoint}: {upperdir}")
                        return upperdir
        return None
    except Exception as e:
        print(f"[ERROR] extract_overlay_upperdir({host_mountpoint}): {e}")
        return None


def get_actual_mount_size(mountpoint: str, fstype: str) -> Tuple[int, str, str]:
    """
    마운트 포인트의 실제 사용량 조회
    
    overlay 마운트: upperdir만 조회
    일반 마운트: 전체 경로 조회
    
    Returns:
        (bytes, human, status)
        status: "ok" | "skip" | "error"
    """
    # 루트는 du로 재면 너무 큼 -> skip 처리
    if mountpoint in ("/", "/host"):
        return -1, "N/A", "skip"

    timeout_sec = int(os.getenv("DU_TIMEOUT_SEC", "15"))
    print(f"[DEBUG] get_actual_mount_size({mountpoint}, {fstype}), timeout={timeout_sec}s")

    # mountpoint가 컨테이너 내부에 없고 /host로만 존재할 수 있어 보정
    mp = mountpoint
    if not os.path.exists(mp) and os.path.exists("/host" + mp):
        mp = "/host" + mp

    target_path = mp

    # overlay면 upperdir만 du로 계산 (컨테이너별 실제 증가분)
    if fstype == "overlay":
        host_mp = _strip_host_prefix(mp)     # /host/run/... -> /run/...
        upperdir = extract_overlay_upperdir(host_mp)
        if not upperdir:
            print(f"[WARN] No upperdir found for {mountpoint}, returning 0")
            return 0, "0 B", "ok"  # upperdir 못 찾으면 0으로(스킵 대상)
        target_path = "/host" + upperdir
        print(f"[DEBUG] Using upperdir: {target_path}")

    # 경로 존재 확인
    if not os.path.exists(target_path):
        print(f"[ERROR] Target path does not exist: {target_path}")
        return -1, f"Path not found: {target_path}", "error"

    try:
        print(f"[DEBUG] Running du on {target_path}...")
        r = subprocess.run(
            ["du", "-sx", "-B1", "--", target_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if r.returncode in (0, 1) and r.stdout.strip():
            size_bytes = int(r.stdout.split()[0])
            print(f"[DEBUG] du success: {size_bytes} bytes")
            return size_bytes, human_bytes(size_bytes), "ok"

        # du 실패
        err = (r.stderr or "").strip()
        print(f"[ERROR] du failed: returncode={r.returncode}, stderr={err[:100]}")
        return -1, f"du error: {err[:80]}", "error"

    except subprocess.TimeoutExpired:
        print(f"[ERROR] du timeout after {timeout_sec}s on {target_path}")
        return -1, f"Timeout ({timeout_sec}s)", "error"
    except Exception as e:
        print(f"[ERROR] Exception in du: {e}")
        return -1, f"Error: {e}", "error"
