from __future__ import annotations
import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

try:
    from .mounts import get_mounts
    from .du_runner import DuCache, list_children_sizes
    from .utils import human_bytes
except ImportError:
    from mounts import get_mounts
    from du_runner import DuCache, list_children_sizes
    from utils import human_bytes

DU_TIMEOUT_SEC = int(os.getenv("DU_TIMEOUT_SEC", "15"))
DU_CACHE_TTL_SEC = int(os.getenv("DU_CACHE_TTL_SEC", "180"))  # 3분
DU_ONE_FS = os.getenv("DU_ONE_FS", "1") not in ("0","false","False")
ALLOWED_ROOTS = [p.strip() for p in os.getenv("ALLOWED_ROOTS", "").split(",") if p.strip()]

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app = FastAPI(title="DF/DU UI", version="0.1")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

cache = DuCache(ttl_sec=DU_CACHE_TTL_SEC)

SHORTCUTS = [
    {"label": "containerd", "path": "/host/var/lib/containerd"},
    {"label": "containers", "path": "/host/var/lib/containers"},
    {"label": "kubelet pods", "path": "/host/var/lib/kubelet/pods"},
    {"label": "log pods", "path": "/host/var/log/pods"},
    {"label": "log containers", "path": "/host/var/log/containers"},
]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "mounts": get_mounts(),
        "shortcuts": SHORTCUTS,
        "one_fs": DU_ONE_FS,
        "timeout": DU_TIMEOUT_SEC,
        "cache_ttl": DU_CACHE_TTL_SEC,
        "allowed_roots": ALLOWED_ROOTS,
    })

@app.get("/api/mounts")
async def api_mounts():
    """마운트 포인트 목록 반환"""
    from mounts import get_mounts
    return JSONResponse(get_mounts())

@app.get("/api/du")
async def api_du(path: str = Query("/", description="absolute path"), depth: int = Query(1, ge=0, le=5)):
    try:
        # depth=0일 때는 실제 사용량 조회
        if depth == 0:
            # fstype 확인 (mounts 정보에서)
            from mounts import get_mounts
            mounts = get_mounts()
            
            fstype = None
            for m in mounts:
                if m.get('mountpoint') == path:
                    fstype = m.get('fstype')
                    break
            
            # overlay_utils 사용
            if fstype:
                from overlay_utils import get_actual_mount_size
                size_bytes, size_human, status = get_actual_mount_size(path, fstype)
                
                if status == "ok":
                    return JSONResponse({
                        "path": path,
                        "total_bytes": size_bytes,
                        "total_human": size_human,
                        "entries": []
                    })
                else:
                    raise HTTPException(status_code=504, detail=size_human)
            
            # fstype을 못 찾은 경우 기존 방식
            import subprocess
            if ALLOWED_ROOTS:
                from utils import is_within
                if not any(is_within(r, path) for r in ALLOWED_ROOTS):
                    raise HTTPException(status_code=403, detail="path is outside allowed roots")
            
            try:
                result = subprocess.run(
                    ["du", "-d", "1", "-x", "-B1", "--", path],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False
                )
                
                if result.returncode in (0, 1):
                    lines = result.stdout.strip().split('\n')
                    if lines:
                        last_line = lines[-1]
                        parts = last_line.split('\t')
                        if len(parts) >= 1:
                            size_bytes = int(parts[0])
                            return JSONResponse({
                                "path": path,
                                "total_bytes": size_bytes,
                                "total_human": human_bytes(size_bytes),
                                "entries": []
                            })
            except subprocess.TimeoutExpired:
                raise HTTPException(status_code=504, detail="du timeout (path too large)")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        
        # depth > 0일 때는 기존 로직
        return JSONResponse(list_children_sizes(
            path=path, depth=depth, cache=cache,
            timeout_sec=DU_TIMEOUT_SEC, one_fs=DU_ONE_FS, allowed_roots=ALLOWED_ROOTS
        ))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"du timeout after {DU_TIMEOUT_SEC}s")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system/stats")
