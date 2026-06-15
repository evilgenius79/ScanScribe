# ScanScribe
An open source AI powered transcription system designed for public safety radio scanning. Uses whisper AI to transcribe raw radio recordings then stores and catagorizes them in an advanced searchable database. Easy to use web UI. Has the ability to create detailed incident threads with local ollama hosted LLM's. Docker ready deployment for easy setup.

## Changes in This Fork

This fork hardens the upstream project with a pass of security, reliability, and
correctness fixes. Highlights versus the original:

### Security
- **SECRET_KEY is now enforced** — the app refuses to start with a missing,
  known-default, or too-short signing key (override for local dev with
  `ALLOW_INSECURE_SECRET_KEY=1`). `docker-compose` no longer ships an insecure default.
- **Upload path-traversal fixed** — client filenames are sanitized to a basename,
  so an upload can no longer escape the queue directory.
- **Uploads are streamed to disk** in chunks with a size cap (`MAX_UPLOAD_MB`,
  default 500) instead of being buffered whole in memory (DoS hardening).
- **Stored XSS fixed** in the Insights and Logs UIs — transcripts, talkgroups,
  filenames and paths are HTML-escaped, and LLM-generated summaries are sanitized
  with DOMPurify before rendering.
- **Config endpoints are admin-only** — reading/writing `config.yml` and
  restarting now require an admin, and saved configs are validated against the
  schema before they're persisted.
- **Registration hardened** — atomic first-admin creation, optional lockdown of
  public sign-up (`DISABLE_OPEN_REGISTRATION`), and a bcrypt 72-byte password guard.
- **Configurable CORS** via `CORS_ALLOW_ORIGINS` (was hard-coded `*`).

### Reliability & concurrency
- **SQLite WAL + busy timeout** on all three databases — eliminates most
  "database is locked" errors under concurrent workers.
- **Event pipeline locking** — background header/summary writes now take the
  per-event work lock, so they can't clobber foreground attach/close updates.
- **File watcher** now guards its in-flight set with a lock and waits for file
  size to stabilize before queuing — no more duplicate or truncated transcriptions.
