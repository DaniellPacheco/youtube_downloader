from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    min_free_bytes: int = 512 * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.base_dir / "app.db"

    @property
    def sources_dir(self) -> Path:
        return self.base_dir / "sources"

    @property
    def results_dir(self) -> Path:
        return self.base_dir / "results"

    @property
    def temp_dir(self) -> Path:
        return self.base_dir / "temp"

    def ensure_dirs(self) -> None:
        for path in (self.base_dir, self.sources_dir, self.results_dir, self.temp_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    root = Path(os.getenv("YTD_APP_DATA_DIR", Path.cwd() / "data")).resolve()
    minimum = int(os.getenv("YTD_MIN_FREE_BYTES", str(512 * 1024 * 1024)))
    return Settings(root, minimum)

