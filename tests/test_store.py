import pandas as pd
import pytest

from airport_agent.data import store


def _builder(calls: list, fail: bool = False):
    def build():
        calls.append(1)
        if fail:
            raise ConnectionError("API down")
        return pd.DataFrame({"x": [1, 2]}), {"source": "Test API", "url": "https://example.test", "coverage": "2026"}

    return build


def test_live_then_cache(isolated_store):
    calls: list = []
    df, prov = store.fetch_frame("t", "k", _builder(calls), ttl=3600)
    assert prov.mode == "live" and list(df.x) == [1, 2]
    df, prov = store.fetch_frame("t", "k", _builder(calls), ttl=3600)
    assert prov.mode == "cache" and len(calls) == 1
    assert prov.source == "Test API" and prov.coverage == "2026"


def test_expired_cache_served_when_api_fails(isolated_store):
    store.fetch_frame("t", "k", _builder([]), ttl=3600)
    df, prov = store.fetch_frame("t", "k", _builder([], fail=True), ttl=0)
    assert prov.mode == "stale_cache" and "unreachable" in prov.note
    assert list(df.x) == [1, 2]


def test_snapshot_fallback_and_offline(isolated_store):
    store.fetch_frame("t", "k", _builder([]), ttl=3600)
    assert store.snapshot_artifact("t", "k")
    # Fresh machine (empty cache) with the network off: the bundled snapshot answers.
    isolated_store(offline=True)
    (store.settings.cache_dir / "t" / "k.parquet").unlink(missing_ok=True)
    calls: list = []
    df, prov = store.fetch_frame("t", "k", _builder(calls), ttl=3600)
    assert prov.mode == "snapshot" and calls == [] and list(df.x) == [1, 2]


def test_unavailable_raises(isolated_store):
    with pytest.raises(store.DataUnavailable):
        store.fetch_frame("t", "missing", _builder([], fail=True), ttl=3600)
