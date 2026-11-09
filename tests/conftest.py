import os
import sys
import importlib.util

import fakeredis
import redis
import pytest

# Env vars must exist before service modules are imported (they read os.getenv at module level)
os.environ.setdefault("REDIS_HOST", "testredis")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:0")
os.environ.setdefault("AISSTREAM_API_KEY", "test-key")

# One shared fake Redis server so every service module sees the same data,
# matching how they all connect to the same real Redis in production.
SHARED_SERVER = fakeredis.FakeServer()


def _fake_redis(**kwargs):
    return fakeredis.FakeStrictRedis(server=SHARED_SERVER, decode_responses=kwargs.get("decode_responses", False))


redis.Redis = _fake_redis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES = os.path.join(ROOT, "services")


def load_module(name, relpath):
    """Import a service module by file path (services aren't packages)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(SERVICES, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def clean_redis():
    fakeredis.FakeStrictRedis(server=SHARED_SERVER).flushall()
    yield
