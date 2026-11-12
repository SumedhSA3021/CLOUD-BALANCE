# CloudBalance Multi-Scheduler Benchmark Report

- **Run ID**: `bench-6e4a8526`
- **Deterministic RNG Seed**: `42`
- **Total Superposed Tasks**: `120` across 3 heterogeneous client laptops (`laptop-alpha-cpu`, `laptop-beta-mem`, `laptop-gamma-burst`)
- **Simulated Stream Duration**: `8.24s`

## Summary Comparison Table

| Scheduler | Mean CPU StdDev (%) | Max CPU StdDev (%) | Peak CPU (%) | Peak RAM (%) | Cap Violations | Mean Latency (ms) | P95 Latency (ms) | Mean Solver (ms) | Throughput (tasks/s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `ortools_milp` | **5.11%** | 15.85% | 83.3% | 79.2% | **0** | 385.8 | 514.2 | 10.211 | 14.56 |
| `least_connections` | **10.88%** | 24.29% | 88.9% | 71.6% | **3** | 397.1 | 574.6 | 0.015 | 14.56 |
| `round_robin` | **11.04%** | 24.36% | 88.9% | 71.6% | **3** | 397.5 | 574.6 | 0.009 | 14.56 |

## Key Findings

1. **Cluster Load Balance (CPU Standard Deviation)**:
   - `ortools_milp` achieved a mean CPU standard deviation of **5.11%**, outperforming `least_connections` (**10.88%**) and `round_robin` (**11.04%**).
2. **Hard SLA Capacity Cap Enforcement (>85% CPU, >90% RAM)**:
   - `ortools_milp` recorded **0** capacity violations compared to **3** for `least_connections` and **3** for `round_robin`.
3. **Completion Latency & Solver Overhead**:
   - Despite solving a Mixed-Integer Linear Program per micro-batch (`10.211 ms` average solver latency, well within the `50 ms` budget), `ortools_milp` achieved the lowest P95 task completion latency (**514.2 ms** vs **574.6 ms** on `round_robin`) by preventing worker CPU/RAM thrashing.
