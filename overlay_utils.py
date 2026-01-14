from __future__ import annotations
import subprocess
import re
from typing import Optional

def extract_overlay_upperdir(mountpoint: str) -> Optional[str]:
    """
    /proc/1/mountinfo에서 overlay 마운트의 upperdir 추출
    
    Args:
        mountpoint: 마운트 포인트 경로 (예: /run/containerd/.../rootfs)
    
    Returns:
        upperdir 경로 또는 None
    """
    try:
        # 호스트의 mountinfo 읽기
        with open('/host/proc/1/mountinfo', 'r') as f:
            for line in f:
                # 마운트 포인트 매칭
                if f' {mountpoint} ' not in line:
                    continue
                
                # overlay 마운트인지 확인
                if ' - overlay ' not in line:
                    continue
                
                # upperdir 추출
                # 형식: ... - overlay overlay rw,...,upperdir=/path,...
                parts = line.split(' - overlay overlay ')
                if len(parts) < 2:
                    continue
                
                options = parts[1].strip()
                for opt in options.split(','):
                    if opt.startswith('upperdir='):
                        upperdir = opt[9:]  # 'upperdir=' 제거
                        return upperdir
        
        return None
    except Exception as e:
        print(f"Failed to extract upperdir for {mountpoint}: {e}")
        return None


def get_actual_mount_size(mountpoint: str, fstype: str) -> tuple[int, str]:
    """
    마운트 포인트의 실제 사용량 조회
    
    overlay 마운트: upperdir만 조회
    일반 마운트: 전체 경로 조회
    
    Returns:
        (bytes, human_readable_string)
    """
    target_path = mountpoint
    
    # overlay 마운트는 upperdir 추출
    if fstype == 'overlay':
        # mountpoint가 /host로 시작하면 호스트 경로로 변환
        host_mountpoint = mountpoint
        if mountpoint.startswith('/host/'):
            # /host/run/containerd/... → /run/containerd/...
            host_mountpoint = mountpoint[5:]
        
        upperdir = extract_overlay_upperdir(host_mountpoint)
        if upperdir:
            # upperdir는 호스트 절대 경로 → /host prefix 추가
            target_path = f'/host{upperdir}'
            print(f"Overlay {mountpoint} -> upperdir {target_path}")
        else:
            print(f"No upperdir for {mountpoint}, using mountpoint")
    
    # du 실행 (timeout은 환경변수에서)
    import os
    timeout_sec = int(os.getenv('DU_TIMEOUT_SEC', '15'))
    
    try:
        result = subprocess.run(
            ["du", "-sx", "-B1", "--", target_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False
        )
        
        if result.returncode in (0, 1):
            line = result.stdout.strip()
            if line:
                size_bytes = int(line.split()[0])
                return size_bytes, human_bytes(size_bytes)
        
        return 0, "0 B"
    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout_sec}s)"
    except Exception as e:
        return -1, f"Error: {e}"


def human_bytes(size: int) -> str:
    """바이트를 사람이 읽기 쉬운 형태로"""
    if size < 0:
        return "Error"
    if size == 0:
        return "0 B"
    
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"
