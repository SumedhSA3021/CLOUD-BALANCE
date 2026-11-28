"""Unit tests for scripts/preflight.py check functions."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from scripts.preflight import (
    CheckOutcome,
    check_controller_health_and_ready,
    check_controller_port,
    check_data_dir_writable,
    check_required_env,
    check_workers_and_secret_rejection,
)

from app.core.config import WorkerEndpoint

VALID_SECRET_A = "A" * 32
VALID_SECRET_B = "B" * 32
THREE_WORKERS = "http://127.0.0.1:8001,http://127.0.0.1:8002,http://127.0.0.1:8003"


def _base_env() -> dict[str, str]:
    return {
        "ADMIN_TOKEN": VALID_SECRET_A,
        "WORKER_SECRET": VALID_SECRET_B,
        "CB_REQUIRE_API_KEY": "false",
        "CB_SEED_DEMO_WORKERS": "false",
        "WORKER_URLS": THREE_WORKERS,
    }


def _resp(status_code: int, json_body: dict | None = None, url: str = "http://127.0.0.1:8000") -> httpx.Response:
    req = httpx.Request("GET", url)
    if json_body is None:
        return httpx.Response(status_code=status_code, request=req)
    return httpx.Response(status_code=status_code, json=json_body, request=req)


def test_required_env_passes_when_valid_and_never_echoes_secret() -> None:
    res = check_required_env(_base_env())
    assert res.status == "PASS"
    assert VALID_SECRET_A not in res.detail
    assert VALID_SECRET_B not in res.detail


@pytest.mark.parametrize(
    "mutated",
    [
        {"ADMIN_TOKEN": ""},
        {"ADMIN_TOKEN": "too-short"},
        {"WORKER_SECRET": ""},
        {"WORKER_SECRET": "short-secret"},
        {"CB_REQUIRE_API_KEY": "true", "CB_API_KEY": ""},
        {"CB_SEED_DEMO_WORKERS": "true"},
        {"CB_SEED_DEMO_WORKERS": ""},
        {"WORKER_URLS": "http://<WORKER_1>:8001,http://127.0.0.1:8002,http://127.0.0.1:8003"},
        {"WORKER_URLS": "http://127.0.0.1:8001,http://127.0.0.1:8002"},
    ],
)
def test_required_env_negative_cases(mutated: dict[str, str]) -> None:
    env = {**_base_env(), **mutated}
    res = check_required_env(env)
    assert isinstance(res, CheckOutcome)
    assert res.status == "FAIL"
    assert VALID_SECRET_A not in res.detail
    assert VALID_SECRET_B not in res.detail


def test_controller_port_check_prestart_skip_and_occupied() -> None:
    res_skip, running = check_controller_port(
        "127.0.0.1",
        8000,
        "http://127.0.0.1:8000",
        controller_running=True,
    )
    assert res_skip.status == "SKIP"
    assert running is True

    res_free, running_free = check_controller_port(
        "127.0.0.1",
        8000,
        "http://127.0.0.1:8000",
        controller_running=False,
        port_free_fn=lambda _h, _p: True,
    )
    assert res_free.status == "PASS"
    assert running_free is False

    res_busy, running_busy = check_controller_port(
        "127.0.0.1",
        8000,
        "http://127.0.0.1:8000",
        controller_running=False,
        port_free_fn=lambda _h, _p: False,
    )
    assert res_busy.status == "FAIL"
    assert running_busy is False


def test_workers_and_secret_rejection_pass_and_fail() -> None:
    eps = [
        WorkerEndpoint("worker-1", "http://127.0.0.1:8001", "http", "127.0.0.1", 8001),
        WorkerEndpoint("worker-2", "http://127.0.0.1:8002", "http", "127.0.0.1", 8002),
        WorkerEndpoint("worker-3", "http://127.0.0.1:8003", "http", "127.0.0.1", 8003),
    ]

    ok = check_workers_and_secret_rejection(
        eps,
        "http://127.0.0.1:8000",
        controller_running=True,
        http_get=lambda u: _resp(200, {"status": "healthy"}, url=u),
        http_post=lambda u, _body, _hdrs: _resp(401, {"detail": "Invalid"}, url=u),
    )
    assert ok.status == "PASS"

    def bad_worker_get(u: str) -> httpx.Response:
        if "8003" in u:
            raise httpx.ConnectError("refused")
        return _resp(200, {"status": "healthy"}, url=u)

    fail_worker = check_workers_and_secret_rejection(
        eps,
        "http://127.0.0.1:8000",
        controller_running=True,
        http_get=bad_worker_get,
        http_post=lambda u, _body, _hdrs: _resp(401, {"detail": "Invalid"}, url=u),
    )
    assert fail_worker.status == "FAIL"

    fail_auth = check_workers_and_secret_rejection(
        eps,
        "http://127.0.0.1:8000",
        controller_running=True,
        http_get=lambda u: _resp(200, {"status": "healthy"}, url=u),
        http_post=lambda u, _body, _hdrs: _resp(200, {"accepted": True}, url=u),
    )
    assert fail_auth.status == "FAIL"


def test_data_dir_writable_and_unwritable(tmp_path: Path) -> None:
    good = check_data_dir_writable(tmp_path / "nested-data")
    assert good.status == "PASS"

    existing_file = tmp_path / "not-a-dir.txt"
    existing_file.write_text("file", encoding="utf-8")
    bad = check_data_dir_writable(existing_file)
    assert bad.status == "FAIL"


def test_controller_health_and_ready_cases() -> None:
    skip = check_controller_health_and_ready("http://127.0.0.1:8000", 3, controller_running=False)
    assert skip.status == "SKIP"

    ok = check_controller_health_and_ready(
        "http://127.0.0.1:8000",
        3,
        controller_running=True,
        http_get=lambda u: _resp(
            200,
            {"status": "ok"} if u.endswith("/healthz") else {"ready": True, "active_workers": 3},
            url=u,
        ),
    )
    assert ok.status == "PASS"

    mismatch = check_controller_health_and_ready(
        "http://127.0.0.1:8000",
        3,
        controller_running=True,
        http_get=lambda u: _resp(
            200,
            {"status": "ok"} if u.endswith("/healthz") else {"ready": True, "active_workers": 2},
            url=u,
        ),
    )
    assert mismatch.status == "FAIL"
