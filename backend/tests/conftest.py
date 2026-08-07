"""Pytest bootstrap and shared fixtures.

This module runs at collection time and unconditionally sets safe defaults
for required environment variables BEFORE any application code is imported.
This guarantees tests never touch a real MySQL instance or rely on whatever
the developer's local ``.env`` happens to contain.

Variables forced (overriding any existing value):
- ``DATABASE_URL`` -> in-memory SQLite
- ``JWT_SECRET``   -> a fixed test value (matches the new required-field contract)
"""

import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret"
