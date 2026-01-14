from __future__ import annotations
import os
import subprocess
import re
from typing import Optional, Tuple, List, Dict

try:
    from .utils import human_bytes
except ImportError:
    from utils import human_bytes


def get_running_container_ids() -> set:
    """crictl ps로 실행 중인 컨테이너 ID 목록 가져오기"""
    try:
        r = subprocess.run(
            ["crictl", "ps", "-q"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            # 전체 ID 반환 (12자 prefix도 매칭 가능하게)
            return set(line.strip() for line in r.stdout.strip().split('\n') if line.strip())
        return set()
    except Exception:
        return set()


def get_overlay_upperdirs() -> List[Dict]:
    """
    mountinfo에서 직접 overlay upperdir 목록 추출
    crictl ps로 실행 중인 컨테이너만 필터링
    
    Returns:
        [{"mountpoint": "/run/containerd/.../rootfs", 
          "upperdir": "/var/lib/containerd/.../diff",
          "container_id": "abc123..."}]
    """
    # 실행 중인 컨테이너 ID 목록
    running_ids = get_running_container_ids()
    
    candidates = ["/host/proc/1/mountinfo", "/proc/1/mountinfo"]
    
    mountinfo_path = None
    for candidate in candidates:
        if os.path.exists(candidate):
            mountinfo_path = candidate
            break
    
    if not mountinfo_path:
        return []
    
    results = []
    try:
        with open(mountinfo_path, "r") as f:
            for line in f:
                if " - overlay " not in line:
                    continue
                
                # mountpoint 추출 (5번째 필드)
                parts = line.split()
                if len(parts) < 5:
                    continue
                mountpoint = parts[4]
                
                # k8s.io 컨테이너만 (containerd)
                if "/k8s.io/" not in mountpoint:
                    continue
                
                # upperdir 추출
                match = re.search(r"upperdir=([^,\s]+)", line)
                if not match:
                    continue
                upperdir = match.group(1)
                
                # 컨테이너 ID 추출 (경로에서)
                # /run/containerd/io.containerd.runtime.v2.task/k8s.io/{container_id}/rootfs
                container_id_full = ""
                container_id_short = ""
                if "/k8s.io/" in mountpoint:
                    try:
                        container_id_full = mountpoint.split("/k8s.io/")[1].split("/")[0]
                        container_id_short = container_id_full[:12]
                    except:
                        pass
                
                # 실행 중인 컨테이너만 (crictl ps로 필터링)
                if running_ids and container_id_full not in running_ids:
                    continue
                
                results.append({
                    "mountpoint": mountpoint,
                    "upperdir": upperdir,
                    "container_id": container_id_short
                })
    except Exception:
        pass
    
    return results


def get_upperdir_size(upperdir: str, timeout_sec: int = 60) -> Tuple[int, str, str]:
    """
    upperdir에 du 실행하여 실제 사용량 조회
    
    Returns:
        (bytes, human, status)
    """
    target_path = "/host" + upperdir if not upperdir.startswith("/host") else upperdir
    
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
