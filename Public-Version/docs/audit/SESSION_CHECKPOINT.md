# CloudBalance Session Checkpoint

**Saved At:** `2026-11-26 00:30 IST`  
**Audit Mode Constraint Followed:** Zero edits to application code, tests, config, `frontend/dist`, or `Local-Version/`. Only files under `audit/` were created.

---

## Current Workspace State

- **Cluster:** Stopped (no background cluster or subagents running).
- **Proof Run Artifacts (pre-existing):** [`proof/PROOF_REPORT.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/proof/PROOF_REPORT.md) (`data/test_summary.csv` has 6 proof rows; `data/test_log.csv` has 3,278 rows).
- **PART 1 Static Audit (Items 1–7) Completed & Saved:**
  1. [`audit/01_route_inventory.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/01_route_inventory.md)
  2. [`audit/02_pipeline_trace.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/02_pipeline_trace.md)
  3. [`audit/03_scheduler_analysis.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/03_scheduler_analysis.md)
  4. [`audit/04_counters_locks.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/04_counters_locks.md)
  5. [`audit/05_hardcoded_values.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/05_hardcoded_values.md)
  6. [`audit/06_auth_matrix.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/06_auth_matrix.md)
  7. [`audit/07_sse_ip_cors_ratelimit.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/07_sse_ip_cors_ratelimit.md)
  8. [`audit/STATIC_AUDIT_REPORT.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/STATIC_AUDIT_REPORT.md)

---

## Top Open Findings to Resume Tomorrow

1. **WebSocket disconnected on `/benchmark`:** `DashboardPage.tsx:8` calls `useWebSocket()` without `token`.
2. **Nginx & Docker/GCP drift:** `infra/nginx/nginx.conf` omits `/tasks`, `/admin/*`, `/test/status`, `/healthz`; `docker-compose.yml` and `infra/gcp/startup-*.sh` omit required `ADMIN_TOKEN`/`WORKER_SECRET`/`WORKER_URLS`.
3. **Out-of-pipeline benchmark issues:** `backend/app/api/benchmark.py` mutates global `SOLVER_CALL_COUNT` outside test lock; `benchmark/run_benchmark.py:46` imports deleted `LeastConnectionsScheduler`.
4. **Mode split-brain:** `start_test`/`end_test` writes Redis `sched_mode` without syncing `scheduler_state`, and leaves `sched_mode` behind after returning to `idle`.
5. **In-test 4xx cleanup leak & lock scope:** `HTTPException(400/413/422)` skips `complete_inflight_task`/`record_assigned` (`tasks.py:349-582`); `workers_cache` is read outside `milp_dispatch_lock` (`tasks.py:270,499`).
6. **Hardcodes & auth/config mismatches:** Hardcoded `worker-1..3` in `admin.py:323`/`test_hooks.py:23`/`live_stats.py:10`/`OpsCenterPage.tsx:56`; `POST /tasks` vs `/api/v1/tasks` disagree on `verify_api_key`; `Settings.api_key` defaults to `"cb-dev-api-key-2026"`; `backend/.env` shadows root `.env`; `Local-Version/` still tracks `"cb-admin-secret-2026"` while `.gitignore` excludes root `backend/`, `frontend/`, `worker/`.

---

## Pending From User

- Provide **PART 2** of the final audit (if any) or confirm which findings from [`audit/STATIC_AUDIT_REPORT.md`](file:///c:/Users/sumed/Desktop/CLOUD%20BALANCE/audit/STATIC_AUDIT_REPORT.md) to fix first.
