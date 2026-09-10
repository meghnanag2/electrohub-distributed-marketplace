import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.exceptions import ElectroHubException, electrohub_exception_handler, unhandled_exception_handler
from app.core.logging_config import configure_logging, request_logging_middleware
from app.api.activity import router as activity_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="ElectroHub — Activity Service", lifespan=lifespan)

app.add_exception_handler(ElectroHubException, electrohub_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.middleware("http")(request_logging_middleware)
app.include_router(activity_router)


@app.get("/health")
def health():
    return {"service": "activity-service", "status": "ok"}
