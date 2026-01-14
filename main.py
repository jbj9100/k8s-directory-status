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
except ImportError:
    from mounts import get_mounts
    from du_runner import DuCache, list_children_sizes

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
    return JSONResponse(get_mounts())

@app.get("/api/du")
async def api_du(path: str = Query("/", description="absolute path"), depth: int = Query(1, ge=0, le=5)):
    try:
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
    """실시간 시스템 모니터링 정보"""
    import psutil
    
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
    """주요 경로별 디스크 사용량 병렬 조회"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from du_runner import list_children_sizes
    
    # 조회할 주요 경로
    paths = [
        "/host/var/lib/containerd",
        "/host/var/lib/containers",
        "/host/var/lib/kubelet/pods",
        "/host/var/log/pods",
        "/host/var/log/containers"
    ]
    
    results = []
    
    def get_path_size(path):
        try:
            data = list_children_sizes(
                path=path, depth=0, cache=cache,
                timeout_sec=10, one_fs=DU_ONE_FS, allowed_roots=ALLOWED_ROOTS
            )
            return {
                "path": path,
                "total_bytes": data.get("total_bytes", 0),
                "total_human": data.get("total_human", "0 B"),
                "status": "ok"
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
        future_to_path = {executor.submit(get_path_size, p): p for p in paths}
        for future in as_completed(future_to_path):
            results.append(future.result())
    
    # 용량 큰 순으로 정렬
    results.sort(key=lambda x: x["total_bytes"], reverse=True)
    
    return JSONResponse({"paths": results})
