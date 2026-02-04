#!/usr/bin/env python3
"""
워커 노드 용량 확인 스크립트 (단독 실행 가능)

이 파일 하나만으로 워커 노드의 컨테이너/볼륨 용량 정보를 CLI로 확인할 수 있습니다.

실행 예시:
  python3 check_node_storage_standalone.py
  python3 check_node_storage_standalone.py --skip-zero
  python3 check_node_storage_standalone.py --timeout 30

필요 권한:
  - crictl 명령 실행 권한
  - /proc/1/mountinfo 읽기 권한
  - /var/lib/kubelet/pods/ 읽기 권한
  - du 명령 실행 권한
"""
from __future__ import annotations
import os
import subprocess
import re
import argparse
import sys
import json
from typing import Tuple, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================================
# utils.py 통합
# ============================================================================

def human_bytes(n: int) -> str:
    """바이트를 사람이 읽기 쉬운 형태로 변환"""
    if n is None:
        return "-"
    units = ["B","KiB","MiB","GiB","TiB","PiB"]
    v = float(max(n, 0))
    for u in units:
        if v < 1024.0 or u == units[-1]:
            return f"{int(v)} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024.0
    return f"{v:.1f} PiB"


def is_safe_abs_path(p: str) -> bool:
    """안전한 절대 경로인지 확인"""
    if not p or "\x00" in p:
        return False
    if not os.path.isabs(p):
        return False
    return True


def is_within(base: str, target: str) -> bool:
    """target이 base 안에 있는지 확인"""
    base = os.path.normpath(base)
    target = os.path.normpath(target)
    if base == "/":
        return True
    return target == base or target.startswith(base + os.sep)


# ============================================================================
# overlay_utils.py 통합
# ============================================================================

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
        # /host 없이 시도
        base_path = "/var/lib/kubelet/pods"
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


# ============================================================================
# CLI 메인 로직
# ============================================================================

def print_header():
    """테이블 헤더 출력"""
    print("\n" + "="*150)
    print(f"{'Type':<10} {'Container ID':<14} {'Container/Volume Name':<35} {'Pod Name':<40} {'Size':<12} {'Status':<10}")
    print("="*150)


def print_row(item: Dict, show_path: bool = True):
    """데이터 행 출력"""
    type_str = item.get('type', '')
    cid = item.get('container_id', '')[:12]
    cname = item.get('container_name', '')[:34]  # 폭 확대
    pod = item.get('pod', '')[:39]  # 폭 확대
    size = item.get('actual_human', '')
    status = item.get('actual_status', '')
    
    print(f"{type_str:<10} {cid:<14} {cname:<35} {pod:<40} {size:<12} {status:<10}")
    
    # 경로 정보 표시 (전체 경로)
    if show_path:
        path = item.get('path', '')
        if path:
            print(f"           └─ {path}")
            print(f"           {'-' * 135}")  # 구분선


def print_summary(items: List[Dict]):
    """요약 정보 출력"""
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


def main():
    parser = argparse.ArgumentParser(
        description='워커 노드의 컨테이너/볼륨 용량 정보 확인',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s                    # 기본 실행
  %(prog)s --skip-zero        # 0 바이트 항목 제외
  %(prog)s --timeout 30       # du 타임아웃 30초로 설정
  %(prog)s --workers 4        # 병렬 작업 수 4개로 설정
        """
    )
    
    parser.add_argument(
        '--skip-zero',
        action='store_true',
        help='0 바이트 항목 제외'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=60,
        metavar='SEC',
        help='du 명령 타임아웃 (기본: 60초)'
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        default=6,
        metavar='N',
        help='병렬 작업 개수 (기본: 6)'
    )
    
    parser.add_argument(
        '--sort',
        choices=['size', 'name', 'type'],
        default='size',
        help='정렬 기준 (기본: size)'
    )
    
    args = parser.parse_args()
    
    print(f"\n🔍 노드 용량 정보 수집 중...")
    print(f"   - 타임아웃: {args.timeout}초")
    print(f"   - 병렬 작업: {args.workers}개")
    
    # 1. 모든 경로 수집
    items = get_all_writable_paths()
    
    if not items:
        print("\n⚠️  수집된 데이터가 없습니다.")
        print("   - crictl ps로 실행 중인 컨테이너가 있는지 확인하세요.")
        print("   - /var/lib/kubelet/pods/ 경로에 emptyDir 볼륨이 있는지 확인하세요.")
        return
    
    print(f"   - 발견된 항목: {len(items)}개\n")
    
    # 2. 병렬로 용량 측정
    def work(item: dict):
        b, h, st = get_upperdir_size(item["path"], args.timeout)
        return {
            **item,
            'actual_bytes': b,
            'actual_human': h,
            'actual_status': st
        }
    
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(work, item) for item in items]
        
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            
            # skip_zero 옵션 처리
            if args.skip_zero and result.get('actual_status') == 'ok' and result.get('actual_bytes', 0) == 0:
                continue
            
            results.append(result)
            print(f"\r   진행 중: {i}/{len(items)}", end='', flush=True)
    
    print()  # 줄바꿈
    
    if not results:
        print("\n⚠️  표시할 데이터가 없습니다. (모든 항목이 0 바이트이거나 필터링됨)")
        return
    
    # 3. 정렬
    if args.sort == 'size':
        results.sort(key=lambda x: x.get('actual_bytes', -1), reverse=True)
    elif args.sort == 'name':
        results.sort(key=lambda x: x.get('container_name', ''))
    elif args.sort == 'type':
        results.sort(key=lambda x: (x.get('type', ''), -x.get('actual_bytes', -1)))
    
    # 4. 출력
    print_header()
    for result in results:
        print_row(result)
    
    print_summary(results)
    
    # 5. 도움말
    print("💡 사용 팁:")
    print("   - 용량이 큰 항목만 보기: --skip-zero")
    print("   - 빠르게 확인: --timeout 10 --workers 10")
    print("   - 이름순 정렬: --sort name")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
