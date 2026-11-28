"""Root pytest defaults for environments without a local .env file."""

from __future__ import annotations

import os

os.environ.setdefault("CB_LOCAL_MODE", "true")
os.environ.setdefault("CB_REQUIRE_API_KEY", "false")
os.environ.setdefault("ADMIN_TOKEN", "cb-admin-test-token")
os.environ.setdefault("WORKER_SECRET", "cb-worker-test-secret")
