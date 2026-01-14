from __future__ import annotations
from typing import List, Dict, Any
import psutil
import subprocess
import re

# The original human_bytes import is replaced by a local definition later.
# The user's provided code had a typo in the except block for human_bytes,
# and then defined a new human_bytes function.
# To ensure get_mounts_fallback uses the intended human_bytes,
# the local human_bytes is defined before get_mounts_fallback.

def human_bytes(size: int) -> str:
    """바이트를 사람이 읽기 쉬운 형태로 변환"""
    if size < 0:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"

def get_mounts_fallback():
    """psutil 기반 fallback"""
    mounts = []
    for partition in psutil.disk_partitions(all=True):
        # 필터링 (컨테이너 내부에서는 /host/* 경로)
        mp = partition.mountpoint
        if not (mp == '/' or 
                mp.startswith('/host/var/lib/containerd') or
                mp.startswith('/host/var/lib/kubelet') or
                mp.startswith('/host/var/lib/containers') or
                mp.startswith('/host/run/containerd')):
            continue
        
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            mounts.append({
                'device': partition.device,
                'fstype': partition.fstype,
                'total_h': human_bytes(usage.total),
                'used_h': human_bytes(usage.used),
                'free_h': human_bytes(usage.free),
                'percent': int(usage.percent),
                'mountpoint': partition.mountpoint
            })
        except (PermissionError, FileNotFoundError):
            continue
    return mounts

def get_mounts():
    """df + awk로 필터링된 마운트 포인트 조회"""
    try:
        # 컨테이너 내부에서는 /host/* 경로로 마운트됨
        cmd = (
            "df -hT --output=source,fstype,size,used,avail,pcent,target | "
            "awk 'NR==1 || $7==\"/\" || "
            "$7 ~ \"^/host/var/lib/containerd\" || "
            "$7 ~ \"^/host/var/lib/kubelet\" || "
            "$7 ~ \"^/host/var/lib/containers\" || "
            "$7 ~ \"^/host/run/containerd\"'"
        )
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            # fallback to psutil
            return get_mounts_fallback()
        
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return get_mounts_fallback()
        
        mounts = []
        for line in lines[1:]:  # 헤더 스킵
            parts = line.split()
            if len(parts) >= 7:
                # 마지막 컬럼이 target (여러 단어일 수 있음)
                target = ' '.join(parts[6:])
                
                # 퍼센트 제거
                percent_str = parts[5].rstrip('%')
                try:
                    percent = int(percent_str)
                except ValueError: # Changed from bare except to specific ValueError
                    percent = 0
                
                mounts.append({
                    'device': parts[0],
                    'fstype': parts[1],
                    'total_h': parts[2],
                    'used_h': parts[3],
                    'free_h': parts[4],
                    'percent': percent,
                    'mountpoint': target
                })
        
        return mounts
        
    except Exception as e:
        print(f"df command failed: {e}, fallback to psutil")
        return get_mounts_fallback()
