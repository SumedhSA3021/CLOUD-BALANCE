# 07 — SSE, IP Logging, CORS & Rate Limiter Audit

**Goal:** Verify (1) zero SSE usage, (2) zero IP logging, (3) clean CORS configuration, and (4) rate limiter keyed strictly on `client_id` (not IP).  
**Verdict:** **PASS** on zero SSE & `client_id`-keyed rate limiting (**WARN** on permissive CORS default `["*"]`, Nginx proxy `X-Real-IP`/`X-Forwarded-For` + uvicorn default access logs, dead `rate_limit_per_sec` config, and unbounded >1024 bucket edge case in `ClientRateLimiter`).

---

## 1. SSE Usage Check (Requirement: Must Be None)

- **Result:** **PASS (0 matches).**
- Raw static search across `backend/`, `worker/`, `frontend/src/`, `tools/`, `traffic/`, `scripts/`, `tests/`, `infra/`:
  - Pattern `EventSource|text/event-stream|\bSSE\b|StreamingResponse`: **No matches found**.
  - Live cluster telemetry uses WebSockets (`/ws`, `backend/app/api/websocket.py:13`) and HTTP polling (`/test/status`, `/admin/stats/live`), never Server-Sent Events.

---

## 2. Client IP Logging Check (Requirement: Must Be None)

- **Result:** **PASS in Python/CSV/DB application code; WARN at HTTP server / reverse-proxy layer.**
- Raw static search across `backend/`, `worker/`, `frontend/src/`, `tools/`, `traffic/`, `scripts/`, `tests/`, `infra/`:
  ```text
  backend\app\core\config.py:152: rate_limit_per_sec: int = Field(
  backend\app\core\config.py:155: validation_alias=AliasChoices("CB_RATE_LIMIT_PER_SEC", "RATE_LIMIT_PER_SEC"),
  infra\nginx\nginx.conf:18: proxy_set_header X-Real-IP $remote_addr;
  infra\nginx\nginx.conf:19: proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  infra\nginx\nginx.conf:20: proxy_set_header X-Forwarded-Proto $scheme;
  infra\nginx\nginx.conf:39: proxy_set_header X-Real-IP $remote_addr;
  ```
- Note on `ip_address` in codebase: `Telemetry.ip_address` (`schemas.py:158`) and `WorkerSnapshotItem.ip_address` (`schemas.py:181`) store **worker node addresses**, never external client IPs. `data/test_log.csv` (`logger.py:35-56`) and `Assignment` (`schemas.py:257-277`) contain zero client IP columns.
- Operational caveat:
  1. `backend/run_cluster.py:160-169` launches controller `uvicorn app.main:app` **without `--no-access-log`**, so Uvicorn's default stdout access logger records TCP peer IP (`127.0.0.1` locally) per HTTP request.
  2. `infra/nginx/nginx.conf:18-19, 39` forwards `$remote_addr` / `$proxy_add_x_forwarded_for` and Nginx default access logs record client IPs if used.

---

## 3. CORS Configuration (`backend/app/main.py:120-126`, `backend/app/core/config.py:119-122, 251-260`)

```python
# backend/app/main.py:120-126
application.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
- `Settings.allowed_origins` (`config.py:119-122`) parses comma-separated `CB_ALLOWED_ORIGINS` / `ALLOWED_ORIGINS` (`config.py:251-260`).
- Local `.env` sets `CB_ALLOWED_ORIGINS="http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000,http://127.0.0.1:5173"`.
- Same-origin serving (`/` SPA served from `:8000` / single Cloudflare tunnel URL) means browser fetches use same-origin relative URLs (`""` in `api.ts:8`).
- **Findings (`WARN`):**
  1. **Permissive fallback default (`["*"]`)** in `config.py:120` if `CB_ALLOWED_ORIGINS` is omitted in `.env`.
  2. `allow_methods=["*"]` and `allow_headers=["*"]` are wildcarded (though `allow_credentials=False` avoids credentialed wildcard exposure).
  3. **WebSocket `/ws` (`websocket.py:13-18`)** does not validate `Origin` header (FastAPI `CORSMiddleware` applies to HTTP only; mitigated by mandatory `verify_admin_ws_token`).

---

## 4. Rate Limiter Key & Edge-Case Analysis (`backend/app/core/security.py:19-50`, `tasks.py:221-223`)

- **Keying:** `ClientRateLimiter.check_and_record(req.client_id, test_active=is_test_running())` (`tasks.py:223`) keys strictly on `self._hits[client_id]` (`security.py:34`) — **never by client IP or `X-Forwarded-For`**. Safe behind NAT / Cloudflare Tunnel where all laptops share one proxy IP. **PASS**.
- **Limits:**
  - `Settings.rate_limit_per_min` defaults to `2400` (`config.py:158`).
  - During an active test (`test_active=True`), `effective_limit = max(1200, self.limit_per_min)` (`security.py:30`), guaranteeing >= 1200 req/min/client floor. **PASS**.
- **Findings (`WARN`):**
  1. **Dead `RATE_LIMIT_PER_SEC` setting (`config.py:152-156`, `.env.example:35`):** `rate_limit_per_sec: int = 300` is defined in `Settings` and `.env.example`, yet **never referenced** anywhere in `backend/app/`.
  2. **Unbounded `_hits` dict under >1024 active `client_id` values (`security.py:46-49`):** Pruning only deletes buckets where `dq[-1] <= cutoff`; if >1024 distinct `client_id` strings arrive within one 60s window, `self._hits` grows without an LRU cap (and because `client_id` comes from request JSON, an attacker rotating `client_id` strings bypasses per-client throttling).
  3. **Missing rate limit on `/admin/auth/login` (`admin.py:457`):** Rate limiter only runs on `POST /tasks`, `POST /api/v1/tasks`, and `/control/traffic`, leaving `/admin/auth/login` unthrottled against brute-force token guessing.
