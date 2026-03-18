# MyVault – Chat & Memories Vault for Snapchat Export (Docker)

MyVault makes your **Snapchat “My Data” export** searchable locally (typo-tolerant / similarity search via Meilisearch) and provides a web UI for chats, media, statistics/insights, and optional Immich sync.

Repo name: `chats-and-memories-vault-for-snapchat-export`

> Disclaimer: This project is **not affiliated with, endorsed by, or connected to** Snapchat or Snap Inc.  
> “Snapchat” is a trademark of Snap Inc. and is used here **only to describe compatibility** with exported data.

## The problem

Snapchat offers very limited ways to meaningfully use your own data:

- **No search** – You can’t search chats or snap history by text/people; you have to scroll manually.
- **Memories are hard to browse** – Memories are a big list without grouping by person/context; finding specific photos/videos is tedious.
- **Chat media is poorly organized** – Images/videos from chats are not easily sortable by chat/date/person.

The official “My Data” export gives you raw files, but no good interface to explore them.

## What MyVault does

MyVault turns your Snapchat export into a **searchable local vault** and provides these areas:

- **Dashboard** – Overview (chat/message/media/snap/memory counts), quick links, and **data management** (unpack ZIPs, run import).
- **Chats** – Chat list with message counts; open a chat view with **in-chat search** (highlight + jump). Also includes **global search** across all chats.
- **Chat media** – Gallery of all chat images/videos with filters (date, type, chat, assigned/unassigned).
- **Insights** – Charts/statistics for chats & snaps plus additional analyses from the export (e.g. engagement, time spent, categories, ranking, account/device/login; stored locally).
- **Immich (optional)** – Sync Memories + chat media into Immich, organized into albums (see below).

## Requirements

- **Docker Desktop**
- Optional for Immich GPU: NVIDIA driver + Container Toolkit

## Quickstart (Windows)

### 1) Clone repo and create `.env`

Copy `.env.example` to `.env` and adjust values if needed.

### 2) Start the app

- **Without Immich:** `start-app.bat`
- **With Immich (CPU):** `start-immich-cpu.bat`
- **With Immich (GPU/NVIDIA):** `start-immich-gpu.bat`
- **Stop everything:** `stop-all.bat`

### 3) Open in your browser

- App: `http://localhost:5173`
- Backend API (Swagger): `http://localhost:8000/docs`
- Immich (if started): `http://localhost:2283`

## Import data (via Dashboard)

1. **Get your Snapchat export**  
   In the Snapchat app, request/download your “My Data” export. You’ll receive one or multiple ZIP files.

2. **Put ZIPs into the folder**  
   Copy all downloaded ZIP files into **`input zip/`** in this project. The folder exists in the repo (empty); the ZIP contents are ignored by Git.

3. **Run import**  
   Open `http://localhost:5173` → **Dashboard** → **Data management**, then:

   - **Unpack ZIP → input** – unpacks ZIPs into `input/` (chat_media, memories, JSON, etc.). Continue only once all files are present in `input/`.

     ![Dashboard – Data management](<images/dashboard import 1.png>)

   - **Start import** – processes the data and makes it searchable.

     ![Dashboard – Import](<images/dashboard import 2.png>)

   - **Immich (optional)** – if Immich is running: go to **Immich** → click **Start sync**.

     ![Dashboard – Immich sync](<images/dashboard import 3.png>)  
     ![Immich integration](<images/dashboard import 4.png>)

## Importing newer exports later (incremental workflow)

When you request a new “My Data” export, Snapchat **typically** includes your previous data plus new data. (This is common behavior, but not a strict guarantee.)

Recommended workflow months later:

1. Put the new ZIP(s) into `input zip/` (you can replace/overwrite older ZIPs).
2. Dashboard → **Unpack ZIP → input**
3. Dashboard → **Start import**
   - Resetting the app database is usually fine (import is fast).
4. Immich → **Start sync**
   - Immich detects duplicates and won’t upload assets twice.
   - This helps preserve Immich data like face/person assignments as long as you **do not reset Immich**.
   - If a medium is assigned to a chat in a newer export, the next sync can additionally place it into the matching chat album.

## Immich organization (if you use sync)

- Album **“Snapchat Memories”** – all Memories main files (overlays are skipped). When uploading, MyVault sets **timestamp + GPS coordinates** (if available) from `json/memories_history.json` as metadata in Immich.
- Album **“Snapchat Shared Story”** – content from `shared_story/` (including date/type from `json/shared_story.json`).
- Album **“Chat: <Chat title>”** – media for that chat.
- Album **“Chat media (unassigned)”** – media without a linked message.

## What should NOT be committed

- `.env` (secrets/keys) → use `.env.example`
- `data/`, `input/`, the **contents** of `input zip/` (ZIP files), `immich-data/` (large/private data)
- `frontend/node_modules/`, `frontend/dist/`

The folder **`input zip/`** is tracked only as an empty folder placeholder (`.gitkeep`). ZIP files placed inside are ignored by Git; the remaining paths are listed in `.gitignore`.
