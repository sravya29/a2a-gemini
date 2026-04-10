import os
import uvicorn
import httpx
from contextvars import ContextVar

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import JSONResponse

from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
)
from a2a.utils import new_agent_text_message

from auth import verify_google_token

# ── Config ─────────────────────────────────────────────────────────────────────

HOST = os.getenv("HOST", "https://a2a-snow.onrender.com/")
PORT = int(os.getenv("PORT", 8000))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent"

# ── Gemini call ────────────────────────────────────────────────────────────────

async def call_gemini(user_text: str, context_history: list = None) -> str:
    """Call Gemini API using centralized API key."""
    contents = []

    if context_history:
        contents.extend(context_history)

    contents.append({
        "role": "user",
        "parts": [{"text": user_text}]
    })

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": contents},
        )

    resp.raise_for_status()
    data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected Gemini response format: {data}") from e


# ── In-memory multi-turn store ─────────────────────────────────────────────────

class ConversationStore:
    """Tracks conversation history per contextId for multi-turn support."""
    def __init__(self):
        self._store: dict[str, list] = {}

    def get(self, context_id: str) -> list:
        return self._store.get(context_id, [])

    def append(self, context_id: str, role: str, text: str):
        if context_id not in self._store:
            self._store[context_id] = []
        self._store[context_id].append({
            "role": role,
            "parts": [{"text": text}]
        })

    def clear(self, context_id: str):
        self._store.pop(context_id, None)


conversation_store = ConversationStore()


# ── Agent executor ─────────────────────────────────────────────────────────────

class GeminiAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue):
        user_text = ""
        for part in context.message.parts:
            if hasattr(part.root, "text"):
                user_text += part.root.text

        if not user_text.strip():
            await event_queue.enqueue_event(
                new_agent_text_message("I received an empty message. Please send some text.")
            )
            return

        ctx_id = context.context_id or context.task_id or "default"
        history = conversation_store.get(ctx_id)

        try:
            gemini_reply = await call_gemini(user_text, history)
        except httpx.HTTPStatusError as e:
            gemini_reply = f"Gemini API error ({e.response.status_code}): {e.response.text}"
        except Exception as e:
            gemini_reply = f"Error calling Gemini: {str(e)}"

        conversation_store.append(ctx_id, "user", user_text)
        conversation_store.append(ctx_id, "model", gemini_reply)

        await event_queue.enqueue_event(
            new_agent_text_message(gemini_reply)
        )

    async def cancel(self, context: RequestContext, event_queue):
        ctx_id = context.context_id or context.task_id or "default"
        conversation_store.clear(ctx_id)


# ── Agent card ─────────────────────────────────────────────────────────────────

agent_card = AgentCard(
    name="Gemini A2A Agent",
    description=(
        "A2A-compliant agent backed by Google Gemini. "
        "Supports multi-turn conversations. "
        "Requires Google OAuth 2.0 Bearer token for authentication."
    ),
    url=HOST,
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    securitySchemes={
        "google_oauth2": {
            "type": "oauth2",
            "description": "Google OAuth 2.0 for authentication.",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": "https://accounts.google.com/o/oauth2/auth",
                    "tokenUrl": "https://oauth2.googleapis.com/token",
                    "scopes": {
                        "openid": "OpenID Connect",
                        "email": "View your email address",
                        "profile": "View your basic profile info"
                    }
                }
            }
        }
    },
    security=[{"google_oauth2": [
        "openid",
        "email",
        "profile"
    ]}],
    skills=[
        AgentSkill(
            id="gemini_chat",
            name="Gemini Chat",
            description=(
                "Send messages to Gemini and get intelligent responses. "
                "Supports multi-turn conversation via contextId."
            ),
            tags=["gemini", "chat", "llm"],
            inputModes=["text"],
            outputModes=["text"],
        )
    ],
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
)

# ── Build base A2A app ─────────────────────────────────────────────────────────

handler = DefaultRequestHandler(
    agent_executor=GeminiAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

base_app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=handler,
).build()

# ── FastAPI wrapper with auth ──────────────────────────────────────────────────

app = FastAPI(title="Gemini A2A Agent")


@app.get("/.well-known/agent.json")  # Public — no auth needed for discovery
async def get_agent_card():
    return JSONResponse(agent_card.model_dump(exclude_none=True))


@app.post("/", dependencies=[Depends(verify_google_token)])  # Protected with OAuth
async def a2a_endpoint(request: Request):
    for route in base_app.router.routes:
        if hasattr(route, "methods") and "POST" in (route.methods or set()):
            return await route.endpoint(request)
    raise HTTPException(status_code=500, detail="A2A POST handler not found")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent": "gemini-a2a",
        "model": GEMINI_MODEL,
        "host": HOST,
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
