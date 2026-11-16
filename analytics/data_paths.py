"""Locations of the data stores used by the analytics readers."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def repository_path(value):
    """Resolve relative paths from the checkout and preserve absolute paths."""
    return REPO_ROOT / Path(value).expanduser()


DATA_DIR = repository_path(os.environ.get("AGENT_DATA_DIR", "__data1"))
METRICS_PATH = repository_path(os.environ.get("AGENT_METRICS_PATH", DATA_DIR / "metrics.sqlite3"))
