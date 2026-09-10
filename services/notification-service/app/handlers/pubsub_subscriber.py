"""
Redis Pub/Sub subscriber — listens to events from all other services.
Runs as an asyncio loop inside notification-service.
"""

import asyncio
import json
import structlog
from app.core.redis_client import get_redis_client
from app.handlers.email_handler import send_contact_email

log = structlog.get_logger()

CHANNELS = [
    "electrohub:events:message_sent",
    "electrohub:events:item_saved",
    "electrohub:events:item_listed",
]


async def subscribe_loop():
    redis = get_redis_client()
    pubsub = redis.pubsub()
    pubsub.subscribe(*CHANNELS)
    log.info("pubsub_subscribed", channels=CHANNELS)

    while True:
        try:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if msg:
                await _dispatch(msg)
        except asyncio.CancelledError:
            pubsub.unsubscribe()
            return
        except Exception as exc:
            log.error("pubsub_error", error=str(exc))
        await asyncio.sleep(0.01)


async def _dispatch(msg: dict):
    try:
        channel = msg.get("channel", b"")
        if isinstance(channel, bytes):
            channel = channel.decode()
        data = json.loads(msg["data"])
        short = channel.split(":")[-1]
        log.info("event_received", channel=short, data=data)

        if short == "message_sent":
            send_contact_email(
                seller_id=data.get("seller_id"),
                buyer_id=data.get("buyer_id"),
                item_id=data.get("item_id"),
                subject=data.get("subject", "Marketplace message"),
                message=data.get("message", ""),
            )
        elif short == "item_listed":
            log.info("item_listed_event", seller=data.get("seller_id"), item=data.get("item_id"))
        elif short == "item_saved":
            log.info("item_saved_event", user=data.get("user_id"), item=data.get("item_id"))

    except Exception as exc:
        log.error("event_dispatch_error", error=str(exc))
