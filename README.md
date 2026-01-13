# DF/DU UI (FastAPI) — 노드 디스크 사용량 웹 UI

`df`는 **마운트(파일시스템)** 단위만 보여서, 같은 파일시스템(`/`) 안에서
`/var/lib/containerd`, `/var/lib/kubelet`, `/var/log` 같은 **디렉터리별 사용량**을 보려면 `du`가 필요합니다.

이 프로젝트는:
- `df` 스타일: 마운트 목록/용량(총/사용/가용)
- `du` 스타일: 특정 경로의 1-depth(하위 디렉터리) 용량 Top 리스트
- 클릭으로 drill-down(폴더 탐색) 가능한 간단 UI

## 설치/실행
```bash
conda create -n k8s-directory-status  python=3.10
conda activate k8s-directory-status
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port=8000 --host=0.0.0.0
```

브라우저:
- http://<node-ip>:8000

## 환경변수
- `DU_TIMEOUT_SEC` (기본 15)
- `DU_CACHE_TTL_SEC` (기본 20)
- `DU_ONE_FS` (기본 1: du -x, 마운트 넘어가지 않음)
- `ALLOWED_ROOTS` (옵션: 콤마로 경로 제한, 예: "/,/var/lib/kubelet,/var/lib/containerd")
