# CloudBalance End-to-End Proof Report (`MILP` vs `Round Robin`)

**Test Parameters (all 6 runs):** `duration_s=60.0`, `lambda_per_client=3.0`, `heavy_ratio=0.3`, `seed=42`, `load_source="external"`, 3 concurrent `tools/load_client.py` processes (`laptop-1..3`, `--controller http://localhost:8000`), `30s` rest between tests.
**Pre-Run Setup:** Started cluster via `scripts/run_local.ps1` (`ready=true`, `active_workers=3`, `redis_backend=in_memory_ttl`, `persistence_backend=sqlite_fallback`) and cleared prior logs via `POST /admin/stats/reset` (`{"status": "reset", "detail": "Test logs and summaries cleared"}`).
**Application Code Policy:** Zero application code files were modified during this proof run.

---

## 1. All 6 Summary Rows (`data/test_summary.csv` + `data/test_log.csv` Queue/Exec Means)

| Round | Mode | `test_id` | `requests` | `failed` | `avg_ms` | `p50_ms` | `p95_ms` | `max_ms` | `avg_queue_ms` | `avg_exec_ms` | `throughput_rps` | `busy_time_stddev` |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `milp` | `test-34814a71` | 546 | 0 | 161.45 | 115.98 | 336.48 | 655.85 | 2.52 | 120.59 | 9.1 | 1831.95 |
| 1 | `round_robin` | `test-fa042816` | 546 | 0 | 158.12 | 114.49 | 357.41 | 564.14 | 0.45 | 119.99 | 9.1 | 1003.13 |
| 2 | `milp` | `test-7b2d9fc6` | 546 | 0 | 169.50 | 123.56 | 356.39 | 802.47 | 3.24 | 125.73 | 9.1 | 1006.01 |
| 2 | `round_robin` | `test-0594d770` | 546 | 0 | 160.65 | 111.94 | 339.72 | 602.76 | 1.56 | 121.18 | 9.1 | 2153.69 |
| 3 | `milp` | `test-ac91cd00` | 546 | 0 | 182.49 | 139.98 | 386.87 | 636.86 | 2.74 | 134.22 | 9.1 | 2576.93 |
| 3 | `round_robin` | `test-02881729` | 546 | 0 | 172.84 | 129.27 | 369.79 | 612.38 | 1.06 | 128.45 | 9.1 | 885.26 |

Raw `data/test_summary.csv`:

```csv
test_id,mode,seed,duration_s,lambda_per_client,heavy_ratio,requests,failed,avg_ms,p50_ms,p95_ms,max_ms,max_queue_ms,throughput_rps,worker1_busy_ms,worker2_busy_ms,worker3_busy_ms,busy_time_stddev
test-34814a71,milp,42,60.0,3.0,0.3,546,0,161.45,115.98,336.48,655.85,394.93,9.1,20122.69,21269.03,24453.07,1831.95
test-fa042816,round_robin,42,60.0,3.0,0.3,546,0,158.12,114.49,357.41,564.14,181.1,9.1,22856.12,22185.93,20473.75,1003.13
test-7b2d9fc6,milp,42,60.0,3.0,0.3,546,0,169.5,123.56,356.39,802.47,480.48,9.1,23826.69,21488.64,23331.77,1006.01
test-0594d770,round_robin,42,60.0,3.0,0.3,546,0,160.65,111.94,339.72,602.76,309.24,9.1,23695.75,23457.91,19012.81,2153.69
test-ac91cd00,milp,42,60.0,3.0,0.3,546,0,182.49,139.98,386.87,636.86,235.38,9.1,25150.45,20973.94,27161.0,2576.93
test-02881729,round_robin,42,60.0,3.0,0.3,546,0,172.84,129.27,369.79,612.38,201.24,9.1,23941.81,24063.33,22127.6,885.26
```

---

## 2. Per-Mode Mean & Std-Dev Across the 3 Rounds (`n = 3`)

*(Both population std-dev `pstdev` and sample std-dev `stdev` shown for completeness.)*

| Metric | MILP Mean | MILP `pstdev` | MILP `stdev` | Round Robin Mean | RR `pstdev` | RR `stdev` | MILP vs RR Mean Diff |
|---|---:|---:|---:|---:|---:|---:|---:|
| `requests` | 546.00 | 0.00 | 0.00 | 546.00 | 0.00 | 0.00 | 0.0% |
| `failed` | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0% |
| `avg_ms` | 171.15 | 8.67 | 10.62 | 163.87 | 6.43 | 7.87 | +4.4% |
| `p50_ms` | 126.51 | 10.02 | 12.27 | 118.57 | 7.64 | 9.36 | +6.7% |
| `p95_ms` | 359.91 | 20.72 | 25.38 | 355.64 | 12.34 | 15.11 | +1.2% |
| `max_ms` | 698.39 | 74.00 | 90.63 | 593.09 | 20.85 | 25.53 | +17.8% |
| `avg_queue_ms` | 2.83 | 0.30 | 0.37 | 1.02 | 0.45 | 0.56 | +177.5% |
| `avg_exec_ms` | 126.85 | 5.62 | 6.88 | 123.21 | 3.74 | 4.58 | +3.0% |
| `throughput_rps` | 9.10 | 0.00 | 0.00 | 9.10 | 0.00 | 0.00 | 0.0% |
| `busy_time_stddev` | 1804.96 | 641.61 | 785.81 | 1347.36 | 572.19 | 700.78 | +34.0% |

