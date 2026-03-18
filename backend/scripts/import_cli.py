from __future__ import annotations

import argparse
import asyncio
import os

from app.config import settings
from app.importer import extract_chat_refs, iter_messages_for_chat, write_normalized
from app.meili import MeiliClient
from app.storage import Storage


async def run() -> None:
    export_root = settings.export_root
    chat_history_path = os.path.join(export_root, "html", "chat_history.html")
    chats = extract_chat_refs(chat_history_path)

    out_dir = os.path.join(settings.data_dir, "normalized")
    chats_path, messages_path = write_normalized(export_root=export_root, out_dir=out_dir, chats=chats)
    print(f"Wrote {chats_path}")
    print(f"Wrote {messages_path}")

    store = Storage(settings.sqlite_path)
    store.init()

    # Upsert chat stats from chats.json (already sorted).
    import json

    with open(chats_path, "r", encoding="utf-8") as f:
        chat_rows = json.load(f)
    for row in chat_rows:
        store.upsert_chat_stats(
            chat_id=row["chat_id"],
            title=row["title"],
            source_subpage=row["source_subpage"],
            text_message_count=row["text_message_count"],
            message_count=row["message_count"],
            first_ts=row.get("first_ts"),
            last_ts=row.get("last_ts"),
        )

    meili = MeiliClient(settings.meili_url, settings.meili_api_key, settings.meili_index)
    await meili.ensure_index()

    batch: list[dict] = []
    batch_size = 2000
    for chat in chats:
        chunk = []
        for m in iter_messages_for_chat(export_root=export_root, chat=chat):
            chunk.append(m)
            batch.append(m.__dict__)
            if len(chunk) >= 2000:
                store.insert_messages(chunk)
                chunk = []
            if len(batch) >= batch_size:
                await meili.add_documents(batch)
                batch = []
        if chunk:
            store.insert_messages(chunk)

    if batch:
        await meili.add_documents(batch)

    print(f"Imported {len(chats)} chats into SQLite + Meilisearch.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    asyncio.run(run())


if __name__ == "__main__":
    main()

