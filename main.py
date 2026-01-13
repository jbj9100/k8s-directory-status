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
