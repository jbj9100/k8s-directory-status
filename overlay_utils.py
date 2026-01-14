from __future__ import annotations
import os
import subprocess
import re
from typing import Optional, Tuple, List, Dict

try:
    from .utils import human_bytes
except ImportError:
    from utils import human_bytes


def get_overlay_upperdirs() -> List[Dict]:
    """
    mountinfo에서 직접 overlay upperdir 목록 추출
    df 없이 바로 각 컨테이너의 writable layer 조회
    
    Returns:
        [{"mountpoint": "/run/containerd/.../rootfs", 
          "upperdir": "/var/lib/containerd/.../diff",
          "container_id": "abc123..."}]
    """
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
                container_id = ""
                if "/k8s.io/" in mountpoint:
                    try:
                        container_id = mountpoint.split("/k8s.io/")[1].split("/")[0][:12]
                    except:
                        container_id = ""
                
                results.append({
                    "mountpoint": mountpoint,
                    "upperdir": upperdir,
                    "container_id": container_id
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
