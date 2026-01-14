# Pod Writable Layer Finder

Kubernetes 노드에서 **PV 이외에 컨테이너가 직접 쓴 데이터**를 찾아주는 웹 UI.

## 목적

노드 디스크 용량이 부족할 때 **어떤 Pod가 범인인지** 빠르게 찾기 위함.

## 조회 대상

### 1. overlay upperdir (Container Writable Layer)
- 컨테이너가 `/app`, `/tmp`, `/var` 등에 파일을 쓰면 여기에 쌓임
- 경로: `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/.../diff`
- `/host/proc/1/mountinfo`에서 overlay mount의 `upperdir` 추출
- `crictl ps`로 실행 중인 컨테이너만 필터링

### 2. emptyDir (Disk 기반)
- PV는 아니지만 `/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~empty-dir/` 아래로 쌓임
- 디렉토리 직접 탐색으로 조회

## 조회 방법

```
1. crictl ps -q → 실행 중인 컨테이너 ID 목록
2. crictl ps --output=json → 컨테이너별 Pod 이름, Container 이름
3. /host/proc/1/mountinfo → overlay mount에서 upperdir 추출
4. /host/var/lib/kubelet/pods/*/volumes/kubernetes.io~empty-dir/* → emptyDir 조회
5. du -sx -B1 <path> → 각 경로별 디스크 사용량 조회
```

## API

### GET /api/containers/writable/stream
- SSE 스트리밍으로 완료되는 순서대로 전송
- `?skip_zero=true` → 0 바이트 제외

### GET /api/containers/writable
- JSON으로 전체 결과 반환 (용량 큰 순 정렬)

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DU_TIMEOUT_SEC` | 60 | du 명령 타임아웃 (초) |
| `ACTUAL_MAX_WORKERS` | 6 | 병렬 du 실행 워커 수 |

## 실행

```bash
# 로컬 테스트
pip install -r requirements.txt
uvicorn main:app --reload --port=8000

# K8s 배포
kubectl apply -f k8s/deploy.yaml
```

## emptyDir의 Pod UID로 Pod 찾기

```bash
kubectl get pods -A -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,UID:.metadata.uid --no-headers | grep "<Pod UID>"
```

## container 내부에서 실행해서 증가 확인
```bash
dd if=/dev/zero of=bigfile.bin bs=1M count=1024 status=progress
```

