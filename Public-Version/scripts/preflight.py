"""Production & Local Deployment Preflight Check Script for CloudBalance.

Validates controller environment contracts, secret strength, worker reachability,
controller port/health state, and writable persistence directories without ever
printing secret values.

Exit codes:
    0 -> zero FAIL checks (PASS / SKIP only)
    1 -> one or more checks returned FAIL
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_LOCAL_HOST,
    WorkerEndpoint,
    parse_worker_endpoints,
)

MIN_SECRET_LENGTH = 32
EXPECTED_WORKER_COUNT = 3
_TRUTHY = frozenset({"1", "true", "yes", "on"})

CheckStatus = Literal["PASS", "FAIL", "SKIP"]


@dataclass(frozen=True)
class CheckOutcome:
    """Result of a single preflight verification check."""

    name: str
    status: CheckStatus
    detail: str


def _has_placeholder(value: str) -> bool:
    return "<" in value or ">" in value


def _env_value(env: Mapping[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in env and env[key] is not None:
            return str(env[key]).strip()
    return default


def load_preflight_env(
    env_file: Path | None = None,
    *,
    use_dotenv: bool = True,
    base_environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load environment configuration for preflight checks.

    - When an explicit `env_file` is supplied, reads strictly from that file so
      invalid/blank values in target `.env` files are never masked by host defaults.
    - Otherwise reads `.env` (if present and `use_dotenv=True`) overlaid by `os.environ`.
    """
    proc_env = dict(os.environ if base_environ is None else base_environ)
    if env_file is not None:
        if not env_file.is_file():
            raise FileNotFoundError(f"Env file not found: {env_file}")
        loaded = dotenv_values(env_file)
        return {k: ("" if v is None else str(v)) for k, v in loaded.items()}

    merged: dict[str, str] = {}
    default_env = ROOT_DIR / ".env"
    if use_dotenv and default_env.is_file():
        loaded = dotenv_values(default_env)
        for k, v in loaded.items():
            merged[k] = "" if v is None else str(v)
    merged.update(proc_env)
    return merged


def _validate_endpoints(raw_urls: str) -> tuple[list[WorkerEndpoint], list[str]]:
    errors: list[str] = []
    if not raw_urls:
        return [], ["WORKER_URLS is missing or blank"]
    if _has_placeholder(raw_urls):
        return [], ["WORKER_URLS contains unreplaced <PLACEHOLDER> text"]

    endpoints = parse_worker_endpoints(raw_urls)
    if len(endpoints) != EXPECTED_WORKER_COUNT:
        errors.append(
            f"WORKER_URLS must parse to {EXPECTED_WORKER_COUNT} endpoints (found {len(endpoints)})"
        )
    for ep in endpoints:
        if ep.scheme not in ("http", "https"):
            errors.append(f"{ep.worker_id} has unsupported scheme '{ep.scheme}'")
        if not ep.host or _has_placeholder(ep.host):
            errors.append(f"{ep.worker_id} has invalid host '{ep.host}'")
        if not (1 <= ep.port <= 65535):
            errors.append(f"{ep.worker_id} has invalid port {ep.port}")
    return endpoints, errors


def check_required_env(env: Mapping[str, str]) -> CheckOutcome:
    """Check 1: secrets >= 32 chars, conditional API key, CB_SEED_DEMO_WORKERS=false, 3 endpoints."""
    errors: list[str] = []

    admin_token = _env_value(env, "ADMIN_TOKEN", "CB_ADMIN_TOKEN")
    if not admin_token:
        errors.append("ADMIN_TOKEN is missing or blank")
    elif _has_placeholder(admin_token):
        errors.append("ADMIN_TOKEN contains <PLACEHOLDER> text")
    elif len(admin_token) < MIN_SECRET_LENGTH:
        errors.append(f"ADMIN_TOKEN length {len(admin_token)} < {MIN_SECRET_LENGTH}")

    worker_secret = _env_value(env, "WORKER_SECRET", "CB_WORKER_SECRET")
    if not worker_secret:
        errors.append("WORKER_SECRET is missing or blank")
    elif _has_placeholder(worker_secret):
        errors.append("WORKER_SECRET contains <PLACEHOLDER> text")
    elif len(worker_secret) < MIN_SECRET_LENGTH:
        errors.append(f"WORKER_SECRET length {len(worker_secret)} < {MIN_SECRET_LENGTH}")

    req_key_raw = _env_value(env, "CB_REQUIRE_API_KEY", "REQUIRE_API_KEY", default="false").lower()
    require_api_key = req_key_raw in _TRUTHY
    api_key = _env_value(env, "CB_API_KEY", "API_KEY")
    if require_api_key and (not api_key or _has_placeholder(api_key)):
        errors.append("CB_API_KEY is required because CB_REQUIRE_API_KEY=true")

    seed_demo_raw = _env_value(env, "CB_SEED_DEMO_WORKERS", "SEED_DEMO_WORKERS")
    if seed_demo_raw.lower() != "false":
        shown = seed_demo_raw if seed_demo_raw else "unset"
        errors.append(f"CB_SEED_DEMO_WORKERS must be 'false' (got '{shown}')")

    worker_urls_raw = _env_value(env, "WORKER_URLS", "CB_WORKER_URLS")
    endpoints, ep_errors = _validate_endpoints(worker_urls_raw)
    errors.extend(ep_errors)

    if errors:
        return CheckOutcome(name="1. Required Environment", status="FAIL", detail="; ".join(errors))

    return CheckOutcome(
        name="1. Required Environment",
        status="PASS",
        detail=(
            f"ADMIN_TOKEN len={len(admin_token)}, WORKER_SECRET len={len(worker_secret)}, "
            f"CB_SEED_DEMO_WORKERS=false, CB_REQUIRE_API_KEY={str(require_api_key).lower()}, "
            f"WORKER_URLS={len(endpoints)} endpoints"
        ),
    )


