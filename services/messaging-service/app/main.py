import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.exceptions import ElectroHubException, electrohub_exception_handler, unhandled_exception_handler
from app.core.logging_config import configure_logging, request_logging_middleware
from app.api.messages import router as messages_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Background task: Redis fan-out subscriber for WebSocket multi-instance delivery
    from app.core.connection_manager import redis_fanout_subscriber
    fan_task = asyncio.create_task(redis_fanout_subscriber())
    yield
    fan_task.cancel()
    try:
        await fan_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ElectroHub — Messaging Service", lifespan=lifespan)

app.add_exception_handler(ElectroHubException, electrohub_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.middleware("http")(request_logging_middleware)
app.include_router(messages_router)


@app.get("/health")
def health():
    return {"service": "messaging-service", "status": "ok"}
