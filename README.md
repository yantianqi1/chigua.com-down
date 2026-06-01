# Chigua Video Downloader 🎬

Web panel to download videos from [51吃瓜网 (chigua.com)](https://chigua.com) via Docker.

## Quick Start

```bash
docker compose up -d
```

Open http://localhost:8006

## Usage

1. Open the web panel
2. Paste article URLs (one per line)
3. Set download directory (default: `/downloads` inside container)
4. Set proxy address if chigua.com is blocked from your NAS network
5. Click "开始下载"
6. Monitor progress in real-time

## Proxy

The web panel can save a proxy address and reuse it for new tasks. The setting is persisted at `/downloads/settings.json`, so the default Docker volume keeps it on the host.

Docker Compose can also provide the initial proxy value:

```yaml
environment:
  - PORT=8006
  - CHIGUA_PROXY_URL=http://127.0.0.1:7890
```

With `network_mode: host`, `127.0.0.1` points to the NAS host, so this works for a local Clash HTTP/mixed port on the NAS. If `/downloads/settings.json` already exists, the saved web-panel setting overrides `CHIGUA_PROXY_URL`.

Supported formats:

```text
http://用户名:密码@服务器IP:HTTP端口
socks5://用户名:密码@服务器IP:SOCKS5端口
```

Empty proxy value clears the setting.

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
uvicorn main:app --host 0.0.0.0 --port 8006
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
