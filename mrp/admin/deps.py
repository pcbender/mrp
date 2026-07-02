from __future__ import annotations

import os
from pathlib import Path


def get_repo_root() -> Path:
    return Path(os.environ.get("MRP_REPO", ".")).resolve()
