from __future__ import annotations

from typing import Any, Optional

import httpx


class MeiliClient:
    def __init__(self, url: str, api_key: str, index: str):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.index = index

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def ensure_index(self) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{self.url}/indexes/{self.index}", headers=self._headers())
            if r.status_code == 404:
                r2 = await client.post(
                    f"{self.url}/indexes",
                    headers=self._headers(),
                    json={"uid": self.index, "primaryKey": "message_id"},
                )
                r2.raise_for_status()
            elif r.status_code >= 400:
                r.raise_for_status()

            settings = {
                "searchableAttributes": ["text", "sender", "chat_title"],
                "filterableAttributes": ["chat_id", "sender", "type", "ts_utc"],
                "sortableAttributes": ["ts_utc", "ordinal_in_chat"],
            }
            rs = await client.patch(
                f"{self.url}/indexes/{self.index}/settings",
                headers=self._headers(),
                json=settings,
            )
            rs.raise_for_status()

    async def add_documents(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{self.url}/indexes/{self.index}/documents",
                headers=self._headers(),
                json=docs,
            )
            r.raise_for_status()

    async def search(
        self,
        q: str,
        chat_id: Optional[str],
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "q": q,
            "limit": limit,
            "offset": offset,
            "attributesToHighlight": ["text"],
            "highlightPreTag": "<mark>",
            "highlightPostTag": "</mark>",
            "attributesToCrop": ["text"],
            "cropLength": 80,
        }
        if chat_id:
            payload["filter"] = f"chat_id = '{chat_id}'"
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self.url}/indexes/{self.index}/search",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            return r.json()