---

## 3. Checks A–I (Verdict + Raw Evidence)

### Check A — Summary Row Count == `requests` == `test_log.csv` Rows
- **Verdict:** **PASS**
- **Evidence:** All 6 runs have 1 matching row in `data/test_summary.csv` and exact row counts in `data/test_log.csv`:
  - `test-34814a71`: summary `requests=546`, `test_log.csv` rows = `546`
  - `test-fa042816`: summary `requests=546`, `test_log.csv` rows = `546`
  - `test-7b2d9fc6`: summary `requests=546`, `test_log.csv` rows = `546`
  - `test-0594d770`: summary `requests=546`, `test_log.csv` rows = `546`
  - `test-ac91cd00`: summary `requests=546`, `test_log.csv` rows = `546`
  - `test-02881729`: summary `requests=546`, `test_log.csv` rows = `546`
  - Total `data/test_log.csv` rows after Check I: `3278` (`6 * 546 + 2 = 3278`).

### Check B — Client `sent` Sum == `requests` & `failed == 0`
- **Verdict:** **PASS**
- **Evidence:** Every test caught `Test Armed:` (`armed_seen=True`) on all 3 `load_client.py` processes and printed identically across all 6 runs:
  - `laptop-1`: `sent: 167 | ok: 167 | failed: 0`
  - `laptop-2`: `sent: 188 | ok: 188 | failed: 0`
  - `laptop-3`: `sent: 191 | ok: 191 | failed: 0`
  - Sum: `167 + 188 + 191 = 546 == requests`, `failed == 0` in both clients and `test_summary.csv`.

### Check C — Identical Workload Split Across Modes Per Round
- **Verdict:** **PASS**
- **Evidence:** For each Round (`1`, `2`, `3`), both `milp` and `round_robin` logged exact identical per-client counts and task-type splits in `data/test_log.csv`:
  - `laptop-1`: `167` total (`48` heavy, `119` light)
  - `laptop-2`: `188` total (`61` heavy, `127` light)
  - `laptop-3`: `191` total (`64` heavy, `127` light)

### Check D — Round Robin Strict Cycling, Zero Failover, Zero Solver Calls
- **Verdict:** **PASS**
- **Evidence (from `data/test_log.csv` + `GET /api/v1/control/solver-metrics`):**
  - Round 1 (`test-fa042816`): `dispatch_seq` contiguous `1..546`, `assigned_worker == worker-((seq-1)%3 + 1)` on all 546 rows, `failover={'false'}`, `scheduler_used={'round_robin'}`, `solver_call_count=0`.
  - Round 2 (`test-0594d770`): `dispatch_seq` contiguous `1..546`, strict `worker-1/2/3` cycle on all 546 rows, `failover={'false'}`, `scheduler_used={'round_robin'}`, `solver_call_count=0`.
  - Round 3 (`test-02881729`): `dispatch_seq` contiguous `1..546`, strict `worker-1/2/3` cycle on all 546 rows, `failover={'false'}`, `scheduler_used={'round_robin'}`, `solver_call_count=0`.

### Check E — MILP `solver_call_count > 0` and `scheduler_used=milp`
- **Verdict:** **FAIL (exact label mismatch on `scheduler_used`)**
- **Evidence:**
  - `solver_call_count`: `546` in Round 1 (`test-34814a71`), `546` in Round 2 (`test-7b2d9fc6`), `546` in Round 3 (`test-ac91cd00`) (`> 0` passes).
  - `mode` column in `data/test_log.csv`: `"milp"` on all 546 rows of each MILP run.
  - **`scheduler_used` column in `data/test_log.csv`:** `"ortools_milp"` on all 546 rows of each MILP run (`backend/app/api/tasks.py` sets `scheduler_used = "ortools_milp"`), not the literal string `"milp"`.

### Check F — Recomputed `busy_time_stddev` Matches `test_summary.csv`
- **Verdict:** **PASS**
- **Evidence (`statistics.pstdev` over per-worker `sum(exec_ms)` where `status="ok"`):**
  - `test-34814a71`: log sums `[20122.69, 21269.03, 24453.07]` → recomputed `1831.95` == CSV `1831.95` (diff `0.0`)
  - `test-fa042816`: log sums `[22856.12, 22185.93, 20473.75]` → recomputed `1003.13` == CSV `1003.13` (diff `0.0`)
  - `test-7b2d9fc6`: log sums `[23826.69, 21488.64, 23331.77]` → recomputed `1006.01` == CSV `1006.01` (diff `0.0`)
  - `test-0594d770`: log sums `[23695.75, 23457.91, 19012.81]` → recomputed `2153.69` == CSV `2153.69` (diff `0.0`)
  - `test-ac91cd00`: log sums `[25150.45, 20973.94, 27161.00]` → recomputed `2576.93` == CSV `2576.93` (diff `0.0`)
  - `test-02881729`: log sums `[23941.81, 24063.33, 22127.60]` → recomputed `885.26` == CSV `885.26` (diff `0.0`)

