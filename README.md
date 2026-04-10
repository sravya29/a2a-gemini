# Gemini A2A Agent

An [A2A protocol](https://google.github.io/A2A)-compliant agent backed by Google Gemini, deployed on Google Cloud Run. Supports multi-turn conversations and Google OAuth 2.0 authentication.

## Architecture

```
Client / External Agent
        │
        │  POST /  (Bearer token required)
        ▼
  Cloud Run Service
        │
        ├── auth.py  →  validates Google OAuth token
        ├── agent.py →  A2A request handler
        └── Gemini API (gemini-2.5-flash)
```

## Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /.well-known/agent.json` | None | A2A agent discovery card |
| `POST /` | Google OAuth Bearer | Send A2A messages |
| `GET /health` | Google Identity Token | Health check |

## Public Agent Card

```
https://storage.googleapis.com/gemini-a2a-agent-card/agent.json
```

## Service URL

```
https://gemini-a2a-agent-581480210619.us-central1.run.app
```

## Local Development

### Prerequisites
- Docker
- gcloud CLI authenticated (`gcloud auth login`)
- Gemini API key

### Run locally

```bash
docker build -t gemini-a2a-local .

docker run -p 8080:8080 \
  -e GEMINI_API_KEY=<your-key> \
  -e PORT=8080 \
  gemini-a2a-local
```

### Test locally

```bash
# Health check (no auth needed)
curl http://localhost:8080/health

# Agent card (no auth needed)
curl http://localhost:8080/.well-known/agent.json

# Send a message (requires Google OAuth token)
TOKEN=$(gcloud auth print-access-token)

curl -s http://localhost:8080/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"text": "Hello, what can you do?"}],
        "messageId": "msg-1"
      }
    }
  }'
```

### Full OAuth consent flow test

```bash
pip install google-auth-oauthlib requests
python3 test_agent.py
```

Requires `client_secret.json` (OAuth 2.0 Desktop client) downloaded from Google Cloud Console → APIs & Services → Credentials.

## Deploy to Cloud Run

```bash
# Build and push
docker buildx build \
  --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/<PROJECT>/cloud-run-source-deploy/gemini-a2a-agent:latest \
  --push .

# Deploy
gcloud run deploy gemini-a2a-agent \
  --image us-central1-docker.pkg.dev/<PROJECT>/cloud-run-source-deploy/gemini-a2a-agent:latest \
  --region us-central1 \
  --platform managed \
  --set-env-vars GEMINI_API_KEY=<your-key>,HOST=https://<service-url>

# Refresh public agent card
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  https://<service-url>/.well-known/agent.json \
  | gsutil cp - gs://gemini-a2a-agent-card/agent.json
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | required | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model to use |
| `HOST` | Cloud Run URL | Public URL of this service (used in agent card) |
| `PORT` | `8000` | Server port |
| `ALLOWED_EMAIL` | _(any)_ | Restrict access to a specific Google account |

## Authentication

The `POST /` endpoint validates Google OAuth 2.0 Bearer tokens via Google's tokeninfo API. Tokens can be obtained via:

- `gcloud auth print-access-token` (for CLI/testing)
- Google OAuth consent flow (for end users via `test_agent.py`)
- Service account credentials (for agent-to-agent calls)
