#!/usr/bin/env python3
"""
대화식 노드 스토리지 체크 도구 (단독 실행 가능)

이 파일 하나로 다음 기능을 모두 수행:
1. Ansible 인벤토리에서 노드 목록 표시
2. 대화식으로 노드 선택
3. 선택한 노드에서 스토리지 체크 실행
4. 결과 실시간 출력

필요 사항:
  - Ansible 설치
  - hosts 인벤토리 파일
  - Python 3.7+
"""
from __future__ import annotations
import os
import sys
import subprocess
import json
import argparse
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================================
# 색상 출력
# ============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_header(msg):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{msg:^80}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 80}{Colors.END}\n")


def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")


def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.END}")


def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.END}")


# ============================================================================
# 스토리지 체크 스크립트 (임베디드)
# ============================================================================

# check_node_storage_standalone.py의 핵심 로직을 임베디드
STORAGE_CHECK_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations
import os
import subprocess
import re
import argparse
import sys
import json
from typing import Tuple, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

def human_bytes(n: int) -> str:
    if n is None:
        return "-"
    units = ["B","KiB","MiB","GiB","TiB","PiB"]
    v = float(max(n, 0))
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{int(v)} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024.0
    return f"{v:.1f} PiB"

def get_running_container_ids() -> set:
    try:
        r = subprocess.run(["crictl", "ps", "-q"], capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0 and r.stdout.strip():
            return set(line.strip() for line in r.stdout.strip().split('\n') if line.strip())
        return set()
    except Exception:
        return set()

def get_container_info() -> Dict[str, Dict]:
    try:
        r = subprocess.run(["crictl", "ps", "--output=json"], capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0 and r.stdout.strip():
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
    try:
        r = subprocess.run(["crictl", "pods", "--output=json"], capture_output=True, text=True, timeout=10, check=False)
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
                match = re.search(r"upperdir=([^,\s]+)", line)
                if not match:
                    continue
                upperdir = match.group(1)
                container_id_full = ""
                try:
                    container_id_full = mountpoint.split("/k8s.io/")[1].split("/")[0]
                except:
                    continue
                if running_ids and container_id_full not in running_ids:
                    continue
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
    base_path = "/host/var/lib/kubelet/pods"
    if not os.path.exists(base_path):
        base_path = "/var/lib/kubelet/pods"
        if not os.path.exists(base_path):
            return []
    pod_info = get_pod_info()
    results = []
    try:
        for pod_uid in os.listdir(base_path):
            pod_path = os.path.join(base_path, pod_uid)
            emptydir_base = os.path.join(pod_path, "volumes", "kubernetes.io~empty-dir")
            if not os.path.exists(emptydir_base):
                continue
            info = pod_info.get(pod_uid, {})
            pod_name = info.get("name", "")
            namespace = info.get("namespace", "")
            for vol_name in os.listdir(emptydir_base):
                vol_path = os.path.join(emptydir_base, vol_name)
                if os.path.isdir(vol_path):
                    results.append({
                        "type": "emptydir",
                        "container_id": "",
                        "container_name": vol_name,
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
    result = []
    result.extend(get_overlay_upperdirs())
    result.extend(get_emptydir_volumes())
    return result

def get_upperdir_size(path: str, timeout_sec: int = 60) -> Tuple[int, str, str]:
    target_path = path
    if not path.startswith("/host") and not os.path.exists(path):
        target_path = "/host" + path
    if not os.path.exists(target_path):
        return -1, "Not found", "error"
    try:
        r = subprocess.run(["du", "-sx", "-B1", "--", target_path], capture_output=True, text=True, timeout=timeout_sec, check=False)
        if r.returncode in (0, 1) and r.stdout.strip():
            size_bytes = int(r.stdout.split()[0])
            return size_bytes, human_bytes(size_bytes), "ok"
        err = (r.stderr or "").strip()
        return -1, f"du error: {err[:80]}", "error"
    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout_sec}s)", "error"
    except Exception as e:
        return -1, f"Error: {e}", "error"

def print_header():
    print("\n" + "="*150)
    print(f"{'Type':<10} {'Container ID':<14} {'Container/Volume Name':<35} {'Pod Name':<40} {'Size':<12} {'Status':<10}")
    print("="*150)

def print_row(item: Dict, show_path: bool = True):
    type_str = item.get('type', '')
    cid = item.get('container_id', '')[:12]
    cname = item.get('container_name', '')[:34]
    pod = item.get('pod', '')[:39]
    size = item.get('actual_human', '')
    status = item.get('actual_status', '')
    print(f"{type_str:<10} {cid:<14} {cname:<35} {pod:<40} {size:<12} {status:<10}")
    if show_path:
        path = item.get('path', '')
        if path:
            print(f"           └─ {path}")
            print(f"           {'-' * 135}")

def print_summary(items: List[Dict]):
    total_bytes = 0
    overlay_count = 0
    emptydir_count = 0
    error_count = 0
    for item in items:
        if item.get('actual_status') == 'ok':
            total_bytes += item.get('actual_bytes', 0)
        else:
            error_count += 1
        if item.get('type') == 'overlay':
            overlay_count += 1
        elif item.get('type') == 'emptydir':
            emptydir_count += 1
    print("="*150)
    print(f"\n📊 요약:")
    print(f"  - Overlay (컨테이너 writable layer): {overlay_count}개")
    print(f"  - EmptyDir 볼륨: {emptydir_count}개")
    print(f"  - 총 용량: {human_bytes(total_bytes)}")
    print(f"  - 오류: {error_count}개")
    print()

parser = argparse.ArgumentParser()
parser.add_argument('--skip-zero', action='store_true')
parser.add_argument('--timeout', type=int, default=60)
parser.add_argument('--workers', type=int, default=6)
parser.add_argument('--sort', choices=['size', 'name', 'type'], default='size')
parser.add_argument('--min-size', type=int, default=0)
parser.add_argument('--no-summary', action='store_true')
parser.add_argument('--quiet', action='store_true')
args = parser.parse_args()

if not args.quiet:
    print(f"\n🔍 노드 용량 정보 수집 중...")
    print(f"   - 타임아웃: {args.timeout}초")
    print(f"   - 병렬 작업: {args.workers}개")

items = get_all_writable_paths()
if not items:
    print("\n⚠️  수집된 데이터가 없습니다.")
    sys.exit(0)

if not args.quiet:
    print(f"   - 발견된 항목: {len(items)}개\n")

def work(item: dict):
    b, h, st = get_upperdir_size(item["path"], args.timeout)
    return {**item, 'actual_bytes': b, 'actual_human': h, 'actual_status': st}

results = []
with ThreadPoolExecutor(max_workers=args.workers) as executor:
    futures = [executor.submit(work, item) for item in items]
    for i, future in enumerate(as_completed(futures), 1):
        result = future.result()
        if result.get('actual_status') == 'ok':
            size_bytes = result.get('actual_bytes', 0)
            if args.skip_zero and size_bytes == 0:
                continue
            if args.min_size > 0 and size_bytes < args.min_size:
                continue
        results.append(result)

print()
if not results:
    print("\n⚠️  표시할 데이터가 없습니다.")
    sys.exit(0)

if args.sort == 'size':
    results.sort(key=lambda x: x.get('actual_bytes', -1), reverse=True)
elif args.sort == 'name':
    results.sort(key=lambda x: x.get('container_name', ''))
elif args.sort == 'type':
    results.sort(key=lambda x: (x.get('type', ''), -x.get('actual_bytes', -1)))

print_header()
for result in results:
    print_row(result)
if not args.no_summary:
    print_summary(results)
'''



# ============================================================================
# Ansible 관련 함수
# ============================================================================

def get_inventory_hosts(inventory_file, target='all'):
    """Ansible 인벤토리에서 호스트 목록 가져오기"""
    try:
        cmd = f"ansible {target} -i {inventory_file} --list-hosts"
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            print_error(f"Failed to retrieve host list: {result.stderr}")
            return []
        
        hosts = []
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and not line.startswith('hosts ('):
                hosts.append(line)
        
        return hosts
    
    except Exception as e:
        print_error(f"Error retrieving host list: {e}")
        return []


def get_available_groups(inventory_file):
    """Get available groups from Ansible inventory"""
    try:
        cmd = f"ansible-inventory -i {inventory_file} --list"
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            return []
        
        data = json.loads(result.stdout)
        groups = [g for g in data.keys() if not g.startswith('_')]
        return groups
    
    except:
        return []


def select_target(inventory_file, watch_mode=False):
    """Show and select target hosts"""
    print_header("Select Node")
    
    # Get all hosts
    all_hosts = get_inventory_hosts(inventory_file, 'all')
    
    if not all_hosts:
        print_error("Failed to retrieve host list.")
        return None, []
    
    # Show host list
    print(f"{Colors.CYAN}Available Nodes:{Colors.END}\n")
    for i, host in enumerate(all_hosts, 1):
        print(f"  {i}. {host}")
    
    # Show selection method (differs based on watch mode)
    print(f"\n{Colors.CYAN}Selection Method:{Colors.END}")
    if watch_mode:
        print(f"  - Single selection: Enter number (e.g., 3)")
        print(f"{Colors.YELLOW}  ※ Only single node selection is allowed in Watch Mode.{Colors.END}")
    else:
        print(f"  - Single selection: Enter number (e.g., 3)")
        print(f"  - Multiple selection: Comma separated (e.g., 1,3,5)")
        print(f"  - Select All: all")
    
    while True:
        choice = input(f"\n{Colors.YELLOW}Select> {Colors.END}").strip().lower()
        
        # 'all' and multiple selection invalid in Watch Mode
        if choice == 'all':
            if watch_mode:
                print_error("Only single node selection is allowed in Watch Mode.")
                continue
            return 'all', all_hosts
        
        # Select by number
        selected = []
        try:
            nums = choice.split(',')
            
            # Multiple selection check for Watch Mode
            if watch_mode and len(nums) > 1:
                print_error("Only single node selection is allowed in Watch Mode.")
                continue
            
            for num in nums:
                num = num.strip()
                if num.isdigit():
                    idx = int(num) - 1
                    if 0 <= idx < len(all_hosts):
                        selected.append(all_hosts[idx])
                    else:
                        print_error(f"Invalid number: {num}")
            
            if selected:
                return 'custom', selected
            else:
                print_error("No valid host selected. Please try again.")
        
        except Exception as e:
            print_error(f"Input error: {e}. Please try again.")




def run_check_on_hosts(inventory_file, hosts, script_args, quiet=False, return_output=False):
    """Run storage c# ============================================================================
# Storage Check Script (Embedded)
# ============================================================================

# Embedded check_node_storage_standalone.py logic
STORAGE_CHECK_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations
import os
import subprocess
import re
import argparse
import sys
import json
from typing import Tuple, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

def human_bytes(n: int) -> str:
    if n is None:
        return "-"
    units = ["B","KiB","MiB","GiB","TiB","PiB"]
    v = float(max(n, 0))
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{int(v)} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024.0
    return f"{v:.1f} PiB"

def get_running_container_ids() -> set:
    try:
        r = subprocess.run(["crictl", "ps", "-q"], capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0 and r.stdout.strip():
            return set(line.strip() for line in r.stdout.strip().split('\n') if line.strip())
        return set()
    except Exception:
        return set()

def get_container_info() -> Dict[str, Dict]:
    try:
        r = subprocess.run(["crictl", "ps", "--output=json"], capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0 and r.stdout.strip():
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
    try:
        r = subprocess.run(["crictl", "pods", "--output=json"], capture_output=True, text=True, timeout=10, check=False)
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
                match = re.search(r"upperdir=([^,\s]+)", line)
                if not match:
                    continue
                upperdir = match.group(1)
                container_id_full = ""
                try:
                    container_id_full = mountpoint.split("/k8s.io/")[1].split("/")[0]
                except:
                    continue
                if running_ids and container_id_full not in running_ids:
                    continue
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

def get_pod_volumes() -> List[Dict]:
    base_path = "/host/var/lib/kubelet/pods"
    if not os.path.exists(base_path):
        base_path = "/var/lib/kubelet/pods"
        if not os.path.exists(base_path):
            return []
    
    pod_info = get_pod_info()
    results = []
    try:
        for pod_uid in os.listdir(base_path):
            pod_vol_path = os.path.join(base_path, pod_uid, "volumes")
            if not os.path.exists(pod_vol_path):
                continue
            info = pod_info.get(pod_uid, {})
            pod_name = info.get("name", "")
            namespace = info.get("namespace", "")
            for plugin_name in os.listdir(pod_vol_path):
                plugin_path = os.path.join(pod_vol_path, plugin_name)
                if not os.path.isdir(plugin_path):
                    continue
                vol_type = plugin_name.replace("kubernetes.io~", "")
                for vol_name in os.listdir(plugin_path):
                    vol_path = os.path.join(plugin_path, vol_name)
                    if os.path.isdir(vol_path):
                        results.append({
                            "type": vol_type,
                            "container_id": "",
                            "container_name": vol_name,
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
    result = []
    result.extend(get_overlay_upperdirs())
    result.extend(get_pod_volumes())
    return result

def get_upperdir_size(path: str, timeout_sec: int = 60) -> Tuple[int, str, str]:
    target_path = path
    if not path.startswith("/host") and not os.path.exists(path):
        target_path = "/host" + path
    if not os.path.exists(target_path):
        return -1, "Not found", "error"
    try:
        r = subprocess.run(["du", "-sx", "-B1", "--", target_path], capture_output=True, text=True, timeout=timeout_sec, check=False)
        if r.returncode in (0, 1) and r.stdout.strip():
            size_bytes = int(r.stdout.split()[0])
            return size_bytes, human_bytes(size_bytes), "ok"
        err = (r.stderr or "").strip()
        return -1, f"du error: {err[:80]}", "error"
    except subprocess.TimeoutExpired:
        return -1, f"Timeout ({timeout_sec}s)", "error"
    except Exception as e:
        return -1, f"Error: {e}", "error"

def print_header():
    print("\n" + "="*150)
    print(f"{'Type':<10} {'Container ID':<14} {'Container/Volume Name':<35} {'Pod Name':<40} {'Size':<12} {'Status':<10}")
    print("="*150)

def print_row(item: Dict, show_path: bool = True):
    type_str = item.get('type', '')
    cid = item.get('container_id', '')[:12]
    cname = item.get('container_name', '')[:34]
    pod = item.get('pod', '')[:39]
    size = item.get('actual_human', '')
    status = item.get('actual_status', '')
    print(f"{type_str:<10} {cid:<14} {cname:<35} {pod:<40} {size:<12} {status:<10}")
    if show_path:
        path = item.get('path', '')
        if path:
            print(f"           └─ {path}")
            print(f"           {'-' * 135}")

def print_summary(items: List[Dict]):
    total_bytes = 0
    vol_count = 0
    overlay_count = 0
    error_count = 0
    for item in items:
        if item.get('actual_status') == 'ok':
            total_bytes += item.get('actual_bytes', 0)
        else:
            error_count += 1
        if item.get('type') == 'overlay':
            overlay_count += 1
        else:
            vol_count += 1
    print("="*150)
    print(f"\n📊 Summary:")
    print(f"  - Overlay (Container): {overlay_count}")
    print(f"  - Volumes (PVC/EmptyDir etc.): {vol_count}")
    print(f"  - Total Size: {human_bytes(total_bytes)}")
    print(f"  - Errors: {error_count}")
    print()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-zero', action='store_true')
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--sort', choices=['size', 'name', 'type'], default='size')
    parser.add_argument('--min-size', type=int, default=0)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--no-summary', action='store_true')
    args = parser.parse_args()
    
    if not args.quiet:
        print(f"\n🔍 Collecting node storage info...")
        print(f"   - Timeout: {args.timeout}s")
        print(f"   - Parallel Workers: {args.workers}")
    
    items = get_all_writable_paths()
    if not items:
        if not args.quiet:
            print("\n⚠️  No data collected.")
        sys.exit(0)
    
    if not args.quiet:
        print(f"   - Found items: {len(items)}\n")
    
    def work(item: dict):
        b, h, st = get_upperdir_size(item["path"], args.timeout)
        return {**item, 'actual_bytes': b, 'actual_human': h, 'actual_status': st}
    
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(work, item) for item in items]
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result.get('actual_status') == 'ok':
                size_bytes = result.get('actual_bytes', 0)
                if args.skip_zero and size_bytes == 0:
                    continue
                if args.min_size > 0 and size_bytes < args.min_size:
                    continue
            results.append(result)
            if not args.quiet:
                print(f"\r   Progress: {i}/{len(items)}", end='', flush=True)
    
    if not args.quiet:
        print()
    
    if not results:
        if not args.quiet:
            print("\n⚠️  No data to display.")
        return
    
    if args.sort == 'size':
        results.sort(key=lambda x: x.get('actual_bytes', -1), reverse=True)
    elif args.sort == 'name':
        results.sort(key=lambda x: x.get('container_name', ''))
    elif args.sort == 'type':
        results.sort(key=lambda x: (x.get('type', ''), -x.get('actual_bytes', -1)))
    
    print_header()
    for result in results:
        print_row(result)
    
    if not args.quiet and not args.no_summary:
        print_summary(results)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception:
        sys.exit(1)
'''   
    # Comma separated hosts
    host_pattern = ','.join(hosts)
    
    if not quiet and not return_output:
        print_info("Executing script (no remote file creation)...\n")
    
    # Hide Ansible warnings
    cmd = (
        f"ANSIBLE_LOCALHOST_WARNING=False ANSIBLE_INVENTORY_UNPARSED_WARNING=False "
        f"ansible {host_pattern} -i {inventory_file} "
        f"-m shell -a \"echo '{script_b64}' | base64 -d | python3 - {script_args}\" "
        f"--become"
    )
    
    # Real-time output
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    output = []
    
    if return_output:
        # Buffered mode: collect all at once
        stdout, stderr = process.communicate()
        return stdout
    else:
        # Streaming mode
        for line in iter(process.stdout.readline, ''):
            if line:
                print(line, end='')
                output.append(line)
        process.wait()
    
    # Save results (Normal mode only)
    if not quiet:
        output_dir = Path('./storage_check_results')
        output_dir.mkdir(exist_ok=True)
        
        # Include hostname in filename
        if len(hosts) == 1:
            # Single host: result_DATE_HOSTNAME.txt
            hostname = hosts[0]
            result_file = output_dir / f"result_{timestamp}_{hostname}.txt"
        else:
            # Multiple hosts: result_DATE_multiple-Nhosts.txt
            result_file = output_dir / f"result_{timestamp}_multiple-{len(hosts)}hosts.txt"
        
        with open(result_file, 'w') as f:
            f.writelines(output)
        
        print_success(f"\nResults saved: {result_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Kubernetes Node Storage Check Tool - Check container & volume usage on remote nodes via Ansible',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Usage Examples:
  # Interactive run (default)
  %(prog)s
  
  # Use specific inventory file
  %(prog)s -i my-hosts
  
  # Real-time monitoring mode (10 second interval)
  %(prog)s --watch --interval 10
  
  # Exclude 0 byte items
  %(prog)s --skip-zero
  
  # Set timeout to 30 seconds
  %(prog)s --timeout 30

Filter Options:
  Use 1 GiB / 100 MiB filters when selecting Watch Mode in interactive menu
        '''
    )
    
    parser.add_argument(
        '-i', '--inventory',
        default='hosts',
        metavar='FILE',
        help='Ansible inventory file path (default: hosts)'
    )
    
    parser.add_argument(
        '--skip-zero',
        action='store_true',
        help='Skip 0 byte items'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=60,
        metavar='SEC',
        help='du command timeout (seconds, default: 60)'
    )
    
    parser.add_argument(
        '--watch',
        action='store_true',
        help='Enable Watch Mode (periodic refresh, stop with Ctrl+C)'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        metavar='SEC',
        help='Watch Mode refresh interval (seconds, default: 5, used with --watch)'
    )
    
    parser.add_argument(
        '--min-size',
        type=int,
        default=0,
        help='Minimum size filter (bytes, e.g., 1073741824 = 1GiB)'
    )
    
    args = parser.parse_args()
    
    # Check file
    if not os.path.exists(args.inventory):
        print_error(f"Inventory file not found: {args.inventory}")
        sys.exit(1)
    
    print_header("Node Storage Check Tool")
    print_info(f"Inventory: {args.inventory}")
    
    # Show menu if not specified via --watch
    if not args.watch and sys.stdin.isatty():
        print(f"\n{Colors.CYAN}Select Mode:{Colors.END}")
        print(f"  1. Normal Check (Run once)")
        print(f"  2. Watch Mode (Real-time monitoring)")
        
        while True:
            mode_choice = input(f"\n{Colors.YELLOW}Select (1/2): {Colors.END}").strip()
            if mode_choice == '1':
                watch_mode = False
                break
            elif mode_choice == '2':
                watch_mode = True
                # Interval input
                interval_input = input(f"{Colors.YELLOW}Refresh Interval (sec, default 5): {Colors.END}").strip()
                if interval_input.isdigit():
                    args.interval = int(interval_input)
                break
            else:
                print_error("Please enter 1 or 2.")
        
        # Filter Options (Common)
        print(f"\n{Colors.CYAN}Filter Options:{Colors.END}")
        print(f"  1. Show All")
        print(f"  2. Show 1 GiB+")
        print(f"  3. Show 100 MiB+")
        
        while True:
            filter_choice = input(f"{Colors.YELLOW}Select (1/2/3, default 1): {Colors.END}").strip()
            if not filter_choice or filter_choice == '1':
                min_size_gb = 0
                break
            elif filter_choice == '2':
                min_size_gb = 1  # 1 GiB
                break
            elif filter_choice == '3':
                min_size_gb = 0.1  # 100 MiB
                break
            else:
                print_error("Please select 1, 2, or 3.")

    else:
        watch_mode = args.watch
        min_size_gb = 0
        # If min-size passed via CLI
        if args.min_size > 0:
            min_size_gb = args.min_size / (1024 * 1024 * 1024)
    
    if watch_mode:
        print_info(f"Mode: Real-time Monitoring (Interval: {args.interval}s)")
        print_info("Stop: Ctrl+C\n")
    
    # Select Target (pass watch_mode)
    target, hosts = select_target(args.inventory, watch_mode)
    
    if not hosts:
        print_error("No host selected.")
        sys.exit(1)
    
    print(f"\n{Colors.GREEN}Selected Hosts ({len(hosts)}):{Colors.END}")
    for host in hosts:
        print(f"  - {host}")
    
    # Confirmation
    confirm = input(f"\n{Colors.YELLOW}Proceed? (y/n): {Colors.END}").lower().strip()
    if confirm not in ['y', 'yes']:
        print_error("Cancelled.")
        sys.exit(0)
    
    # Build script arguments
    script_args = f"--timeout {args.timeout}"
    if args.skip_zero:
        script_args += " --skip-zero"
    
    # Apply Filter Options (All modes)
    if min_size_gb > 0:
        min_size_bytes = int(min_size_gb * 1024 * 1024 * 1024)
        script_args += f" --min-size {min_size_bytes}"
    elif args.min_size > 0:
         script_args += f" --min-size {args.min_size}"

    # Hide summary and header in Watch Mode
    if watch_mode:
        script_args += " --no-summary --quiet"
    
    # Watch Mode
    if watch_mode:
        import time
        iteration = 0
        try:
            # Clear screen immediately on first run
            os.system('cls' if os.name == 'nt' else 'clear')
            
            while True:
                iteration += 1
                
                # Collect data (before clearing screen)
                output = run_check_on_hosts(args.inventory, hosts, script_args, quiet=True, return_output=True)
                
                # Clear screen after collection (atomic refresh)
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # Header info
                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"{Colors.CYAN}[Live Monitoring #{iteration}] {current_time} - Interval: {args.interval}s - Stop: Ctrl+C{Colors.END}\n")
                
                # Print output
                if output:
                    print(output)
                
                # Footer wait message
                print(f"\n{Colors.YELLOW}Waiting for next update... ({args.interval}s){Colors.END}", end='', flush=True)
                
                time.sleep(args.interval)
        
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}⚠ Watch Mode Stopped{Colors.END}")
            sys.exit(0)
    
    # Normal Mode (run once)
    else:
        run_check_on_hosts(args.inventory, hosts, script_args)
        print_header("Completed")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}⚠ Interrupted by user.{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}❌ Error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
