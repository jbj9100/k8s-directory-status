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


@app.get("/api/local/writable/stream")
async def api_local_writable_stream(skip_zero: bool = False):
    """
    [Local] Pod가 PV 이외에 컨테이너 자체에 쓴 데이터 조회
    """
    import json
    import socket
    from fastapi.responses import StreamingResponse
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from overlay_utils import get_all_writable_paths, get_upperdir_size
    
    my_node_name = os.getenv("NODE_NAME", socket.gethostname())

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
                
                if skip_zero and st == "ok" and b == 0:
                    continue
                
                result = {
                    "node_name": my_node_name,
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


@app.get("/api/local/writable")
async def api_local_writable(skip_zero: bool = False):
    """[Local] JSON Non-streaming"""
    import socket
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from overlay_utils import get_all_writable_paths, get_upperdir_size

    my_node_name = os.getenv("NODE_NAME", socket.gethostname())
    
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
                "node_name": my_node_name,
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
    
    out.sort(key=lambda x: x.get("actual_bytes", 0), reverse=True)
    return JSONResponse({"containers": out})


@app.get("/api/containers/writable/stream")
async def api_cluster_writable_stream(skip_zero: bool = False):
    """
    [Cluster] 모든 노드의 Pod 데이터 조회 (Aggregation)
    status-headless 서비스를 통해 Peer 찾아서 집계
    """
    import socket
    import asyncio
    import httpx
    import json
    from fastapi.responses import StreamingResponse
    
    # 1. Peer Discovery
    try:
        # Headless Service 이름으로 DNS 조회
        # 같은 namespace라고 가정 (default)
        infos = socket.getaddrinfo("status-headless", 8080, proto=socket.IPPROTO_TCP)
        # IP 주소만 추출 (IPv4)
        peers = set(info[4][0] for info in infos)
    except Exception as e:
        print(f"Discovery failed: {e}")
        # 실패 시 로컬호스트만이라도? 아니면 빈 집합
        peers = {"127.0.0.1"}
    
    async def cluster_generator():
        queue = asyncio.Queue()
        # active_workers count
        state = {"active": len(peers)}
        
        async def fetch_peer(ip):
            # Peer의 Local API 호출
            url = f"http://{ip}:8080/api/local/writable/stream?skip_zero={str(skip_zero).lower()}"
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("GET", url) as response:
                        async for line in response.aiter_lines():
                            # line example: "data: {...}" or "data: [DONE]" or ""
                            if not line.strip():
                                continue
                            if line.startswith("data: [DONE]"):
                                continue
                            if line.startswith("data: "):
                                # 그대로 큐에 넣음 (이미 JSON 포맷팅 되어있음)
                                await queue.put(line)
            except Exception as e:
                print(f"Error fetching {ip}: {e}")
            finally:
                state["active"] -= 1
                if state["active"] == 0:
                    await queue.put(None) # Signal done

        # Launch workers
        if not peers:
             await queue.put(None)
        else:
            for ip in peers:
                asyncio.create_task(fetch_peer(ip))
            
        # Yield result
        while True:
            line = await queue.get()
            if line is None:
                break
            yield f"{line}\n\n"
        
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        cluster_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
