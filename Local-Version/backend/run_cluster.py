"""Unified Real-Time Cluster Runner: Controller (:8000) + 3 Real NumPy/psutil Workers (:8001-8003)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"

WORKER_CONFIGS = [
    {
        "WORKER_ID": "worker-1",
        "WORKER_IP": "127.0.0.1",
        "WORKER_PORT": "8001",
        "WORKER_TOTAL_MEM_MB": "4096.0",
        "WORKER_BASE_CPU_PCT": "12.0",
        "WORKER_BASE_MEM_MB": "640.0",
        "WORKER_TIME_SCALE": "0.55",
        "WORKER_MAX_PHYSICAL_DIM": "450",
        "WORKER_ENABLE_AGENT": "true",
        "WORKER_TELEMETRY_INTERVAL": "1.5",
        "CONTROLLER_URL": "http://127.0.0.1:8000",
    },
    {
        "WORKER_ID": "worker-2",
        "WORKER_IP": "127.0.0.1",
        "WORKER_PORT": "8002",
        "WORKER_TOTAL_MEM_MB": "4096.0",
        "WORKER_BASE_CPU_PCT": "18.0",
        "WORKER_BASE_MEM_MB": "820.0",
        "WORKER_TIME_SCALE": "0.55",
        "WORKER_MAX_PHYSICAL_DIM": "450",
        "WORKER_ENABLE_AGENT": "true",
        "WORKER_TELEMETRY_INTERVAL": "1.5",
        "CONTROLLER_URL": "http://127.0.0.1:8000",
    },
    {
        "WORKER_ID": "worker-3",
        "WORKER_IP": "127.0.0.1",
        "WORKER_PORT": "8003",
        "WORKER_TOTAL_MEM_MB": "8192.0",
        "WORKER_BASE_CPU_PCT": "9.0",
        "WORKER_BASE_MEM_MB": "1024.0",
        "WORKER_TIME_SCALE": "0.55",
        "WORKER_MAX_PHYSICAL_DIM": "450",
        "WORKER_ENABLE_AGENT": "true",
        "WORKER_TELEMETRY_INTERVAL": "1.5",
        "CONTROLLER_URL": "http://127.0.0.1:8000",
    },
]

CLUSTER_PORTS = (8000, 8001, 8002, 8003)


def free_ports(ports: tuple[int, ...] = CLUSTER_PORTS) -> None:
    """Safely terminate any lingering processes listening on the target cluster ports."""
    try:
        import psutil
        current_pid = os.getpid()
        killed: set[int] = set()
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port in ports:
                pid = conn.pid
                if pid and pid != current_pid and pid not in killed:
                    try:
                        p = psutil.Process(pid)
                        print(f"[*] Releasing port {conn.laddr.port} from stale PID {pid} ({p.name()})...")
                        p.kill()
                        p.wait(timeout=1.0)
                        killed.add(pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
    except Exception as e:
        print(f"[!] Port pre-check note: {e}")


def main() -> int:
    # 0. Automatically free any orphaned listeners before binding
    free_ports(CLUSTER_PORTS)

    processes: list[subprocess.Popen[bytes]] = []
    python_exe = sys.executable

    try:
        # 1. Start the 3 internal Worker Executor + psutil Telemetry Agent servers (:8001..8003)
        for cfg in WORKER_CONFIGS:
            env = os.environ.copy()
            env.update(cfg)
            env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{BACKEND_DIR}"
            cmd = [
                python_exe,
                "-m",
                "uvicorn",
                "worker.executor:app",
                "--host",
                "127.0.0.1",
                "--port",
                cfg["WORKER_PORT"],
                "--log-level",
                "warning",
            ]
            proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env)
            processes.append(proc)

        # 2. Start the public Controller (:8000) serving API + WebSocket + Frontend SPA
        ctrl_env = os.environ.copy()
        ctrl_env["CB_SEED_DEMO_WORKERS"] = "false"
        ctrl_env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{ROOT_DIR}"
        ctrl_cmd = [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--timeout-keep-alive",
            "75",
        ]
        ctrl_proc = subprocess.Popen(ctrl_cmd, cwd=str(BACKEND_DIR), env=ctrl_env)
        processes.append(ctrl_proc)

        print("[✓] CloudBalance Cluster successfully initialized on ports 8000-8003.")

        # Monitor child processes until interrupted
        while True:
            for idx, p in enumerate(processes[:-1], start=1):
                if p.poll() is not None:
                    print(f"[!] Worker-{idx} process exited unexpectedly with returncode: {p.poll()}", flush=True)
            if ctrl_proc.poll() is not None:
                print(f"[!] Controller process exited with returncode: {ctrl_proc.poll()}", flush=True)
                return ctrl_proc.returncode or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[*] Stopping CloudBalance Cluster via KeyboardInterrupt...", flush=True)
    except Exception as exc:
        print(f"\n[!] Unexpected error in cluster loop: {exc}", flush=True)
    finally:
        for p in processes:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        for p in processes:
            try:
                p.wait(timeout=2.0)
            except Exception:
                pass
        free_ports(CLUSTER_PORTS)
        print("[✓] All cluster ports successfully cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
