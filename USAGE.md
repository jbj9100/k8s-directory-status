# 노드 스토리지 체크 도구 사용 가이드

## 📦 파일 구성

- **check_node_storage_standalone.py** - 각 노드에서 실행되는 스토리지 체크 스크립트 (단독 실행 가능)
- **deploy_storage_check.py** - Ansible을 사용한 대화식 배포/실행 도구
- **hosts.example** - Ansible 인벤토리 파일 예시

## 🚀 사용 방법

### 1. 단일 노드에서 직접 실행

워커 노드에 SSH 접속 후 직접 실행:

```bash
# 파일 복사
scp check_node_storage_standalone.py worker-node:/tmp/

# SSH 접속
ssh worker-node

# 실행
python3 /tmp/check_node_storage_standalone.py

# 0 바이트 제외
python3 /tmp/check_node_storage_standalone.py --skip-zero

# 빠른 체크
python3 /tmp/check_node_storage_standalone.py --timeout 10 --workers 10
```

### 2. Ansible로 모든 노드에 배포 및 실행 (권장)

마스터 노드에서 실행:

#### 준비 단계

1. **Ansible 설치 확인**
```bash
ansible --version
```

2. **인벤토리 파일 생성**
```bash
# hosts.example을 복사하여 수정
cp hosts.example hosts
vi hosts
```

3. **연결 테스트**
```bash
ansible all -i hosts -m ping
```

#### 실행

```bash
# 기본 실행 (대화식)
python3 deploy_storage_check.py

# 인벤토리 파일 지정
python3 deploy_storage_check.py -i ./hosts

# 0 바이트 항목 제외
python3 deploy_storage_check.py --skip-zero

# 모든 확인 단계 자동 승인
python3 deploy_storage_check.py -y

# 빠른 체크
python3 deploy_storage_check.py --timeout 30 -y
```

#### 실행 흐름

```
[Step 1] 스크립트를 모든 노드에 배포
  ↓
[Step 2] 각 노드에서 스토리지 체크 실행
  ↓
[Step 3] 임시 파일 정리
  ↓
결과 저장: ./storage_check_results/
```

#### 결과 확인

```bash
# 결과 디렉토리 확인
ls -lh storage_check_results/

# 실행 결과 보기
cat storage_check_results/02_results_*.txt

# 특정 노드만 필터링
cat storage_check_results/02_results_*.txt | grep -A 20 "worker1"
```

## 📊 출력 형식

```
Type       Container ID   Container/Volume Name               Pod Name                                 Size         Status
======================================================================================================================================================
overlay    a62bdd4bbc7c   redis-insight                       redis-insight-747dc6dd84-sssqk           2.1 MiB      ok
           └─ /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/1201/fs
           ---------------------------------------------------------------------------------------------------------------------------------------
emptydir                  dshm                                cloudbeaver-6fd856b468-5nszp             1.0 MiB      ok
           └─ /var/lib/kubelet/pods/92d81696-9b26-40e1-88f4-202a71d9072f/volumes/kubernetes.io~empty-dir/dshm
           ---------------------------------------------------------------------------------------------------------------------------------------

📊 요약:
  - Overlay (컨테이너 writable layer): 27개
  - EmptyDir 볼륨: 38개
  - 총 용량: 7.7 MiB
  - 오류: 0개
```

## ⚙️ 상세 옵션

### deploy_storage_check.py 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-i, --inventory` | Ansible 인벤토리 파일 | hosts |
| `--script` | 배포할 스크립트 파일 | check_node_storage_standalone.py |
| `--output-dir` | 결과 저장 디렉토리 | ./storage_check_results |
| `--skip-zero` | 0 바이트 항목 제외 | False |
| `--timeout` | du 명령 타임아웃 (초) | 60 |
| `-y, --yes` | 모든 확인 자동 승인 | False |

### check_node_storage_standalone.py 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--skip-zero` | 0 바이트 항목 제외 | False |
| `--timeout` | du 명령 타임아웃 (초) | 60 |
| `--workers` | 병렬 작업 개수 | 6 |
| `--sort` | 정렬 (size/name/type) | size |

## 🔍 트러블슈팅

### Ansible 연결 실패

```bash
# SSH 키 기반 인증 설정
ssh-copy-id root@worker-node

# 또는 인벤토리에 비밀번호 추가
ansible_ssh_pass=yourpassword
```

### crictl 명령 없음

```bash
# containerd 사용 중인지 확인
ansible all -i hosts -m shell -a "which crictl" --become
```

### 권한 부족

```bash
# sudo 권한으로 실행
python3 deploy_storage_check.py  # --become 옵션이 이미 포함됨
```

## 💡 사용 팁

1. **정기 점검**: cron으로 주기적 실행
   ```bash
   # 매일 오전 2시 실행
   0 2 * * * cd /path/to/k8s-directory-status && python3 deploy_storage_check.py -y
   ```

2. **결과 비교**: 시간별 변화 추적
   ```bash
   # 이전 결과와 비교
   diff storage_check_results/02_results_20260204_100000.txt \
        storage_check_results/02_results_20260204_140000.txt
   ```

3. **용량 큰 항목만 확인**: 
   ```bash
   python3 deploy_storage_check.py --skip-zero -y
   ```
