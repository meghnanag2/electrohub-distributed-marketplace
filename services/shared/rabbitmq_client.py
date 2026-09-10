"""
RabbitMQ client — used for background notification jobs.

Pattern: messaging-service publishes a job → RabbitMQ queue →
         notification-service worker picks it up → sends email / push.

Why RabbitMQ here and not Redis Pub/Sub?
  - RabbitMQ persists messages (durable=True + delivery_mode=2).
    If notification-service restarts, jobs are not lost — they wait.
  - Redis Pub/Sub drops messages if no subscriber is connected.
  - For transactional notifications (email on message received),
    guaranteed delivery matters.

Queue: electrohub.notifications  (durable, persistent messages)
"""

import os
import json
import structlog

log = structlog.get_logger()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
QUEUE_NAME    = "electrohub.notifications"


def _get_connection():
    import pika
    return pika.BlockingConnection(
        pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
            heartbeat=30,
            blocked_connection_timeout=10,
        )
    )


def publish_notification(notification_type: str, payload: dict) -> None:
    """
    Publish a notification job to RabbitMQ.
    Never raises — RabbitMQ outage must not block the primary flow.

    notification_type: "message_received" | "item_sold" | "item_saved_alert"
    """
    try:
        conn = _get_connection()
        ch = conn.channel()
        ch.queue_declare(queue=QUEUE_NAME, durable=True)
        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"type": notification_type, **payload}),
            properties=__import__("pika").BasicProperties(
                delivery_mode=2,   # persistent — survives broker restart
            ),
        )
        conn.close()
        log.info("rabbitmq_published", type=notification_type)
    except Exception as exc:
        log.error("rabbitmq_publish_failed", type=notification_type, error=str(exc))
