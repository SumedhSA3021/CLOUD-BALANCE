"""Unified Real-Time Cluster Runner driven by .env (WORKER_URLS, ADMIN_TOKEN, WORKER_SECRET)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import (  # noqa: E402
    DEFAULT_LOCAL_HOST,
    ROOT_DIR,
    Settings,
    WorkerEndpoint,
    WorkerSettings,
)

_WORKER_PROFILES = (
    ("4096.0", "12.0", "640.0"),
    ("4096.0", "18.0", "820.0"),
    ("8192.0", "9.0", "1024.0"),
)


def _build_worker_configs(
    endpoints: list[WorkerEndpoint],
    controller_url: str,
    worker_secret: str,
    telemetry_interval: float,
) -> list[dict[str, str]]:
    """Construct worker process environment dicts from parsed WORKER_URLS."""
    configs: list[dict[str, str]] = []
    for idx, ep in enumerate(endpoints):
        total_mem, base_cpu, base_mem = _WORKER_PROFILES[idx % len(_WORKER_PROFILES)]
        bind_host = DEFAULT_LOCAL_HOST if ep.host in ("localhost", "127.0.0.1", "0.0.0.0") else ep.host
        configs.append(
            {
                "WORKER_ID": ep.worker_id,
                "WORKER_IP": bind_host,
                "WORKER_PORT": str(ep.port),
                "WORKER_TOTAL_MEM_MB": total_mem,
                "WORKER_BASE_CPU_PCT": base_cpu,
                "WORKER_BASE_MEM_MB": base_mem,
                "WORKER_TIME_SCALE": "0.55",
                "WORKER_MAX_PHYSICAL_DIM": "450",
                "WORKER_ENABLE_AGENT": "true",
                "WORKER_TELEMETRY_INTERVAL": str(telemetry_interval),
                "CONTROLLER_URL": controller_url,
                "WORKER_SECRET": worker_secret,
            }
        )
    return configs


def free_ports(ports: tuple[int, ...]) -> None:
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
    try:
        cfg = Settings()
    except ValidationError as exc:
        print(f"[!] Invalid cluster configuration in .env or environment: {exc}", file=sys.stderr)
        return 1

    worker_defaults = WorkerSettings()
    endpoints = cfg.worker_endpoints()
    admin_token = cfg.admin_token
    worker_secret = cfg.worker_secret

    controller_port = cfg.controller_port
    controller_url = cfg.controller_url.rstrip("/")
    parsed_ctrl = urlparse(controller_url)
    if parsed_ctrl.port:
        controller_port = parsed_ctrl.port

    cluster_ports = (controller_port, *(ep.port for ep in endpoints))
    worker_configs = _build_worker_configs(
        endpoints,
        controller_url,
        worker_secret,
        telemetry_interval=worker_defaults.worker_telemetry_interval,
    )

    # 0. Automatically free any orphaned listeners before binding
    free_ports(cluster_ports)

    processes: list[subprocess.Popen[bytes]] = []
    python_exe = sys.executable

    try:
        # 1. Start the internal Worker Executor + psutil Telemetry Agent servers
        for worker_cfg in worker_configs:
            env = os.environ.copy()
            env.update(worker_cfg)
            env["PYTHONPATH"] = f"{ROOT_DIR}{os.pathsep}{BACKEND_DIR}"
            cmd = [
                python_exe,
                "-m",
                "uvicorn",
                "worker.executor:app",
                "--host",
                worker_cfg["WORKER_IP"],
                "--port",
                worker_cfg["WORKER_PORT"],
                "--log-level",
                "warning",
            ]
            proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env)
            processes.append(proc)

        # 2. Start the Controller serving API + WebSocket + Frontend SPA
        ctrl_env = os.environ.copy()
        ctrl_env["CB_SEED_DEMO_WORKERS"] = "false"
        ctrl_env["ADMIN_TOKEN"] = admin_token
        ctrl_env["WORKER_SECRET"] = worker_secret
        ctrl_env["WORKER_URLS"] = ",".join(ep.url for ep in endpoints)
        ctrl_env["CONTROLLER_HOST"] = cfg.controller_host
        ctrl_env["CONTROLLER_PORT"] = str(controller_port)
        ctrl_env["CONTROLLER_URL"] = controller_url
        ctrl_env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{ROOT_DIR}"
        ctrl_cmd = [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            cfg.controller_host,
            "--port",
            str(controller_port),
            "--timeout-keep-alive",
            "75",
        ]
        ctrl_proc = subprocess.Popen(ctrl_cmd, cwd=str(BACKEND_DIR), env=ctrl_env)
        processes.append(ctrl_proc)

        worker_list = [ep.url for ep in endpoints]
        print(
            f"[✓] CloudBalance Cluster initialized (controller=:{controller_port}, workers={worker_list})."
        )

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
        free_ports(cluster_ports)
        print("[✓] All cluster ports successfully cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