async def api_system_stats():
    """실시간 시스템 모니터링 정보 (호스트 노드)"""
    import psutil
    import os
    
    # 호스트 /proc 사용 (컨테이너가 아닌 노드 정보)
    if os.path.exists('/host/proc'):
        # psutil이 호스트 /proc을 사용하도록 설정
        psutil.PROCFS_PATH = '/host/proc'
    
    # CPU 정보
    cpu_percent = psutil.cpu_percent(interval=0.1, percpu=False)
    cpu_count = psutil.cpu_count()
    
    # 메모리 정보
    mem = psutil.virtual_memory()
    
    # 디스크 I/O
    disk_io = psutil.disk_io_counters()
    
    # 네트워크 I/O
    net_io = psutil.net_io_counters()
    
    # Top 프로세스 (CPU 기준)
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            processes.append({
                "pid": pinfo['pid'],
                "name": pinfo['name'],
                "cpu": pinfo['cpu_percent'] or 0,
                "mem": pinfo['memory_percent'] or 0
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # CPU 사용률 높은 순으로 정렬
    processes.sort(key=lambda x: x['cpu'], reverse=True)
    top_processes = processes[:10]
    
    return JSONResponse({
        "cpu": {
            "percent": cpu_percent,
            "count": cpu_count
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "free": mem.free,
            "percent": mem.percent,
            "total_h": human_bytes(mem.total),
            "used_h": human_bytes(mem.used),
            "free_h": human_bytes(mem.free)
        },
        "disk_io": {
            "read_bytes": disk_io.read_bytes if disk_io else 0,
            "write_bytes": disk_io.write_bytes if disk_io else 0,
            "read_h": human_bytes(disk_io.read_bytes) if disk_io else "0 B",
            "write_h": human_bytes(disk_io.write_bytes) if disk_io else "0 B"
        },
        "net_io": {
            "bytes_sent": net_io.bytes_sent if net_io else 0,
            "bytes_recv": net_io.bytes_recv if net_io else 0,
            "sent_h": human_bytes(net_io.bytes_sent) if net_io else "0 B",
            "recv_h": human_bytes(net_io.bytes_recv) if net_io else "0 B"
        },
        "top_processes": top_processes
    })

@app.get("/api/paths/summary")
async def api_paths_summary():
    """주요 경로별 디스크 사용량 병렬 조회 (du -s -x 사용)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import subprocess
    
    # 조회할 주요 경로
    paths = [
        "/host/var/lib/containerd",
        "/host/var/lib/containers", 
        "/host/var/lib/kubelet/pods",
        "/host/var/log/pods",
        "/host/var/log/containers"
    ]
    
    results = []
    
    def get_path_size_fast(path):
        """du -s -x로 빠르고 정확한 용량 조회"""
        try:
            # -s: 요약 (총합만), -x: 마운트 경계 넘지 않음, -B1: 바이트 단위
            result = subprocess.run(
                ["du", "-s", "-x", "-B1", "--", path],
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )
            
            if result.returncode in (0, 1):
                line = result.stdout.strip()
                if line:
                    size_bytes = int(line.split()[0])
                    return {
                        "path": path,
                        "total_bytes": size_bytes,
                        "total_human": human_bytes(size_bytes),
                        "status": "ok"
                    }
            
            # 실패 시
            return {
                "path": path,
                "total_bytes": 0,
                "total_human": "Error",
                "status": "error",
                "error": result.stderr.strip() if result.stderr else "du failed"
            }
            
        except subprocess.TimeoutExpired:
            return {
                "path": path,
                "total_bytes": 0,
                "total_human": "Timeout",
                "status": "error",
                "error": "Timeout after 10s"
            }
        except Exception as e:
            return {
                "path": path,
                "total_bytes": 0,
                "total_human": "Error",
                "status": "error",
                "error": str(e)
            }
    
    # 병렬로 모든 경로 조회
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_path = {executor.submit(get_path_size_fast, p): p for p in paths}
        for future in as_completed(future_to_path):
            results.append(future.result())
    
    # 용량 큰 순으로 정렬
    results.sort(key=lambda x: x["total_bytes"], reverse=True)
    
    return JSONResponse({"paths": results})


@app.get("/api/mounts/actual")
async def api_mounts_actual(skip_zero: bool = True):
    """
    df로 필터된 mountpoint들을 순서대로 actual 사용량을 붙여서 반환.
    skip_zero=true면 actual_bytes==0인 항목은 제외.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from overlay_utils import get_actual_mount_size
    
    mounts = get_mounts()

    # 병렬(선택): mountpoint가 많을 때 응답속도 개선
    max_workers = int(os.getenv("ACTUAL_MAX_WORKERS", "6"))

    results = [None] * len(mounts)

    def work(i: int, m: dict):
        b, h, st = get_actual_mount_size(m["mountpoint"], m.get("fstype", ""))
        return i, b, h, st

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(work, i, m) for i, m in enumerate(mounts)]
        for fut in as_completed(futs):
            i, b, h, st = fut.result()
            m = mounts[i].copy()
            m["actual_bytes"] = b
            m["actual_human"] = h
            m["actual_status"] = st
            results[i] = m

    out = []
    for m in results:
        # 순서 유지
        if not m:
            continue
        # 0인 것은 빼기 (요구사항)
        if skip_zero and m.get("actual_status") == "ok" and m.get("actual_bytes") == 0:
            continue
        out.append(m)

    return JSONResponse({"mounts": out})
