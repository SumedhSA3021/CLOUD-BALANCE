"""Structural & dependency consistency invariants across repository manifests."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
_REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_,\-]+\])?==[^;\s]+)(.*)$")


def _parse_req_list(items: list[str]) -> dict[str, tuple[str, str]]:
    parsed: dict[str, tuple[str, str]] = {}
    for raw in items:
        clean = raw.strip()
        if not clean or clean.startswith("#"):
            continue
        m = _REQ_LINE_RE.match(clean)
        assert m, f"Dependency specification must use exact '==' pin: {raw!r}"
        pkg_spec, marker = m.group(1), m.group(2).strip().replace("'", '"')
        name = pkg_spec.split("==", 1)[0].split("[", 1)[0].lower()
        ver = pkg_spec.split("==", 1)[1]
        parsed[f"{name}|{marker}"] = (pkg_spec.lower(), ver)
    return parsed


def test_backend_requirements_matches_pyproject_dependencies() -> None:
    """Ensure backend/requirements.txt and backend/pyproject.toml share identical runtime pins."""
    be_toml = tomllib.loads((ROOT_DIR / "backend/pyproject.toml").read_text(encoding="utf-8"))
    be_req_lines = (ROOT_DIR / "backend/requirements.txt").read_text(encoding="utf-8").splitlines()

    toml_deps = _parse_req_list(list(be_toml["project"]["dependencies"]))
    req_deps = _parse_req_list(be_req_lines)
    assert toml_deps == req_deps


def test_shared_package_versions_consistent_across_controller_worker_and_traffic() -> None:
    """Prevent silent version skew between controller, worker, and traffic manifests."""
    be_req = _parse_req_list((ROOT_DIR / "backend/requirements.txt").read_text(encoding="utf-8").splitlines())
    wk_req = _parse_req_list((ROOT_DIR / "worker/requirements.txt").read_text(encoding="utf-8").splitlines())
    tr_toml = tomllib.loads((ROOT_DIR / "traffic/pyproject.toml").read_text(encoding="utf-8"))
    tr_deps = _parse_req_list(list(tr_toml["project"]["dependencies"]))

    for key, (wk_spec, wk_ver) in wk_req.items():
        assert key in be_req, f"Worker dependency {wk_spec} missing from backend/requirements.txt"
        assert be_req[key][1] == wk_ver, f"Version skew for {key}: {be_req[key][1]} vs {wk_ver}"

    for key, (tr_spec, tr_ver) in tr_deps.items():
        assert key in be_req, f"Traffic dependency {tr_spec} missing from backend/requirements.txt"
        assert be_req[key][1] == tr_ver, f"Version skew for {key}: {be_req[key][1]} vs {tr_ver}"


def test_consolidated_directory_layout_preserved() -> None:
    """Confirm docs consolidation and single scripts/ directory are intact with zero lost files."""
    for expected in (
        "docs/audit/FINAL_STRUCTURE_REPORT.md",
        "docs/audit/STRUCTURE_AUDIT.md",
        "docs/proof/PROOF_REPORT.md",
        "docs/project-reports/CHANGES_AND_UPGRADE_TASK_SHEET.md",
        "docs/project-reports/CloudBalance_Team_Workflow.html",
        "docs/drafts/00_Project_Introduction_And_Backend_API_Architecture.md",
        "scripts/load_client.py",
        "scripts/preflight.py",
        "deploy/controller.env.example",
        "infra/gcp/provision.sh",
    ):
        assert (ROOT_DIR / expected).exists(), f"Missing consolidated file: {expected}"

    for stale in ("audit", "proof", "tools", "Local-Version", "Public-Version"):
        assert not (ROOT_DIR / stale).exists(), f"Stale root directory should not exist: {stale}"
