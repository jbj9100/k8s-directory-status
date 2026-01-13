from __future__ import annotations
from typing import List, Dict, Any
import psutil
from .utils import human_bytes

def get_mounts() -> List[Dict[str, Any]]:
    parts = psutil.disk_partitions(all=True)
    out = []
    for p in parts:
        mp = p.mountpoint
        try:
            u = psutil.disk_usage(mp)
        except Exception:
            continue
        out.append({
            "device": p.device,
            "mountpoint": mp,
            "fstype": p.fstype,
            "opts": p.opts,
            "total": u.total, "used": u.used, "free": u.free, "percent": u.percent,
            "total_h": human_bytes(u.total),
            "used_h": human_bytes(u.used),
            "free_h": human_bytes(u.free),
        })
    out.sort(key=lambda x: (0 if x["mountpoint"] == "/" else 1, x["mountpoint"]))
    return out
