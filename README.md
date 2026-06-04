# MyVault – Chat & Memories Vault for Snapchat Export (Docker)

MyVault makes your **Snapchat “My Data” export** searchable locally and provides a web UI for chats, media/snaps, statistics/insights.

> Disclaimer: This project is **not affiliated with, endorsed by, or connected to** Snapchat or Snap Inc.  
> "Snapchat" is a trademark of Snap Inc. and is used here **only to describe compatibility** with exported data.
> "Immich" is used in this programm. The immich repo can be viewed here: `https://github.com/immich-app/immich`

## The problem

Snapchat offers very limited ways to meaningfully use your own data:

- **No search** – You can’t search chats or snap history by text/people; you have to scroll manually.
- **Memories are hard to browse** – Memories are a big list without grouping by person/context; finding specific photos/videos is tedious.
- **Chat media is poorly organized** – Images/videos from chats are not easily sortable by chat/date/person.
- **Storage** – Snapchat recently announced a storage limit for non premium users

The official “My Data” export gives you raw files, but no good interface to explore them.

## What MyVault does

MyVault turns your Snapchat export into a **searchable local vault** and provides these areas:

- **Dashboard** – Overview (chat/message/media/snap/memory counts), quick links, and **data management** (unpack ZIPs, run import).
- **Chats** – Chat list with message counts; open a chat view with **in-chat search** (highlight + jump). Also includes **global search** across all chats.
- **Chat media** – Gallery of all chat images/videos with filters (date, type, chat).
- **Insights** – Charts/statistics for chats & snaps plus additional analyses from the export (e.g. engagement, time spent, categories, ranking, account/device/login).
- **Immich** – Sync Memories + chat media into Immich, organized into albums (see below).

### Screenshots

| Dashboard | Chats | Chat |
|-----------|-------|------|
| ![Dashboard](images/dashboard.png) | ![Chat list](images/chats.png) | ![Chat view](images/chat.png) |

| Chat media | Insights |
|------------|----------|
| ![Chat media gallery](images/media.png) | ![Insights / Stats](images/insights.png) |

## Requirements

- **Docker**
- Optional for Immich GPU (CPU works fine as well, only ML from Immich is slower): NVIDIA driver + Container Toolkit

## Quickstart (Windows)

### Option A: Clone the repo (includes start scripts)

```bash
git clone https://github.com/leofleischmann/chats-and-memories-vault-for-snapchat-export.git
cd chats-and-memories-vault-for-snapchat-export
```

### 2) Start the app (via scripts)

- **Without Immich:** `scripts/start-app.bat`
- **With Immich (CPU):** `scripts/start-immich-cpu.bat`
- **With Immich (GPU/NVIDIA):** `scripts/start-immich-gpu.bat`
- **Stop everything:** `scripts/stop-all.bat`

By default, Docker Compose pulls **prebuilt images** from GitHub Container Registry (GHCR), so users don't have to build locally.
For development from a repo clone, append `dev` (e.g. `scripts/start-app.bat dev`) to build backend/frontend from source.

### Option B: Without the repo (only `docker-compose.yml` + `.env`)

You can also run MyVault without cloning the repo. You only need:

- `docker-compose.yml`
- `.env` (recommended)
- the local data folders (persistent storage):
  - `input/` (unpacked export / raw_export)
  - `input_zip/` (optional, if you import ZIPs)
  - `data/` (SQLite + app data)
  - `logs/` (optional, only if `LOG_TO_FILES=1`)
  - `immich-data/` (only if you run Immich via Compose)

Start:

```bash
# without Immich
docker compose up -d

# with Immich (CPU)
docker compose --profile immich up -d

# with Immich (GPU)
docker compose --profile immich-gpu up -d
```

Optionally pin image versions in `.env`:

```bash
BACKEND_TAG=1.0.2
FRONTEND_TAG=1.0.2
```

### 3) Open in your browser

- App: `http://localhost:5173`

## Import data (via Dashboard)

1. **Get your Snapchat export**  
   In the Snapchat app, request your “My Data” export, or use the web link: [Download My Data (Snapchat)](https://accounts.snapchat.com/v2/download-my-data). You’ll receive one or multiple ZIP files.

   ![Snapchat – Export request](images/export-all.png)

2. **Put ZIPs into the folder**  
   Copy all downloaded ZIP files into **`input_zip/`** in this project.

   ![Put ZIP-Files in /input_zip](images/export-in-folder.png)

3. **Run import**  
   Open `http://localhost:5173` → **Dashboard** → **Data management**, then:

   - **Unpack + import ** – unpacks ZIPs into `input/` (chat_media, memories, JSON, etc.) and starts the import process.

     ![Dashboard – Data management](<images/dashboard import 1.png>)

   - **Immich (optional)** – if Immich is running: go to **Immich** → click **Start sync**.

     ![Dashboard – Immich sync](<images/dashboard import 2.png>)  
     ![Immich integration](<images/dashboard import 3.png>)
     Everything from immich account setup to moving your files into immich will be handled automatically.
     You can choose if you want to move the images with or without the Snapchat overlay to immich. Note: This can only be chosen at the first sync.



## Importing newer exports later

When you request a new “My Data” export, Snapchat **typically** includes your previous data plus new data. (This is common behavior, but not a strict guarantee.)

Recommended workflow months later:

1. Put the new ZIP(s) into `input_zip/` (delete old ZIPs).
2. Dashboard → **Unpack + import**
3. Immich → **Start sync**
   - The sync can skip already-uploaded files locally without re-checking every file on the Immich server.
   - Immich also detects duplicates and won’t upload assets twice.
   - This helps preserve Immich data like face/person assignments as long as you **do not reset Immich**.
   - If a medium is assigned to a chat in a newer export, the next sync can additionally place it into the matching chat album.

## Immich organization (if you use sync)

- Album **“Snapchat Memories”** – all Memories main files (overlays are skipped when not checked in first sync process). When uploading, MyVault sets **timestamp + GPS coordinates** (if available) from `json/memories_history.json` as metadata in Immich.
- Album **“Snapchat Shared Story”** – content from `shared_story/` (including date/type from `json/shared_story.json`).
- Album **“Chat: <Chat title>”** – media for that chat.
- Album **“Chat media (unassigned)”** – media without a linked message.

### Existing Immich library (advanced)

If Immich already runs **somewhere else** (NAS, home server, or on the host next to Docker) and you want Snapchat exports in **that** library together with your other media:

1. In Immich, create an **API key** (Account → API Keys) for the account that should own the uploads.
2. In MyVault, open **Immich** and expand **Advanced: custom Immich instance**.
3. Enable **Use external Immich**, set the **Immich base URL** (scheme + host + port only, e.g. `https://photos.example.com` or, when Immich runs on the same PC as Docker Desktop, often `http://host.docker.internal:2283`). The backend container must reach this URL (firewall, HTTPS, DNS).
4. Paste the **API key**, optionally **Test connection**, then **Save**.
5. Run **Start sync** — same behaviour as with the bundled stack (albums, duplicate detection, overlay choice on first sync).

Notes:

- You **do not** need to start the optional bundled Immich Compose profile only to upload to an external server; only MyVault’s backend must reach your Immich URL.
- Turning external mode **off** and saving targets the **bundled** Immich URL again (`IMMICH_URL` / default `http://immich-server:2283` inside Compose). Existing bundled API keys in `immich_config.json` remain unless you wipe them via admin reset.
