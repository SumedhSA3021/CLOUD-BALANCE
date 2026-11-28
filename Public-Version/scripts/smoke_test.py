"""End-to-End Smoke Test for CloudBalance Local or Public Controller."""

from __future__ import annotations

import argparse
import base64
import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _ws_handshake_status(base_url: str, path_and_query: str) -> int:
    """Perform a minimal RFC 6455 HTTP Upgrade handshake and return HTTP status code."""
    from app.core.config import DEFAULT_LOCAL_HOST

    parsed = urlparse(base_url)
    use_tls = parsed.scheme == "https"
    host = parsed.hostname or DEFAULT_LOCAL_HOST
    port = parsed.port or (443 if use_tls else 80)
    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
    raw_req = (
        f"GET {path_and_query} HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")

    with socket.create_connection((host, port), timeout=5.0) as sock:
        conn = ssl.create_default_context().wrap_socket(sock, server_hostname=host) if use_tls else sock
        conn.sendall(raw_req)
        resp_head = conn.recv(1024).decode("latin-1", errors="ignore")
    first_line = resp_head.splitlines()[0] if resp_head else ""
    parts = first_line.split()
    return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0


def main(argv: list[str] | None = None) -> int:
    from app.core.config import DEFAULT_LOCAL_HOST, DEFAULT_WORKER_PORT, ClientSettings

    cfg = ClientSettings()
    parser = argparse.ArgumentParser(description="CloudBalance end-to-end smoke test")
    parser.add_argument(
        "--controller",
        default=cfg.controller_url,
    )
    parser.add_argument(
        "--admin-token",
        default=cfg.admin_token,
    )
    parser.add_argument(
        "--worker-secret",
        default=cfg.worker_secret,
    )
    args = parser.parse_args(argv)

    base = args.controller.rstrip("/")
    if not args.admin_token:
        print("[!] ADMIN_TOKEN not set in environment or .env", file=sys.stderr)
        return 1

    admin_headers = {"Authorization": f"Bearer {args.admin_token}"}
    with httpx.Client(base_url=base, timeout=15.0) as client:
        # 1. Health & readiness probes
        hz = client.get("/healthz")
        assert hz.status_code == 200 and hz.json().get("status") == "ok", f"/healthz failed: {hz.status_code} {hz.text}"
        ready = client.get("/ready")
        assert ready.status_code == 200 and ready.json().get("ready") is True, f"/ready failed: {ready.text}"
        print(f"[✓] /healthz & /ready OK (active_workers={ready.json().get('active_workers')})")

        # 2. Auth lock checks (must reject unauthenticated callers)
        for path in (
            "/admin/stats/summary",
            "/api/v1/telemetry/redis",
            "/api/v1/telemetry/workers",
            "/api/v1/telemetry/mongo",
            "/api/v1/control/snapshot",
            "/api/v1/benchmark/runs",
        ):
            r = client.get(path)
            assert r.status_code == 401, f"Expected 401 on unauthenticated GET {path}, got {r.status_code}"

        bad_tel = client.post(
            "/api/v1/telemetry",
            json={
                "worker_id": "rogue-worker",
                "ip_address": DEFAULT_LOCAL_HOST,
                "port": DEFAULT_WORKER_PORT,
                "cpu_percent": 1.0,
                "memory_total_mb": 1024.0,
                "memory_used_mb": 128.0,
                "memory_percent": 12.5,
                "load_avg_1m": 0.1,
                "active_task_count": 0,
            },
            headers={"X-Worker-Secret": "wrong-secret"},
        )
        assert bad_tel.status_code == 401, f"Expected 401 on bad telemetry secret, got {bad_tel.status_code}"
        print("[✓] Admin & worker telemetry auth gates return 401 on unauthenticated/invalid requests")

        # 3. Verify live worker heartbeats kept workers alive for /ops
        workers_resp = client.get("/api/v1/telemetry/workers", headers=admin_headers)
        assert workers_resp.status_code == 200
        workers = workers_resp.json()
        assert len(workers) >= 1, "No active workers reported on /api/v1/telemetry/workers"
        assert client.get("/api/v1/telemetry/redis", headers=admin_headers).status_code == 200
        assert client.get("/api/v1/control/snapshot", headers=admin_headers).status_code == 200
        assert client.get("/api/v1/benchmark/runs", headers=admin_headers).status_code == 200
        print(f"[✓] Authenticated /ops data endpoints OK (alive={[w['worker_id'] for w in workers]})")

        # 4. WebSocket auth handshake check
        ws_unauth = _ws_handshake_status(base, "/ws")
        assert ws_unauth in (400, 403), f"Expected WS rejection without token, got {ws_unauth}"
        ws_ok = _ws_handshake_status(base, f"/ws?token={args.admin_token}")
        assert ws_ok == 101, f"Expected WS 101 Switching Protocols with token, got {ws_ok}"
        print("[✓] WebSocket /ws rejects anonymous connections and accepts valid ADMIN_TOKEN")

        # 5. Public task execution (light + heavy) + SPA HTML check
        t_light = client.post(
            "/tasks",
            json={
                "client_id": "smoke-test",
                "task_type": "light",
                "payload": {"courses": [{"name": "CS101", "credits": 4, "grade": 9.5}]},
            },
        )
        assert t_light.status_code == 200 and t_light.json()["result"].get("cgpa") == 9.5, t_light.text

        t_heavy = client.post(
            "/tasks",
            json={
                "client_id": "smoke-test",
                "task_type": "heavy",
                "size": 10000,
                "payload": {"data": "smoke", "iterations": 10000},
            },
        )
        assert t_heavy.status_code == 200 and "final_hash" in t_heavy.json()["result"], t_heavy.text
        assert client.get("/").status_code == 200 and client.get("/ops").status_code == 200
        print(
            f"[✓] Public POST /tasks & SPA OK (light->{t_light.json()['assigned_worker']}, "
            f"heavy->{t_heavy.json()['assigned_worker']})"
        )

    print("[✓] ALL SMOKE TEST CHECKS PASSED!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
