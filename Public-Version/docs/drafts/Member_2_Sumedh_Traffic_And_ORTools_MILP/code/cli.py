"""CLI Entrypoint `cb-traffic` for Multi-Laptop CloudBalance Traffic Generation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from traffic.poisson_generator import PoissonTrafficGenerator
from traffic.workloads import ScenarioType, WorkloadMix


def build_parser() -> argparse.ArgumentParser:
    """Create argument parser matching exact CloudBalance CLI specification."""
    parser = argparse.ArgumentParser(
        prog="cb-traffic",
        description="CloudBalance Seedable Poisson Workload Traffic Generator",
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default="http://localhost:8000",
        help="Public URL of the CloudBalance Controller (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--client-id",
        type=str,
        default="laptop-alpha",
        help="Unique identifier for this client laptop",
    )
    parser.add_argument(
        "--lambda",
        dest="lambda_rate",
        type=float,
        default=4.0,
        help="Mean Poisson arrival rate lambda in tasks/sec (default: 4.0)",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=50,
        help="Maximum number of tasks to send before exiting (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic RNG seed (default: 42)",
    )
    parser.add_argument(
        "--mix",
        type=str,
        choices=[m.value for m in WorkloadMix],
        default=WorkloadMix.BALANCED.value,
        help="Task resource mix: cpu | mem | balanced (default: balanced)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        choices=[s.value for s in ScenarioType],
        default=ScenarioType.STEADY.value,
        help="Temporal traffic scenario: steady | burst | ramp (default: steady)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Optional X-API-Key header value for controller authentication",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate deterministic Poisson trace and print summary JSON without HTTP calls",
    )
    return parser


async def _run_cli_async(args: argparse.Namespace) -> int:
    generator = PoissonTrafficGenerator(
        client_id=args.client_id,
        lambda_rate=args.lambda_rate,
        mix=WorkloadMix(args.mix),
        scenario=ScenarioType(args.scenario),
        seed=args.seed,
    )

    if args.dry_run:
        trace = generator.generate_trace(max_tasks=args.max_tasks)
        type_counts: dict[str, int] = {}
        for ev in trace:
            type_counts[ev.task_type] = type_counts.get(ev.task_type, 0) + 1
        output = {
            "mode": "dry_run",
            "client_id": args.client_id,
            "lambda_rate": args.lambda_rate,
            "mix": args.mix,
            "scenario": args.scenario,
            "seed": args.seed,
            "total_events": len(trace),
            "simulated_duration_sec": trace[-1].arrival_time_sec if trace else 0.0,
            "task_type_counts": type_counts,
        }
        print(json.dumps(output, indent=2))
        return 0

    summary = await generator.run_against_target(
        target_url=args.target_url,
        max_tasks=args.max_tasks,
        api_key=args.api_key,
        realtime_sleep=True,
    )
    print(
        json.dumps(
            {
                "mode": "live",
                "client_id": summary.client_id,
                "sent_count": summary.sent_count,
                "accepted_count": summary.accepted_count,
                "backpressured_429_count": summary.backpressured_429_count,
                "error_count": summary.error_count,
                "elapsed_sec": summary.elapsed_sec,
                "effective_rate_per_sec": summary.effective_rate_per_sec,
                "task_type_counts": summary.task_type_counts,
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `cb-traffic`."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run_cli_async(args))


if __name__ == "__main__":
    sys.exit(main())

