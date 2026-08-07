"""Pytest fixtures and environment bootstrap.

Forces ``DATABASE_URL`` to a safe SQLite URL for the test session so that
``app.config.Settings`` can be instantiated without requiring a live MySQL
instance.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
