# Chigua Video Downloader 🎬

Web panel to download videos from [51吃瓜网 (chigua.com)](https://chigua.com) via Docker.

## Quick Start

```bash
docker compose up -d
```

Open http://localhost:8000

## Usage

1. Open the web panel
2. Paste article URLs (one per line)
3. Set download directory (default: `/downloads` inside container)
4. Click "开始下载"
5. Monitor progress in real-time

## Change Download Directory

Edit `docker-compose.yml`:

```yaml
volumes:
  - /your/host/path:/downloads   # change left side
```

## Manual Install (without Docker)

```bash
pip install -r requirements.txt
# ffmpeg must be installed on your system
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API

| Method   | Path              | Description              |
| -------- | ----------------- | ------------------------ |
| `POST`   | `/api/tasks`      | Submit download tasks    |
| `GET`    | `/api/tasks`      | List all tasks           |
| `DELETE` | `/api/tasks/{id}` | Cancel / remove a task   |
| `GET`    | `/api/health`     | Health check             |

### POST /api/tasks

```json
{
  "urls": "https://chigua.com/archives/123/\nhttps://chigua.com/archives/456/",
  "download_dir": "/downloads"
}
```