- **NER inference is serialized** (HuggingFace pipelines aren't thread-safe).
- **WebSocket** only replays log messages to new clients (not stale
  transcriptions/stats) and deregisters sockets on any error.
- **Auto-summaries** use a consistent local-time basis, skip the LLM call when a
  summary already exists, and no longer block the event loop (`asyncio.to_thread`).
- **Startup DB migrations** are logged and error-handled, and warn before the
  destructive `span_store` rebuild instead of doing it silently.

### Correctness
- **Whisper** uses the supported `language`/`task` generate arguments instead of
  the deprecated `forced_decoder_ids`.
- **Transcription confidence** is computed from real token probabilities instead
  of a fabricated constant.
- Event models are registered in `models/__init__` so table metadata is complete.

## Screenshots
### ScanScribe Dashboard
<img src="screenshots/Screenshot_1.png" alt="ScanScribe Dashboard">

### Search and advanced filtering
<img src="screenshots/Screenshot_2.png" alt="Search Engine for Transcriptions">

### Insights Dashboard
<img src="screenshots/Screenshot_3.png" alt="Advanced Insights">

## Features

- **Whisper transcription** — multi-worker, VAD-filtered, CPU or GPU
- **Real-time Web UI** — WebSocket live updates, modern dark web interface
- **Search and Playback** - Search for specific words in the database. Playback any transcriptions.
- **Insights** — Daily activity statistics with interactable graph. Counts how many transcriptions per hour and logs talkgroups.
- **Multi-user auth** — JWT-based login, user management
- **Ollama LLM integration** — local model routing, header normalization, and event summaries (no cloud required)
- **Events pipeline** — NER → Worker LLM (opens incidents) → Master LLM (attach/skip/close) → header normalizer → summary
- **Incident management** — open/close/reopen events, paginated archive, pipeline activity log, auto-close stale events by incident time

## Prerequisites

- Docker & Docker Compose
- Ollama (local or remote) with your chosen models loaded
- NER model (`models/incident_ner_*`) — custom public-safety NER
- Whisper model (`models/whisper-*`)
- 8 GB+ RAM recommended; 16+ GB if running Ollama on the same host

## Windows First-Time Docker Setup (Simple Guide)

If this is your first time using Docker, follow these exact steps.

### Step 1: Install Docker Desktop
1. Go to [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
2. Download **Docker Desktop for Windows**
3. Run the installer and keep default options
4. Restart your PC if Docker asks
5. Open Docker Desktop and wait until it says Docker is running

### Step 2: Download ScanScribe
Open **PowerShell** and run:

```powershell
git clone https://github.com/xxbubziexx/scanscribe.git
cd scanscribe
```

If you do not have Git installed, install **Git for Windows** first:
[https://git-scm.com/download/win](https://git-scm.com/download/win)

### Step 3: Create your environment file
In PowerShell (inside the `scanscribe` folder):

```powershell
copy .env.example .env
```

Then open `.env` in Notepad and set a strong `SECRET_KEY`.

Quick way to generate one:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

### Step 4: Check `config.yml`
Open `config.yml` and confirm:
- `model.name` matches your Whisper model folder in `./models`
- `events_pipeline.enabled` is true/false as you want
- `incidents_ollama.enabled` and `base_url` are correct if using Ollama

### Step 5: CPU or GPU (same mode for all of these)
Pick **one** path—do not mix files from the CPU and GPU examples.

**CPU (typical):**

```powershell
copy docker-compose.cpu.example docker-compose.yml
copy requirements.cpu.example requirements.txt
```

In `config.yml`, set **`model.device: cpu`**.

**GPU (NVIDIA GPU + [Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)):**

```powershell
copy docker-compose.gpu.example docker-compose.yml
copy requirements.gpu.example requirements.txt
```

In `config.yml`, set **`model.device: cuda`**.

**To switch later:** `docker compose down` → copy the *other* pair of examples over `docker-compose.yml` and `requirements.txt` → set **`model.device`** → `docker compose up -d --build`.

### Step 6: Start ScanScribe
From the project folder:

```powershell
docker-compose up -d --build
```

First build can take a while. This is normal.

### Step 7: Open the app
Go to:

`http://localhost:8000`

Register your first account.

### Step 8: Basic commands you will use later
```powershell
# See running logs
docker-compose logs -f

# Stop ScanScribe
docker-compose down

# Start again later
docker-compose up -d
```

### Notes
- You do **not** need to install FFmpeg manually when using Docker. It is already included in the container.
- Your databases and files stay in local folders (`./data`, `./logs`, `./audio_storage`) between restarts.

## Quick Start

### 1. Clone & configure environment

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY (required)
openssl rand -hex 32   # generate a key
```

### 2. Configure `config.yml`
**Events pipeline is DISABLED by default.**

It's recommened to use whisper-small fined tuned on public safety audio. There is no official release for a finetuned model as of now. Just use the base whisper-small model available here on [Huggingface.](https://huggingface.co/openai/whisper-small)

Key sections to set before first run:
```yaml
model:
  name: <your-whisper-model-dir>   # folder name inside ./models/
  workers: 4                        # parallel transcription threads

events_pipeline:
  enabled: false
  ner_model_path: ./models/incident_ner_<version>
  llm_routing: true
  auto_close_stale_seconds: 3600    # close events idle > 1 hour
  cleanup_interval_seconds: 300     # sweep every 5 min

incidents_ollama:
  enabled: false
  base_url: "http://<ollama-host>:11434"
  worker_model: "gemma4:latest"     # cheap triage model
  master_model: "qwen3.5"           # routing + header + summary
```

### 3. CPU or GPU

Copy the matching pair to the working names, then set **`model.device`** in **`config.yml`** (`cpu` or `cuda`):

```bash
# CPU
cp docker-compose.cpu.example docker-compose.yml
cp requirements.cpu.example requirements.txt

# or GPU
# cp docker-compose.gpu.example docker-compose.yml
# cp requirements.gpu.example requirements.txt
# → model.device: cuda  (needs NVIDIA + Container Toolkit)
```

**To switch later:** `docker compose down` → use the *other* pair of examples → update **`model.device`** → `docker compose up -d --build`.

### 4. Build & run

```bash
docker-compose up -d
```

Open `http://<host>:8000` — register your first account.

## Raspberry Pi 5 Setup

ScanScribe runs on a Raspberry Pi 5 (ARM64, CPU-only). There is no NVIDIA GPU, so
always use the **CPU** path. Transcription is slower than on a desktop but works
well for short scanner clips. An **8 GB or 16 GB** Pi 5 is strongly recommended.

### 1. OS and Docker
1. Flash **64-bit Raspberry Pi OS (Bookworm)** or **Ubuntu Server 24.04 (arm64)** —
   a 64-bit OS is required (the 32-bit OS cannot run the PyTorch wheels).
2. Install Docker + Compose:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out/in afterwards
   sudo apt-get install -y docker-compose-plugin
   ```

### 2. Get ScanScribe and pick the CPU files
```bash
git clone https://github.com/evilgenius79/scanscribe.git
cd scanscribe
cp .env.example .env
cp docker-compose.cpu.example docker-compose.yml
cp requirements.cpu.example requirements.txt
```
- Edit `.env` and set a strong `SECRET_KEY` (`openssl rand -hex 32`) — the app
  will refuse to start without one.
- The CPU `Dockerfile` is ARM64-aware: on the Pi it keeps the PyPI CPU wheels for
  `torch`/`torchaudio` (the x86 PyTorch CPU index has no aarch64 build), so no
  manual changes are needed.

### 3. Tune `config.yml` for the Pi
```yaml
model:
  name: whisper-small        # or whisper-base for more speed on the Pi
  device: cpu                # REQUIRED — the Pi has no CUDA GPU
  workers: 2                 # Pi 5 has 4 cores; 2 leaves headroom
```
Then in `.env`, match the PyTorch thread limits to the core count:
```
OMP_NUM_THREADS=4
MKL_NUM_THREADS=4
TORCH_NUM_THREADS=4
```

> **Ollama events pipeline:** running Ollama *on the Pi itself* is heavy and slow.
> Either leave `events_pipeline.enabled: false` / `incidents_ollama.enabled: false`,
> or point `incidents_ollama.base_url` at Ollama running on another machine on your LAN.

### 4. Build and run
```bash
docker compose up -d --build
```
The first build downloads PyTorch and compiles a few wheels — on a Pi 5 this can
take **15–40 minutes** and needs swap. If the build is killed for memory, raise swap:
```bash
sudo dphys-swapfile swapoff
sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup && sudo dphys-swapfile swapon
```
Open `http://<pi-ip>:8000` and register your first account.

### Faster builds
The first build is dominated by downloading the PyTorch wheel (~200 MB+) — there's
no way around that on a cold build. But you can make everything *after* it fast:

- **Re-builds are cached.** The CPU `Dockerfile` uses a BuildKit pip cache mount,
  so once the wheels are downloaded, later `--build` runs reuse them and finish in
  seconds. BuildKit is on by default in modern Docker; if yours is older, prefix
  with `DOCKER_BUILDKIT=1`:
  ```bash
  DOCKER_BUILDKIT=1 docker compose up -d --build
  ```
- **Skip the Pi's CPU entirely** by cross-building the image on a faster x86
  machine and shipping it over:
  ```bash
  docker buildx build --platform linux/arm64 -f Dockerfile.cpu -t scanscribe:cpu --load . \
    && docker save scanscribe:cpu | ssh pi@<pi-ip> 'docker load'
  ```

### Tips
- Run the Whisper model from a USB SSD rather than the SD card for better I/O.
- Keep audio clips short; long recordings take noticeably longer on CPU.
- Check progress with `docker compose logs -f`.

## Architecture

```
ScanScribe Container (port 8000)
│
├── FastAPI web service
│   ├── Auth / Users
│   ├── Transcriptions / Logs
│   ├── Events pipeline API
│   ├── Insights (hour summaries)
│   └── Settings / Maintenance
│
├── Transcription engine (Whisper, multi-worker)
├── File watcher (./ingest or client HTTP upload)
│
├── Events pipeline
│   ├── NER service  →  SpanStore
│   ├── Worker LLM   →  opens new incidents
│   ├── Master LLM   →  attach / skip / close
│   ├── Header normalizer (event_type, location, units, status_detail)
│   ├── Event summary generator
│   └── Cleanup worker (auto-close stale by incident time)
│
└── Databases (SQLite)
    ├── scanscribe.db        (users, config)
    ├── scanscribe_logs.db   (transcription log entries)
    └── scanscribe_events.db (monitors, events, links, debug logs)
```

## Events Pipeline
You can find my fine-tuned NER model here on [huggingface.](https://huggingface.co/xxbubziexx/incident_ner_v1)

The pipeline processes every transcription through:

1. **NER** — extracts `EVT_TYPE`, `LOC`, `UNIT`, `ADDRESS`, etc.
2. **Worker LLM** (cheap model) — decides if an `EVT_TYPE` span should open a new incident
3. **Master LLM** (stronger model) — routes spans to open events: `attach`, `skip`, or `close`
4. **Header normalizer** — runs on create, every N attaches (`normalize_every_n_spans`), and on close; fills structured header fields from transcripts
5. **Summary generator** — chains after header normalization in the same thread once `summary_trigger_spans` is reached
6. **Cleanup worker** — background sweep that auto-closes events whose last radio transmission timestamp exceeds `auto_close_stale_seconds`

Configure monitors (talkgroup → monitor mapping) from the Events page.

## Configuration

All runtime settings live in **`config.yml`**. Environment variables in **`.env`** handle secrets and paths only.

### `.env` variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | **Required.** JWT signing key. Startup **fails** if missing, a known default, or shorter than 16 chars. Generate with `openssl rand -hex 32`. |
| `ALLOW_INSECURE_SECRET_KEY` | Set to `1` to boot anyway with a weak/empty `SECRET_KEY` (**local dev only**). |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime (default 60) |
| `DISABLE_OPEN_REGISTRATION` | Set to `1`/`true` to block public self-registration after the first admin account exists. |
| `MAX_UPLOAD_MB` | Max client upload size in MB (default 500; `0` disables the limit). |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed CORS origins (default `*`). |
| `INGEST_DIR` | Audio drop directory |
| `OUTPUT_DIR` | Processed audio storage |
| `LOG_DIR` | App logs |
| `DB_PATH` | Main SQLite DB path |
| `CONFIG_PATH` | Path to `config.yml` |
| `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `TORCH_NUM_THREADS` | PyTorch CPU thread limits |

### Key `config.yml` sections

| Section | Purpose |
|---|---|
| `model` | Whisper model name, path, workers, device |
| `transcription` | VAD, beam size, silence removal |
| `events_pipeline` | NER path, LLM routing, auto-close, normalize interval |
| `incidents_ollama` | Ollama URL, worker/master model names, timeout |
| `gemini` | Gemini API key and model for hour summaries |
| `summaries` | Auto-generation schedule |
| `storage` | Audio retention, cleanup hour |
| `logging` | Log level, rotation |

## ScanScribe Client

A lightweight audio file uploader for Windows. Available here: [Uploader Client on Github](https://github.com/xxbubziexx/Scanscribe-Uploader-Client). This is an active folder watcher for your scanner recording software recording directory. It uploads all recordings to the scanscribe server. Configurable in config.yml.

## Timestamp and Talkgroup Extraction

ScanScribe handles timestamps two different ways (config chooses). From file date modified or from the filename. SDRtrunk works natively with scanscribe and there is no need for any config.

### 1. From the filename (“title”) 
- YYYYMMDD_HHMMSS (e.g. 20260125_123543)
- HH-MM-SS AM/PM MM-DD-YY
- HH-MM-SS AM/PM only → uses today’s date


### 2. From the filesystem (“metadata”) 
- **macOS:** st_birthtime if present
- **otherwise:** st_mtime (modification time)

### How to configure proscan
1. Use `%TT %D %C` as a custom file format. **Use this format if you plan on extracting timestamp data from the title.**
2. Use `%TG %G %C` as a custom TIT2(title). **This is crucial for talkgroup extraction to work. SDRtrunk does this natively.**

## Docker Commands

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f

# Rebuild after code changes
docker-compose up -d --build

# Stop
docker-compose down

# Health check
curl http://localhost:8000/health
```

## Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and edit config
cp config.yml.example config.yml   # if present, else edit config.yml directly
cp .env.example .env

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Project Structure

```
scanscribe/
├── app/
│   ├── main.py                    # FastAPI app + lifespan startup
│   ├── config.py                  # Pydantic config schema + loader
│   ├── database.py                # SQLAlchemy sessions (3 DBs)
│   ├── models/                    # SQLAlchemy models
│   │   ├── user.py
│   │   ├── log_entry.py
│   │   ├── event.py               # Monitor, Event, EventTranscriptLink, SpanStore
│   │   └── hour_summary.py
│   ├── routes/                    # FastAPI routers
│   │   ├── auth.py, users.py
│   │   ├── logs.py, transcriptions.py, upload.py
│   │   ├── events.py              # Events pipeline API
│   │   ├── insights.py, settings.py, maintenance.py, watcher.py
│   ├── services/                  # Business logic
│   │   ├── events_worker.py       # NER → Worker → Master pipeline
│   │   ├── ollama_event_routing.py # Master LLM routing
│   │   ├── master_event_header_ollama.py
│   │   ├── event_summary_ollama.py
│   │   ├── ollama_worker.py       # Worker LLM triage
│   │   ├── ner_service.py
│   │   ├── events_common.py, events_debug.py
│   │   ├── transcription_engine.py
│   │   ├── queue_processor.py
│   │   ├── watcher.py
│   │   └── summaries_auto.py
│   ├── templates/                 # Jinja2 HTML pages
│   └── static/                    # CSS + JS
├── models/                        # Whisper + NER model weights
├── data/                          # SQLite databases (persistent)
├── logs/                          # Application logs
├── ingest/                        # Audio drop directory
├── Dockerfile
├── docker-compose.yml
├── config.yml
└── requirements.txt
```

## Troubleshooting

**Events not routing** — check `incidents_ollama.enabled: true` and `llm_routing: true` in `config.yml`. Verify Ollama is reachable at `base_url`.

**Header never fills** — check pipeline activity log on the Events page. Confirm `master_header_normalize: true` and the master model is loaded in Ollama.

**Stale events not closing** — both `auto_close_stale_seconds` and `cleanup_interval_seconds` must be > 0.

**Container won't start** — `docker-compose logs scanscribe`

**Database locked** — SQLite DBs live in `./data/` (persistent bind mount), not in the container layer.

**Model not found** — verify `model.name` in `config.yml` matches the folder name inside `./models/`.

## Security Notes

- Set a strong `SECRET_KEY` in `.env` before deployment. The app now **refuses to
  start** with a missing, known-default, or too-short key (generate one with
  `openssl rand -hex 32`). Override for local dev only with `ALLOW_INSECURE_SECRET_KEY=1`.
- After creating your first (admin) account, set `DISABLE_OPEN_REGISTRATION=1` to
  block public self-registration.
- Use an HTTPS reverse proxy (nginx, Traefik, Caddy) in production
- Restrict the Ollama host to your LAN
- Restrict CORS with `CORS_ALLOW_ORIGINS` (comma-separated) if exposing the API
- Limit upload size with `MAX_UPLOAD_MB` (default 500)
- The web interface and API have no rate limiting by default

## License

Proprietary — ScanScribe Project
