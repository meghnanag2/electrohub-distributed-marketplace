"""
Kafka producer — shared by all services that emit events.

Topics:
  electrohub.item.viewed    — user viewed a listing
  electrohub.item.saved     — user saved/wishlisted a listing
  electrohub.message.sent   — buyer sent seller a message
  electrohub.user.login     — user logged in

These events feed the Spark ETL pipeline → ML recommendations.
Producer is created once per process (lru_cache) and is thread-safe.
"""

import os
import json
import structlog
from functools import lru_cache

log = structlog.get_logger()

KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "kafka:9092")

TOPICS = {
    "item_viewed":   "electrohub.item.viewed",
    "item_saved":    "electrohub.item.saved",
    "message_sent":  "electrohub.message.sent",
    "user_login":    "electrohub.user.login",
}


@lru_cache(maxsize=1)
def _get_producer():
    from kafka import KafkaProducer
    return KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retries=3,
    )


def publish(topic_key: str, event: dict, key: str | None = None) -> None:
    """
    Fire-and-forget publish. Never raises — a Kafka outage must not
    break the primary request path.

    topic_key: one of the TOPICS dict keys, e.g. "item_viewed"
    key: partition key (e.g. user_id for user events)
    """
    topic = TOPICS.get(topic_key, topic_key)
    try:
        _get_producer().send(topic, value=event, key=key)
        log.info("kafka_published", topic=topic, key=key)
    except Exception as exc:
        log.error("kafka_publish_failed", topic=topic, error=str(exc))
