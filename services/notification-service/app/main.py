"""
Notification Service — no REST API, two concurrent consumers:
  1. RabbitMQ consumer  — persistent notification jobs (email, push)
  2. Redis Pub/Sub      — lightweight system events (logging, analytics)
  3. gRPC server        — direct calls from other services
"""

import asyncio
import threading
import grpc.aio
import structlog

from app.core.logging_config import configure_logging

configure_logging()
log = structlog.get_logger()


def _run_rabbitmq_in_thread():
    """RabbitMQ uses blocking I/O — run in a separate thread."""
    from app.handlers.rabbitmq_consumer import start_consuming
    start_consuming()


async def _serve_grpc():
    from app.grpc.servicer import NotificationServicer
    from app.grpc.generated import notification_pb2_grpc
    server = grpc.aio.server()
    notification_pb2_grpc.add_NotificationServiceServicer_to_server(
        NotificationServicer(), server)
    server.add_insecure_port("[::]:50055")
    await server.start()
    log.info("grpc_server_started", port=50055)
    await server.wait_for_termination()


async def _serve_pubsub():
    from app.handlers.pubsub_subscriber import subscribe_loop
    await subscribe_loop()


async def main():
    log.info("notification_service_starting")

    # RabbitMQ consumer runs in a background thread (blocking API)
    t = threading.Thread(target=_run_rabbitmq_in_thread, daemon=True)
    t.start()

    # gRPC + Redis Pub/Sub run as async tasks
    await asyncio.gather(_serve_grpc(), _serve_pubsub())


if __name__ == "__main__":
    asyncio.run(main())
