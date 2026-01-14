from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app = FastAPI(title="Pod Writable Layer Finder", version="1.0")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/api/node-info")
async def api_node_info():
    """현재 Pod가 떠있는 노드 정보"""
    import socket
    node_name = os.getenv("NODE_NAME", socket.gethostname())
    return {"node_name": node_name}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/containers/writable/stream")
async def api_containers_writable_stream(skip_zero: bool = False):
    """
    Pod가 PV 이외에 컨테이너 자체에 쓴 데이터 조회
    - overlay upperdir: 컨테이너 writable layer
    - emptyDir: /var/lib/kubelet/pods/.../volumes/kubernetes.io~empty-dir/
    완료되는 순서대로 SSE 스트리밍
    """
    import json
    from fastapi.responses import StreamingResponse
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from overlay_utils import get_all_writable_paths, get_upperdir_size
    
    def generate():
        items = get_all_writable_paths()
        max_workers = int(os.getenv("ACTUAL_MAX_WORKERS", "6"))
        timeout_sec = int(os.getenv("DU_TIMEOUT_SEC", "60"))

        def work(item: dict):
            b, h, st = get_upperdir_size(item["path"], timeout_sec)
            return item, b, h, st

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(work, item) for item in items]
            
            for fut in as_completed(futs):
                item, b, h, st = fut.result()
                
                # 0 바이트는 스킵 (옵션)
                if skip_zero and st == "ok" and b == 0:
                    continue
                
                result = {
                    "type": item.get("type", ""),
                    "container_id": item.get("container_id", ""),
                    "container_name": item.get("container_name", ""),
                    "pod": item.get("pod", ""),
                    "namespace": item.get("namespace", ""),
                    "path": item.get("path", ""),
                    "mountpoint": item.get("mountpoint", ""),
                    "actual_bytes": b,
                    "actual_human": h,
                    "actual_status": st,
                }
                
                # emptyDir인 경우 추가 정보
                if item.get("type") == "emptydir":
                    result["volume_name"] = item.get("volume_name", "")
                    result["pod_uid"] = item.get("pod_uid", "")
                
                yield f"data: {json.dumps(result)}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/containers/writable")
async def api_containers_writable(skip_zero: bool = False):
    """
    Pod가 PV 이외에 컨테이너 자체에 쓴 데이터 조회 (JSON)
    - overlay upperdir: 컨테이너 writable layer
    - emptyDir: /var/lib/kubelet/pods/.../volumes/kubernetes.io~empty-dir/
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from overlay_utils import get_all_writable_paths, get_upperdir_size
    
    items = get_all_writable_paths()
    max_workers = int(os.getenv("ACTUAL_MAX_WORKERS", "6"))
    timeout_sec = int(os.getenv("DU_TIMEOUT_SEC", "60"))

    def work(item: dict):
        b, h, st = get_upperdir_size(item["path"], timeout_sec)
        return item, b, h, st

    out = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(work, item) for item in items]
        
        for fut in as_completed(futs):
            item, b, h, st = fut.result()
            
            if skip_zero and st == "ok" and b == 0:
                continue
            
            result = {
                "type": item.get("type", ""),
                "container_id": item.get("container_id", ""),
                "container_name": item.get("container_name", ""),
                "pod": item.get("pod", ""),
                "namespace": item.get("namespace", ""),
                "path": item.get("path", ""),
                "mountpoint": item.get("mountpoint", ""),
                "actual_bytes": b,
                "actual_human": h,
                "actual_status": st
            }
            
            if item.get("type") == "emptydir":
                result["volume_name"] = item.get("volume_name", "")
                result["pod_uid"] = item.get("pod_uid", "")
            
            out.append(result)
    
    # 용량 큰 순으로 정렬
    out.sort(key=lambda x: x.get("actual_bytes", 0), reverse=True)
    
    return JSONResponse({"containers": out})
