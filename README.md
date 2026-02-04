# Kubernetes Node Storage Check Tool

A comprehensive tool to analyze disk usage on Kubernetes nodes. It identifies **Container Writable Layers (OverlayFS)** and **Volumes (EmptyDir, PVC, HostPath)** that consume disk space.

This project supports two modes:
1.  **Ansible CLI Tool (Recommended)**: Verify multiple remote nodes directly from your local machine/master node.
2.  **Standalone Script**: Run manually on a single node.

---

## 🚀 Key Features

-   **Check Container Writable Layers**: Finds files written directly inside containers (`/run`, `/tmp`, etc.) via OverlayFS `upperdir`.
-   **Check Volume Usage**: Finds disk usage in `EmptyDir`, `PVC`, `HostPath`, and `CSI` volumes.
-   **Real-time Monitoring (Watch Mode)**: Continuously monitors storage usage with auto-refresh.
-   **Smart Filtering**:
    -   Skip 0-byte items (`--skip-zero`).
    -   Filter by size (1 GiB+, 100 MiB+).
-   **No Dependency Hell**: Uses standard `ansible` and `python3`. No complex installation required on remote nodes.

---

## 📦 Components

-   `ansible_check_node.py`: **Main entry point**. Uses Ansible to execute the check on remote nodes.
-   `check_node_storage_standalone.py`: The actual logic script. It is automatically embedded and sent to remote nodes by the wrapper.
-   `hosts`: Ansible inventory file example.

---

## 🛠 Prerequisites

### Control Node (Where you run the script)
-   Python 3.6+
-   Ansible installed: `pip install ansible`

### Managed Nodes (Kubernetes Workers)
-   Python 3 installed
-   `crictl` configured (standard for Containerd/Kubernetes environments)
-   Root/Sudo access (required to read `/var/lib/kubelet` and overlay directories)

---

## 📖 Usage

### 1. Setup Inventory

Create an Ansible inventory file (`hosts`) listing your Kubernetes nodes:

```ini
[all]
k8s-worker-1 ansible_host=192.168.1.101
k8s-worker-2 ansible_host=192.168.1.102

[all:vars]
ansible_user=root
# ansible_ssh_pass=secret  <-- If using password auth
# ansible_ssh_private_key_file=~/.ssh/id_rsa
```

### 2. Run Ansible CLI Tool (`ansible_check_node.py`)

This is the **primary way** to use the tool.

```bash
# Basic Interactive Mode
python3 ansible_check_node.py

# Specify inventory file
python3 ansible_check_node.py -i ./hosts
```

#### Interactive Menu
When run without arguments, you'll see a menu:
```
Select Mode:
  1. Normal Check (Run once)
  2. Watch Mode (Real-time monitoring)
```
-   **Normal Check**: Runs once and saves the result to `storage_check_results/`.
-   **Watch Mode**: Refreshes the screen every N seconds (like `watch` command).

#### Command Line Options

You can also run non-interactively:

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
crictl info
```

### Permission Denied
The script requires `sudo`/root privileges to read `/var/lib/kubelet` and overlay directories. The Ansible wrapper automatically attempts to elevate privileges (`--become`).

---

## 💡 Tips

1.  **Find the culprit**: Use `Watch Mode` while recreating the issue (e.g., file upload) to see which container's storage grows.
2.  **Log History**: In "Normal Mode", results are saved to `storage_check_results/` with timestamps. You can verify past usage.
3.  **Large Clusters**: For clusters with many nodes, use `--skip-zero` to reduce noise.
