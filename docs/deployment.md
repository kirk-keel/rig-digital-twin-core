# Rig Digital Twin Core - Production Deployment Guide

This guide covers deployment architectures for edge hardware on offshore rigs, onshore drilling control rooms, and enterprise cloud clusters.

---

## 1. Quickstart with Docker Compose

The simplest and most resilient way to run the full stack locally or on a rig edge server is via Docker Compose.

### Step 1: Clone and Configure
```bash
git clone https://github.com/kirk-keel/rig-digital-twin-core.git
cd rig-digital-twin-core
cp .env.example .env
```

### Step 2: Launch Stack
```bash
docker compose up -d --build
```

### Step 3: Verify Services
- **Driller Console Web UI**: `http://localhost:8000`
- **FastAPI Interactive Swagger Specs**: `http://localhost:8000/docs`
- **WITS Level 0 TCP Feed**: `localhost:9090`
- **TimescaleDB Database**: `localhost:5432`

---

## 2. Standalone Local Development

If developing locally without Docker:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package with development dependencies
pip install -e ".[dev]"

# Run unit tests
pytest

# Launch API and Driller Console
rig-twin serve --host 0.0.0.0 --port 8000

# In a separate terminal, launch WITS0 TCP server
rig-twin wits0-server --host 0.0.0.0 --port 9090
```

---

## 3. Production TimescaleDB Configuration

For high-frequency sensor streams (e.g. 10 Hz to 100 Hz from MWD/PWD tools), tune PostgreSQL/TimescaleDB parameters in `postgresql.conf`:

```ini
# Memory Configuration
shared_buffers = 4GB
work_mem = 64MB
maintenance_work_mem = 1GB

# TimescaleDB Chunk Interval & Compression
timescaledb.max_background_workers = 8
max_worker_processes = 16

# WAL & Checkpoints
checkpoint_completion_target = 0.9
max_wal_size = 16GB
min_wal_size = 2GB
```

Hypertables are created automatically with:
- `raw_telemetry`: Chunk time interval of `1 day`, compressed after `7 days`.
- `anomaly_events`: Chunk time interval of `1 day`.

---

## 4. Kubernetes / Edge Helm Deployment

For edge clusters (K3s, MicroK8s, or OpenShift on drilling vessels):
- Mount persistent volumes for `/var/lib/postgresql/data`.
- Configure `service.type: LoadBalancer` or Ingress for ports 8000 (HTTP/WebSocket) and 9090 (TCP).
- Health probes:
  - `livenessProbe`: `GET /health` with `initialDelaySeconds: 15`
  - `readinessProbe`: `GET /health` with `periodSeconds: 5`
