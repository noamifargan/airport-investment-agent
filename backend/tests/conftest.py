import pytest

from airport_agent import config
from airport_agent.data import store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point the artifact store at temp cache/snapshot dirs. Returns a function to toggle OFFLINE."""

    def use(offline: bool = False):
        monkeypatch.setattr(store, "settings", config.Settings(data_dir=tmp_path / "data", offline=offline))

    monkeypatch.setattr(store, "SNAPSHOT_DIR", tmp_path / "snapshot")
    use(False)
    return use
