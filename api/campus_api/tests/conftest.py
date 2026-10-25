import os
import tempfile

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("STAFF_KEY", "test-key")
    # Reimport so config/db pick up the env vars set above.
    import importlib
    from campus_api import config, db, seed
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(seed)
    from campus_api.main import app
    from fastapi.testclient import TestClient
    from campus_api.ratelimit import hold_limiter
    hold_limiter.reset()
    hold_limiter.configure(max_calls=1000, window_seconds=10)
    with TestClient(app) as c:
        yield c
