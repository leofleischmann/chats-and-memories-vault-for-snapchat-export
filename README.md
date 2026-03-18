# SnapChats – Snapchat Chat Search (Docker)

## Das Problem

Snapchat bietet kaum Möglichkeiten, die eigenen Daten sinnvoll zu nutzen:

- **Keine Suche** – In Chats und dem Snap-Verlauf kann man nicht nach Text oder Personen suchen; alles muss manuell durchscrollt werden.
- **Memories unübersichtlich** – Memories liegen in einer großen Liste ohne Gruppierung nach Person oder Kontext; Fotos/Videos von bestimmten Freunden wiederzufinden ist mühsam.
- **Chat-Medien schlecht gruppiert** – Bilder und Videos aus Chats sind nicht klar nach Chat, Datum oder Person sortierbar und schwer auffindbar.

Mit dem offiziellen Datenexport (My Data) hat man zwar die Rohdaten, aber keine passende Oberfläche dafür.

## Was SnapChats löst

SnapChats macht deinen Snapchat-Export **durchsuchbar** (Tippfehler-/Ähnlichkeitssuche via Meilisearch) und bietet eine lokale Web-UI mit folgenden Bereichen:

- **Dashboard** – Übersicht (Anzahl Chats, Nachrichten, Medien, Snaps, Memories), Links zu allen Bereichen sowie **Datenverwaltung**: ZIPs entpacken, Import starten.
- **Chats** – Chat-Liste mit Nachrichtenanzahl; Klick öffnet einen Chat mit Sortierung nach Nachrichten und **Suche im Chat** (Highlight, Sprung zur Stelle). **Globale Suche** über alle Chats (ebenfalls mit Highlight und Sprung).
- **Chat-Medien** – Galerie aller Bilder/Videos aus Chats, filterbar nach Datum, Typ, Chat und Zuweisung (zugeordnet/nicht zugeordnet).
- **Insights** – Charts/Statistiken zu Chats & Snaps **plus** zusätzliche Auswertungen aus dem Snapchat-Export (z. B. Engagement, Time Spent, Kategorien, Ranking, Account/Device/Login – alles lokal).
- **Immich (optional)** – Sync von Memories und Chat-Medien in die Foto-App Immich; Alben nach Kontext (siehe unten).

## Voraussetzungen

- **Docker Desktop**
- Optional für Immich GPU: NVIDIA-Treiber + Container Toolkit

## Quickstart (Windows)

### 1) Repo klonen und `.env` anlegen


### 2) App starten

- **Ohne Immich:** `start-app.bat`
- **Mit Immich (CPU):** `start-immich-cpu.bat`
- **Mit Immich (GPU/NVIDIA):** `start-immich-gpu.bat`
- **Alles stoppen:** `stop-all.bat`

### 3) Web öffnen

- App: `http://localhost:5173`
- Backend-API (Swagger): `http://localhost:8000/docs`
- Immich (wenn gestartet): `http://localhost:2283`

## Daten importieren (über das Dashboard)

1. **Snapchat-Export besorgen**  
   In der Snapchat-App alles exportieren und herunterladen („Daten exportieren“ / My Data). Du erhältst eine oder mehrere ZIP-Dateien.

2. **ZIPs in den Ordner legen**  
   Alle heruntergeladenen ZIP-Dateien in den Ordner **`input zip/`** in diesem Projekt kopieren. Der Ordner ist im Repo vorhanden (leer); nur die ZIP-Inhalte werden von Git ignoriert.

3. **Import starten**  
   `http://localhost:5173` öffnen → **Dashboard** → **Datenverwaltung**, dann nacheinander:

   - **ZIP → input entpacken** – entpackt die ZIPs nach `input/` (Chat_media, memories, JSON etc.). Erst fortfahren, wenn alle Dateien nach `input/` kopiert wurden.

     ![Dashboard – Datenverwaltung](images/dashboard-import-1.png)

   - **Import starten** – verarbeitet die Daten und macht sie durchsuchbar.

     ![Dashboard – Import](images/dashboard-import-2.png)

   - **Immich (optional)** – Wenn Immich gestartet wurde: **Immich Integration** → **Sync starten** klicken.

     ![Dashboard – Immich Sync](images/dashboard-import-3.png)  
     ![Immich Integration](images/dashboard-import-4.png)

## Neue Snapchat-Exporte nachträglich einspielen (inkrementeller Workflow)

Snapchat liefert bei einem neuen „My Data“-Export **typischerweise** wieder die bisherigen Daten **plus** neue Daten. (Das Verhalten ist praktisch so, aber Snapchat dokumentiert das nicht als harte Garantie.)

Wenn du Monate später erneut exportierst, ist der empfohlene Ablauf:

1. **Neue ZIP(s) in `input zip/` legen** (alte ZIPs kannst du dabei überschreiben/ersetzen).
2. **Dashboard → ZIP → input entpacken** (entpackt nach `input/`).
3. **Dashboard → Import starten**
   - Ein **Reset der App-Datenbank** ist unkritisch (Import ist schnell).
4. **Immich Integration → Sync starten**
   - Immich erkennt bereits vorhandene Assets als **Duplikate** und lädt sie nicht doppelt hoch.
   - Wichtig: Dadurch bleiben in Immich Dinge wie **Personen-/Gesichtszuordnung** erhalten, solange du **Immich nicht zurücksetzt**.
   - Wenn ein Medium in einem neuen Export später (besser) einem Chat zugeordnet ist, kann es beim erneuten Sync zusätzlich in das passende **Chat-Album** einsortiert werden.

## Immich-Organisation (wenn Sync genutzt wird)

- Album **„Snapchat Memories“** – alle Memories (Hauptdateien; Overlays werden übersprungen). Beim Upload setzt SnapChats **Zeitstempel + GPS-Koordinaten** (wenn verfügbar) aus `json/memories_history.json` als Metadaten in Immich.
- Album **„Snapchat Shared Story“** – Inhalte aus `shared_story/` (inkl. Datum/Typ aus `json/shared_story.json`).
- Album **„Chat: &lt;Chat-Titel&gt;“** – Medien aus dem jeweiligen Chat.
- Album **„Chat-Medien (ohne Zuordnung)“** – Medien ohne verknüpfte Nachricht.

## Was nicht ins Repo gehört

- `.env` (Secrets/Keys) → Vorlage: `.env.example`
- `data/`, `input/`, **Inhalte** von `input zip/` (ZIP-Dateien), `immich-data/` (große/private Daten)
- `frontend/node_modules/`, `frontend/dist/`

Der Ordner **`input zip/`** ist im Repo nur als leerer Ordner enthalten; die darin abgelegten ZIPs werden von Git ignoriert. Die übrigen genannten Pfade stehen in der `.gitignore`.
