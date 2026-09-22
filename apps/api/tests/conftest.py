"""Test configuration.

Unit tests (tests/unit) are pure and need nothing. Integration tests (tests/integration) run against a
real PostgreSQL database (TEST_DATABASE_URL, default: the docker-compose Postgres, database gtmos_test).
The schema is created once per session and seeded with a small deterministic demo universe; every test
runs inside a transaction that is rolled back, so tests are isolated and order-independent.
"""

from __future__ import annotations

import os

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://gtmos:gtmos@localhost:56432/gtmos_test")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["ENV"] = "test"
os.environ["QUEUE_BACKEND"] = "inline"
os.environ["SEED_ACCOUNTS"] = "150"
# Never let a developer's shell credentials reach tests.
for var in (
    "ANTHROPIC_API_KEY",
    "HUBSPOT_ACCESS_TOKEN",
    "APOLLO_API_KEY",
    "ADMIN_API_TOKEN",
    "WEBHOOK_SECRET",
    "LLM_ENABLED",
    "HUBSPOT_LIVE_WRITES_ENABLED",
    "REDIS_URL",
):
    os.environ.pop(var, None)