def _default_probe_port_free(host: str, port: int) -> bool:
    bind_host = DEFAULT_LOCAL_HOST if host in ("", "0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
        except OSError:
            return False
    return True


def _probe_controller_healthz(
    controller_url: str,
    *,
    http_get: Callable[[str], httpx.Response] | None = None,
    timeout_sec: float = 3.0,
) -> tuple[bool, str]:
    url = f"{controller_url.rstrip('/')}/healthz"
    try:
        if http_get is not None:
            resp = http_get(url)
        else:
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.get(url)
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("status") == "ok":
                return True, f"{url} returned 200 ok"
        return False, f"{url} returned HTTP {resp.status_code}"
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return False, f"{url} not reachable ({type(exc).__name__})"


def resolve_controller_target(env: Mapping[str, str], controller_override: str | None = None) -> tuple[str, int, str]:
    """Resolve bind host, controller port, and local/HTTP probe URL."""
    raw_host = _env_value(env, "CONTROLLER_HOST", "CB_CONTROLLER_HOST", default="0.0.0.0")
    bind_host = DEFAULT_LOCAL_HOST if _has_placeholder(raw_host) or not raw_host else raw_host

    port_raw = _env_value(env, "CONTROLLER_PORT", "CB_CONTROLLER_PORT", default="8000")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8000

    if controller_override:
        probe_url = controller_override.rstrip("/")
        parsed = urlparse(probe_url)
        if parsed.port:
            port = parsed.port
        return bind_host, port, probe_url

    raw_url = _env_value(env, "CONTROLLER_URL", "CB_CONTROLLER_URL", "CB_BASE_URL")
    if raw_url and not _has_placeholder(raw_url):
        probe_url = raw_url.rstrip("/")
        parsed = urlparse(probe_url)
        if parsed.port:
            port = parsed.port
        return bind_host, port, probe_url

    probe_host = DEFAULT_LOCAL_HOST if bind_host in ("0.0.0.0", "::") else bind_host
    return bind_host, port, f"http://{probe_host}:{port}"


def check_controller_port(
    host: str,
    port: int,
    controller_url: str,
    *,
    controller_running: bool | None = None,
    http_get: Callable[[str], httpx.Response] | None = None,
    port_free_fn: Callable[[str, int], bool] | None = None,
) -> tuple[CheckOutcome, bool]:
    """Check 2: Verify controller port is free before start, or SKIP if already running."""
    is_running = (
        controller_running
        if controller_running is not None
        else _probe_controller_healthz(controller_url, http_get=http_get)[0]
    )
    if is_running:
        return (
            CheckOutcome(
                name="2. Controller Port",
                status="SKIP",
                detail=f"Controller already running at {controller_url}; pre-start port {port} bind check skipped",
            ),
            True,
        )

    probe_fn = port_free_fn or _default_probe_port_free
    if probe_fn(host, port):
        return (
            CheckOutcome(
                name="2. Controller Port",
                status="PASS",
                detail=f"Port {port} is available before startup",
            ),
            False,
        )

    return (
        CheckOutcome(
            name="2. Controller Port",
            status="FAIL",
            detail=f"Port {port} is already occupied and {controller_url}/healthz did not answer",
        ),
        False,
    )


def _sample_telemetry_probe() -> dict[str, Any]:
    return {
        "worker_id": "preflight-probe",
        "ip_address": "127.0.0.1",
        "port": 8001,
        "cpu_percent": 1.0,
        "memory_total_mb": 1024.0,
        "memory_used_mb": 128.0,
        "memory_percent": 12.5,
        "load_avg_1m": 0.1,
        "active_task_count": 0,
    }


def check_workers_and_secret_rejection(
    endpoints: Sequence[WorkerEndpoint],
    controller_url: str,
    *,
    controller_running: bool,
    http_get: Callable[[str], httpx.Response] | None = None,
    http_post: Callable[[str, dict[str, Any], dict[str, str]], httpx.Response] | None = None,
    timeout_sec: float = 4.0,
) -> CheckOutcome:
    """Check 3: GET /health on each worker and verify missing/wrong WORKER_SECRET is rejected."""
    if not endpoints:
        return CheckOutcome(
            name="3. Worker Reachability & Auth",
            status="FAIL",
            detail="No valid worker endpoints parsed from WORKER_URLS",
        )

    errors: list[str] = []
    healthy_workers: list[str] = []

    with httpx.Client(timeout=timeout_sec) as client:
        for ep in endpoints:
            health_url = f"{ep.url}/health"
            try:
                resp = http_get(health_url) if http_get is not None else client.get(health_url)
                if resp.status_code != 200:
                    errors.append(f"{ep.worker_id} ({health_url}) returned HTTP {resp.status_code}")
                    continue
                body = resp.json()
                if not isinstance(body, dict) or body.get("status") != "healthy":
                    errors.append(f"{ep.worker_id} ({health_url}) unhealthy payload")
                    continue
                healthy_workers.append(ep.worker_id)
            except (httpx.HTTPError, OSError, ValueError) as exc:
                errors.append(f"{ep.worker_id} ({health_url}) unreachable ({type(exc).__name__})")

        auth_note = "telemetry auth probe skipped (controller not running)"
        if controller_running:
            tel_url = f"{controller_url.rstrip('/')}/api/v1/telemetry"
            payload = _sample_telemetry_probe()
            for label, headers in (
                ("missing secret", {}),
                ("wrong secret", {"X-Worker-Secret": "invalid-preflight-secret"}),
            ):
                try:
                    if http_post is not None:
                        r = http_post(tel_url, payload, headers)
                    else:
                        r = client.post(tel_url, json=payload, headers=headers)
                    if r.status_code not in (401, 403):
                        errors.append(
                            f"{tel_url} with {label} returned HTTP {r.status_code} (expected 401/403)"
                        )
                except (httpx.HTTPError, OSError) as exc:
                    errors.append(f"{tel_url} {label} probe failed ({type(exc).__name__})")
            if not any("telemetry" in err for err in errors):
                auth_note = "unauthorized telemetry rejected (401)"

    if errors:
        return CheckOutcome(name="3. Worker Reachability & Auth", status="FAIL", detail="; ".join(errors))

    return CheckOutcome(
        name="3. Worker Reachability & Auth",
        status="PASS",
        detail=f"{len(healthy_workers)}/{len(endpoints)} workers /health ok; {auth_note}",
    )


def check_data_dir_writable(raw_data_dir: str | Path, *, root_dir: Path = ROOT_DIR) -> CheckOutcome:
    """Check 4: Verify CB_DATA_DIR exists or can be created and supports creating/removing files."""
    val = str(raw_data_dir or "").strip() or DEFAULT_DATA_DIR
    if _has_placeholder(val):
        return CheckOutcome(
            name="4. Data Dir Writable",
            status="FAIL",
            detail=f"CB_DATA_DIR contains <PLACEHOLDER> text: '{val}'",
        )

    candidate = Path(val)
    target = candidate if candidate.is_absolute() else (root_dir / candidate)

    try:
        if target.exists() and not target.is_dir():
            return CheckOutcome(
                name="4. Data Dir Writable",
                status="FAIL",
                detail=f"CB_DATA_DIR '{target}' exists and is not a directory",
            )
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".preflight_write_probe_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        with probe.open("wb") as handle:
            handle.write(b"ok")
        probe.unlink()
    except OSError as exc:
        return CheckOutcome(
            name="4. Data Dir Writable",
            status="FAIL",
            detail=f"CB_DATA_DIR '{target}' is not writable ({type(exc).__name__}: {exc})",
        )

    return CheckOutcome(
        name="4. Data Dir Writable",
        status="PASS",
        detail=f"CB_DATA_DIR writable at {target}",
    )


def check_controller_health_and_ready(
    controller_url: str,
    expected_workers: int,
    *,
    controller_running: bool,
    http_get: Callable[[str], httpx.Response] | None = None,
    timeout_sec: float = 4.0,
) -> CheckOutcome:
    """Check 5: When controller is running, verify /healthz and /ready active_workers count."""
    if not controller_running:
        return CheckOutcome(
            name="5. Controller Health & Ready",
            status="SKIP",
            detail=f"Controller not running at {controller_url}; /healthz and /ready skipped",
        )

    base = controller_url.rstrip("/")
    with httpx.Client(timeout=timeout_sec) as client:
        try:
            hz_resp = http_get(f"{base}/healthz") if http_get is not None else client.get(f"{base}/healthz")
            if hz_resp.status_code != 200 or hz_resp.json().get("status") != "ok":
                return CheckOutcome(
                    name="5. Controller Health & Ready",
                    status="FAIL",
                    detail=f"/healthz returned HTTP {hz_resp.status_code}",
                )

            rd_resp = http_get(f"{base}/ready") if http_get is not None else client.get(f"{base}/ready")
            if rd_resp.status_code != 200:
                return CheckOutcome(
                    name="5. Controller Health & Ready",
                    status="FAIL",
                    detail=f"/ready returned HTTP {rd_resp.status_code}",
                )
            rd_data = rd_resp.json()
            if not rd_data.get("ready"):
                return CheckOutcome(
                    name="5. Controller Health & Ready",
                    status="FAIL",
                    detail=f"/ready reported ready={rd_data.get('ready')}",
                )
            active = int(rd_data.get("active_workers", -1))
            if active != expected_workers:
                return CheckOutcome(
                    name="5. Controller Health & Ready",
                    status="FAIL",
                    detail=f"/ready active_workers={active}, expected {expected_workers}",
                )
        except (httpx.HTTPError, OSError, ValueError) as exc:
            return CheckOutcome(
                name="5. Controller Health & Ready",
                status="FAIL",
                detail=f"Controller probe error ({type(exc).__name__}: {exc})",
            )

    return CheckOutcome(
        name="5. Controller Health & Ready",
        status="PASS",
        detail=f"/healthz ok, /ready ready=True, active_workers={active}/{expected_workers}",
    )


def run_preflight(
    env: Mapping[str, str],
    *,
    controller_override: str | None = None,
    timeout_sec: float = 4.0,
) -> list[CheckOutcome]:
    """Run all 5 preflight checks and return ordered CheckOutcome results."""
    env_result = check_required_env(env)
    raw_urls = _env_value(env, "WORKER_URLS", "CB_WORKER_URLS")
    endpoints, _ = _validate_endpoints(raw_urls)

    bind_host, ctrl_port, ctrl_url = resolve_controller_target(env, controller_override=controller_override)
    port_result, ctrl_running = check_controller_port(bind_host, ctrl_port, ctrl_url)

    workers_result = check_workers_and_secret_rejection(
        endpoints,
        ctrl_url,
        controller_running=ctrl_running,
        timeout_sec=timeout_sec,
    )

    raw_data_dir = _env_value(env, "CB_DATA_DIR", "DATA_DIR", default=DEFAULT_DATA_DIR)
    data_dir_result = check_data_dir_writable(raw_data_dir)

    ready_result = check_controller_health_and_ready(
        ctrl_url,
        len(endpoints) if endpoints else EXPECTED_WORKER_COUNT,
        controller_running=ctrl_running,
        timeout_sec=timeout_sec,
    )

    return [env_result, port_result, workers_result, data_dir_result, ready_result]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CloudBalance deployment & cluster preflight checks")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional explicit env file (e.g. /etc/cloudbalance/controller.env)",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Ignore repo .env and read only process environment variables",
    )
    parser.add_argument(
        "--controller",
        default=None,
        help="Override Controller base URL for health/ready/auth probes",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="HTTP probe timeout in seconds (default: 4.0)",
    )
    args = parser.parse_args(argv)

    try:
        env = load_preflight_env(args.env_file, use_dotenv=not args.no_dotenv)
    except OSError as exc:
        print(f"FAIL | 0. Env Load | {exc}", file=sys.stderr)
        return 1

    outcomes = run_preflight(
        env,
        controller_override=args.controller,
        timeout_sec=args.timeout,
    )

    for item in outcomes:
        print(f"{item.status:<4} | {item.name} | {item.detail}")

    failures = sum(1 for item in outcomes if item.status == "FAIL")
    skips = sum(1 for item in outcomes if item.status == "SKIP")
    passes = sum(1 for item in outcomes if item.status == "PASS")
    print(f"SUMMARY: PASS={passes} SKIP={skips} FAIL={failures}")
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
