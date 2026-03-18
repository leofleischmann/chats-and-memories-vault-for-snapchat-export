"""Immich API client for upload and album operations."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

DEVICE_ID = "snapchat-export"
TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".heif": "image/heif", ".heic": "image/heic",
        ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }.get(ext, "application/octet-stream")


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self.api_key},
            timeout=TIMEOUT,
        )

    def check_connection(self) -> bool:
        try:
            r = self.client.get("/api/server/ping")
            return r.status_code == 200
        except Exception:
            return False

    def upload_asset(
        self,
        file_path: str,
        device_asset_id: str,
        created_at: str | None = None,
    ) -> dict | None:
        """
        Upload a single file.

        Returns:
          - Immich asset dict (uploaded or duplicate)
          - or an error dict: {"status": "error", "error_type": "...", "message": "..."}
        """
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()

        fname = os.path.basename(file_path)
        mime = _guess_mime(fname)

        with open(file_path, "rb") as f:
            r = self.client.post(
                "/api/assets",
                data={
                    "deviceAssetId": device_asset_id,
                    "deviceId": DEVICE_ID,
                    "fileCreatedAt": created_at,
                    "fileModifiedAt": created_at,
                },
                files={"assetData": (fname, f, mime)},
            )

        if r.status_code == 201:
            return r.json()
        if r.status_code == 200:
            body = r.json()
            if body.get("status") == "duplicate":
                return body
            return body
        try:
            body = r.json()
            message = str(body.get("message") or body.get("error") or r.text)[:300]
        except Exception:
            message = str(r.text)[:300]

        error_type = "upload-error"
        if "Unsupported file type" in message or "unsupported file type" in message:
            error_type = "unsupported-mime"

        logger.warning("Upload failed %s: %s %s", fname, r.status_code, message[:200])
        return {"status": "error", "error_type": error_type, "message": message}

    def update_asset_metadata(
        self,
        asset_id: str,
        description: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        date_time_original: str | None = None,
    ) -> bool:
        body: dict = {}
        if description is not None:
            body["description"] = description
        if latitude is not None:
            body["latitude"] = latitude
        if longitude is not None:
            body["longitude"] = longitude
        if date_time_original is not None:
            body["dateTimeOriginal"] = date_time_original
        if not body:
            return True

        r = self.client.put(f"/api/assets/{asset_id}", json=body)
        if r.status_code == 200:
            return True
        if r.status_code == 404:
            logger.debug(
                "Asset not found, skipping metadata update (id=%s); may be race or asset removed.",
                asset_id,
            )
            return False
        logger.warning("Update metadata failed %s: %s", asset_id, r.text[:200])
        return False

    def get_or_create_album(self, name: str) -> str:
        """Returns album ID, creating it if it doesn't exist."""
        r = self.client.get("/api/albums")
        if r.status_code == 200:
            for album in r.json():
                if album.get("albumName") == name:
                    return album["id"]

        r = self.client.post("/api/albums", json={"albumName": name})
        if r.status_code == 201:
            return r.json()["id"]
        raise RuntimeError(f"Failed to create album '{name}': {r.status_code} {r.text[:200]}")

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        for i in range(0, len(asset_ids), 100):
            batch = asset_ids[i : i + 100]
            r = self.client.put(
                f"/api/albums/{album_id}/assets",
                json={"ids": batch},
            )
            if r.status_code != 200:
                logger.warning(
                    "add_assets_to_album failed: album_id=%s batch_size=%d status=%d %s",
                    album_id, len(batch), r.status_code, r.text[:200],
                )
                continue
            try:
                body = r.json()
                if isinstance(body, dict) and body.get("success") is False:
                    err = body.get("error", body)
                    logger.warning(
                        "add_assets_to_album partial failure: album_id=%s %s (often due to rejected uploads, e.g. HEIC without pillow-heif)",
                        album_id, str(err)[:200],
                    )
            except Exception:
                pass

    def close(self):
        self.client.close()