### Check G — Mode Lock & Single Active Test Enforcement
- **Verdict:** **PASS**
- **Evidence (probed live during Round 1 `milp` in `state="running"`):**
  - `POST /api/v1/control/scheduler` `{"scheduler": "round_robin"}` → **HTTP `409`**: `{"detail": "Cannot change scheduling mode while an automated test is running (mode is locked)."}`
  - `POST /admin/test/start` (second concurrent test) → **HTTP `409`**: `{"detail": "Another test is already active in state 'running'. Only one test at a time."}`

### Check H — Security & Public/Protected Endpoint Gatekeeping
- **Verdict:** **PASS** *(note on SPA HTML shells below)*
- **Evidence (unauthenticated `GET` responses):**
  - `/api/v1/telemetry/workers` (`/ops` live workers): **`401`**
  - `/api/v1/control/snapshot` (`/ops` live snapshot): **`401`**
  - `/admin/stats/summary`: **`401`**
  - `/api/v1/telemetry/redis`: **`401`**
  - `/api/v1/benchmark/runs` (`/benchmark` data): **`401`**
  - `/ops` and `/benchmark` SPA routes: **`200`** (serve React HTML wrapped in `<AdminAuthGate>`, which prompts for `ADMIN_TOKEN` and receives `401` on all underlying API calls).
  - `/healthz`: **`200`**
  - `/test/status`: **`200`**
  - `/`: **`200`**

### Check I — Public Path Outside Test (`client_id="web"`, `test_id="none"`)
- **Verdict:** **PASS**
- **Evidence:** After tests returned to `idle`:
  - `light` task (`tsk-199b284c19`): HTTP **`200`**, `assigned_worker="worker-1"`, `queue_ms=0.02`, `exec_ms=49.28`, `total_ms=69.57`, logged to `data/test_log.csv` with `test_id="none"`, `client_id="web"`, `status="ok"`.
  - `heavy` task (`tsk-e6338bb3fd`): HTTP **`200`**, `assigned_worker="worker-2"`, `queue_ms=0.02`, `exec_ms=190.27`, `total_ms=214.07`, logged to `data/test_log.csv` with `test_id="none"`, `client_id="web"`, `status="ok"`.

---

## 4. Reported Findings / Bugs Observed (No Code Changed)

1. **`scheduler_used` Label Discrepancy in MILP (Check E FAIL):**
   - `backend/app/api/tasks.py` records `mode="milp"` and `scheduler_used="ortools_milp"` in `data/test_log.csv`, causing an exact-string mismatch if an automated check asserts `scheduler_used == "milp"`.
2. **MILP Imbalance & Latency Regression on Local Single-Host Runs (`milp` vs `round_robin`):**
   - Across all 3 rounds on one host, MILP had higher mean latency (`171.15 ms` vs `163.87 ms`), higher mean queue delay (`2.83 ms` vs `1.02 ms`), and higher `busy_time_stddev` (`1804.96 ms` vs `1347.36 ms`).
   - Per-worker counts in `data/test_log.csv` explain why:
     - `R1 milp`: total `{w1: 182, w2: 182, w3: 182}`, heavy `{w1: 52, w2: 49, w3: 72}`
     - `R2 milp`: total `{w1: 182, w2: 182, w3: 182}`, heavy `{w1: 60, w2: 47, w3: 66}`
     - `R3 milp`: total `{w1: 182, w2: 182, w3: 182}`, heavy `{w1: 59, w2: 35, w3: 79}`
     - Contrast `round_robin`: `R1` heavy `{w1: 62, w2: 60, w3: 51}`, `R2` heavy `{w1: 59, w2: 66, w3: 48}`, `R3` heavy `{w1: 60, w2: 62, w3: 51}`.
   - **Root cause in `backend/app/schedulers/ortools_milp.py` + `backend/run_cluster.py`:**
     - `cumul_penalty = min(20.0, float(rel_cumul) * 5.0)` forces total dispatched counts (`all`) to tie at `182` per worker regardless of task weight.
     - With staggered virtual baseline CPU profiles (`worker-3` `9%`, `worker-1` `12%`, `worker-2` `18%`) and `λ=3` req/s/client (~`9` req/s total, where most arrivals see `in_flight == 0`), MILP's minimax peak-CPU objective repeatedly places `heavy` (`35%` CPU) tasks onto `worker-3` (`72`, `66`, `79` heavy tasks) and offloads `light` tasks onto `worker-2` (`35`–`49` heavy tasks). Because heavy SHA-256 loops take ~`200–350 ms` of real CPU while light CGPA takes ~`45–75 ms`, steering heavy tasks disproportionately to `worker-3` inflates `worker-3`'s cumulative `exec_ms`, increases local worker semaphore queueing on `worker-3`, and raises `busy_time_stddev`. Running 546 per-task CBC solves on the same CPU core as the 3 local workers adds minor CPU contention as well.
