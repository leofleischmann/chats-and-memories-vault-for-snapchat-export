from __future__ import annotations

import os

from pydantic import BaseModel


class Settings(BaseModel):
    export_root: str = os.getenv("EXPORT_ROOT", "/data/raw_export")
    data_dir: str = os.getenv("DATA_DIR", "/data")
    sqlite_path: str = os.getenv("SQLITE_PATH", "/data/app.sqlite")

    meili_url: str = os.getenv("MEILI_URL", "http://meilisearch:7700")
    meili_api_key: str = os.getenv("MEILI_API_KEY", "masterKey")
    meili_index: str = os.getenv("MEILI_INDEX", "messages")

    immich_url: str = os.getenv("IMMICH_URL", "http://immich-server:2283")
    immich_admin_email: str = os.getenv("IMMICH_ADMIN_EMAIL", "admin@snapchats.local")
    immich_admin_password: str = os.getenv("IMMICH_ADMIN_PASSWORD", "snapchats-admin-2026")

    @property
    def immich_cache_sqlite_path(self) -> str:
        """Separate SQLite file for Immich upload cache; survives reset-app."""
        return os.getenv(
            "IMMICH_CACHE_SQLITE_PATH",
            os.path.join(os.path.dirname(self.sqlite_path) or ".", "immich_upload_cache.sqlite"),
        )


settings = Settings()

