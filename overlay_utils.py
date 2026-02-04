from __future__ import annotations
import os
import subprocess
import re
from typing import Tuple, List, Dict

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
            return set(line.strip() for line in r.stdout.strip().split('\n') if line.strip())
        return set()
    except Exception:
        return set()


def get_container_info() -> Dict[str, Dict]:
    """crictl ps로 컨테이너 정보 가져오기 (ID -> {name, pod})"""
    try:
        r = subprocess.run(
            ["crictl", "ps", "--output=json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            import json
            data = json.loads(r.stdout)
            result = {}
            for c in data.get("containers", []):
                cid = c.get("id", "")
                result[cid] = {
                    "name": c.get("metadata", {}).get("name", ""),
                    "pod": c.get("labels", {}).get("io.kubernetes.pod.name", ""),
                    "namespace": c.get("labels", {}).get("io.kubernetes.pod.namespace", ""),
                }
            return result
        return {}
    except Exception:
        return {}


def get_pod_info() -> Dict[str, Dict]:
    """crictl pods로 Pod 정보 가져오기 (pod_uid -> {name, namespace})"""
    try:
        import json
        r = subprocess.run(
            ["crictl", "pods", "--output=json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            result = {}
            for p in data.get("items", []):
                pod_uid = p.get("id", "")
                result[pod_uid] = {
                    "name": p.get("metadata", {}).get("name", ""),
                    "namespace": p.get("metadata", {}).get("namespace", ""),
                }
            return result
        return {}
    except Exception:
        return {}


def get_overlay_upperdirs() -> List[Dict]:
    """
    overlay upperdir 조회 (컨테이너 writable layer)
    crictl ps로 실행 중인 컨테이너만 필터링
    """
    running_ids = get_running_container_ids()
    container_info = get_container_info()
    
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
                
                parts = line.split()
                if len(parts) < 5:
                    continue
                mountpoint = parts[4]
                
                if "/k8s.io/" not in mountpoint:
                    continue
                
                # upperdir 추출
                match = re.search(r"upperdir=([^,\s]+)", line)
                if not match:
                    continue
                upperdir = match.group(1)
                
                # 컨테이너 ID 추출
                container_id_full = ""
                try:
                    container_id_full = mountpoint.split("/k8s.io/")[1].split("/")[0]
                except:
                    continue
                
                # 실행 중인 컨테이너만
                if running_ids and container_id_full not in running_ids:
                    continue
                
                # 컨테이너 이름 가져오기
                info = container_info.get(container_id_full, {})
                
                results.append({
                    "type": "overlay",
                    "container_id": container_id_full[:12],
                    "container_name": info.get("name", ""),
                    "pod": info.get("pod", ""),
                    "namespace": info.get("namespace", ""),
                    "path": upperdir,
                    "mountpoint": mountpoint,
                })
    except Exception:
        pass
    
    return results


def get_emptydir_volumes() -> List[Dict]:
    """
    emptyDir 볼륨 조회 (/var/lib/kubelet/pods/.../volumes/kubernetes.io~empty-dir/...)
    """
    base_path = "/host/var/lib/kubelet/pods"
    if not os.path.exists(base_path):
        return []
    
    # Pod UID -> Pod Name 매핑 정보 가져오기
    pod_info = get_pod_info()
    
    results = []
    try:
        for pod_uid in os.listdir(base_path):
            pod_path = os.path.join(base_path, pod_uid)
            emptydir_base = os.path.join(pod_path, "volumes", "kubernetes.io~empty-dir")
            
            if not os.path.exists(emptydir_base):
                continue
            
            # Pod 정보 가져오기
            info = pod_info.get(pod_uid, {})
            pod_name = info.get("name", "")
            namespace = info.get("namespace", "")
            
            for vol_name in os.listdir(emptydir_base):
                vol_path = os.path.join(emptydir_base, vol_name)
                if os.path.isdir(vol_path):
                    results.append({
                        "type": "emptydir",
                        "container_id": "",
                        "container_name": vol_name,  # emptydir은 볼륨 이름 표시
                        "pod": pod_name,
                        "namespace": namespace,
                        "path": vol_path,
                        "mountpoint": vol_path,
                        "volume_name": vol_name,
                        "pod_uid": pod_uid,
                    })
    except Exception:
        pass
    
    return results


def get_all_writable_paths() -> List[Dict]:
    """overlay upperdir + emptyDir 모두 조회"""
    result = []
    result.extend(get_overlay_upperdirs())
    result.extend(get_emptydir_volumes())
    return result


def get_upperdir_size(path: str, timeout_sec: int = 60) -> Tuple[int, str, str]:
    """경로에 du 실행하여 실제 사용량 조회"""
    target_path = path
    if not path.startswith("/host") and not os.path.exists(path):
        target_path = "/host" + path
    
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
