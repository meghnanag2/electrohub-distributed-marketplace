"""
RabbitMQ consumer — runs inside notification-service.

Pulls jobs from the durable `electrohub.notifications` queue and
processes them. If the handler fails, the message is nacked and
requeued (RabbitMQ retries it when the service restarts).

This is the correct use of RabbitMQ:
  - Guaranteed delivery (message survives service crash)
  - One job processed by exactly one worker
  - Easy to scale: add more notification-service replicas,
    RabbitMQ distributes jobs across all of them
"""

import json
import os
import structlog

log = structlog.get_logger()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
QUEUE_NAME    = "electrohub.notifications"


def _handle(ch, method, properties, body):
    try:
        job = json.loads(body)
        jtype = job.get("type")
        log.info("notification_job_received", type=jtype, job=job)

        if jtype == "message_received":
            _handle_message_received(job)
        elif jtype == "item_sold":
            _handle_item_sold(job)
        else:
            log.warning("unknown_notification_type", type=jtype)

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as exc:
        log.error("notification_job_failed", error=str(exc))
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def _handle_message_received(job: dict):
    seller_id = job.get("seller_id")
    buyer_id  = job.get("buyer_id")
    item_id   = job.get("item_id")
    preview   = job.get("preview", "")
    log.info("email_notification",
             to=seller_id, from_buyer=buyer_id,
             item=item_id, preview=preview[:50])
    # In production: send email via SMTP / SendGrid / SES


def _handle_item_sold(job: dict):
    log.info("item_sold_notification", seller=job.get("seller_id"),
             item=job.get("item_id"))


def start_consuming():
    """Blocking call — runs until process killed."""
    import pika
    import time

    while True:
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
                    heartbeat=30,
                )
            )
            ch = conn.channel()
            ch.queue_declare(queue=QUEUE_NAME, durable=True)
            ch.basic_qos(prefetch_count=1)   # one job at a time per worker
            ch.basic_consume(queue=QUEUE_NAME, on_message_callback=_handle)
            log.info("rabbitmq_consumer_started", queue=QUEUE_NAME)
            ch.start_consuming()
        except Exception as exc:
            log.error("rabbitmq_consumer_error", error=str(exc))
            time.sleep(5)   # retry connection on broker restart
