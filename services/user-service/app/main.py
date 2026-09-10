import asyncio
import os
from contextlib import asynccontextmanager

import grpc.aio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.exceptions import ElectroHubException, electrohub_exception_handler, unhandled_exception_handler
from app.core.logging_config import configure_logging, request_logging_middleware
from app.api.auth import router as auth_router
from app.api.users import router as users_router

configure_logging()


async def _serve_grpc():
    from app.grpc.servicer import UserServicer
    from app.grpc.generated import user_pb2_grpc
    server = grpc.aio.server()
    user_pb2_grpc.add_UserServiceServicer_to_server(UserServicer(), server)
    server.add_insecure_port("[::]:50051")
    await server.start()
    await server.wait_for_termination()


@asynccontextmanager
async def lifespan(app: FastAPI):
    grpc_task = asyncio.create_task(_serve_grpc())
    yield
    grpc_task.cancel()
    try:
        await grpc_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ElectroHub — User Service", lifespan=lifespan)

app.add_exception_handler(ElectroHubException, electrohub_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.middleware("http")(request_logging_middleware)

app.include_router(auth_router)
app.include_router(users_router)


@app.get("/health")
def health():
    return {"service": "user-service", "status": "ok"}
