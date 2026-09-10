"""
Messaging Service REST + WebSocket API.

Two parallel messaging paths:
  REST  POST /messages/contact/{item_id}  — fire-and-forget (backwards compat)
  WS    /messages/ws/{item_id}/{seller_id} — real-time bidirectional chat

WebSocket auth: token passed as ?token= query param (standard for WS).

After every message:
  1. Saved to PostgreSQL  (source of truth)
  2. Redis publish        (fan-out to all messaging-service instances)
  3. Kafka publish        (feeds analytics / Spark pipeline)
  4. RabbitMQ publish     (notification-service sends email if seller offline)
"""

import os
import json
from datetime import datetime

import structlog
from fastapi import APIRouter, Header, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.grpc.user_client import verify_token, get_user
from app.grpc.listing_client import get_seller_info
from app.core.exceptions import (
    ValidationException, ItemNotFoundException,
    RateLimitException, AuthException,
)
from app.core.redis_client import get_redis_client
from app.core.connection_manager import manager, redis_fanout_subscriber
from app.core.kafka_client import publish as kafka_publish
from app.core.rabbitmq_client import publish_notification

log = structlog.get_logger()
router = APIRouter(prefix="/messages", tags=["messages"])

DB_URL = (
    f"postgresql://{os.getenv('DB_USER','postgres')}:"
    f"{os.getenv('DB_PASSWORD','password')}@"
    f"{os.getenv('DB_HOST','postgres_shard0')}:"
    f"{os.getenv('DB_PORT','5432')}/"
    f"{os.getenv('DB_NAME','electrohub')}"
)
_engine = create_engine(DB_URL, pool_pre_ping=True)
_Session = sessionmaker(bind=_engine)


def _current_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthException("Authorization header required")
    valid, user_id = verify_token(authorization[7:])
    if not valid:
        raise AuthException("Invalid or expired token")
    return user_id


def _save_message(sender_id: str, receiver_id: str, item_id: int, body: str) -> dict:
    db = _Session()
    try:
        row = db.execute(text("""
            INSERT INTO marketplace_messages
                (sender_id, receiver_id, item_id, message_text, sent_at)
            VALUES (:sender, :receiver, :item_id, :msg, NOW())
            RETURNING message_id, sent_at
        """), {
            "sender": sender_id, "receiver": receiver_id,
            "item_id": item_id, "msg": body,
        }).fetchone()
        db.commit()
        return {
            "message_id": row[0],
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "item_id": item_id,
            "text": body,
            "sent_at": str(row[1]),
        }
    finally:
        db.close()


def _after_message(msg: dict, seller_email: str = "", seller_name: str = "") -> None:
    """Publish to Kafka + RabbitMQ after every message. Fire-and-forget."""
    conv_id = manager.conv_id(msg["item_id"], msg["sender_id"], msg["receiver_id"])

    # Redis fan-out → real-time WebSocket delivery on all instances
    get_redis_client().publish(
        f"electrohub:chat:{conv_id}", json.dumps(msg)
    )

    # Kafka → analytics / Spark pipeline
    kafka_publish("message_sent", {
        "buyer_id": msg["sender_id"],
        "seller_id": msg["receiver_id"],
        "item_id": msg["item_id"],
        "ts": msg["sent_at"],
    }, key=msg["sender_id"])

    # RabbitMQ → persistent notification job (email if seller offline)
    publish_notification("message_received", {
        "seller_id": msg["receiver_id"],
        "buyer_id": msg["sender_id"],
        "seller_email": seller_email,
        "seller_name": seller_name,
        "item_id": msg["item_id"],
        "preview": msg["text"][:100],
    })


# ── WebSocket endpoint ────────────────────────────────────────────────────── #

@router.websocket("/ws/{item_id}/{seller_id}")
async def chat_ws(
    websocket: WebSocket,
    item_id: int,
    seller_id: str,
    token: str = Query(...),
):
    """
    Real-time chat between buyer and seller about a specific item.

    URL: ws://localhost/messages/ws/{item_id}/{seller_id}?token={jwt}

    Connect as buyer: seller_id = the seller you're talking to
    Connect as seller: seller_id = your own user_id (you receive messages)
    """
    valid, caller_id = verify_token(token)
    if not valid:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    conv_id = manager.conv_id(item_id, caller_id, seller_id)
    await manager.connect(websocket, conv_id)
    log.info("chat_ws_joined", conv_id=conv_id, user=caller_id)

    # Send message history on connect
    db = _Session()
    try:
        history = db.execute(text("""
            SELECT message_id, sender_id, receiver_id, message_text, sent_at
            FROM marketplace_messages
            WHERE item_id = :iid
              AND ((sender_id = :a AND receiver_id = :b)
                OR (sender_id = :b AND receiver_id = :a))
            ORDER BY sent_at ASC
            LIMIT 50
        """), {"iid": item_id, "a": caller_id, "b": seller_id}).fetchall()

        # Opening the thread reads everything the other person sent us
        db.execute(text("""
            UPDATE marketplace_messages
            SET is_read = true
            WHERE item_id = :iid AND sender_id = :other AND receiver_id = :me
              AND is_read = false
        """), {"iid": item_id, "other": seller_id, "me": caller_id})
        db.commit()

        await websocket.send_json({
            "type": "history",
            "messages": [
                {"message_id": r[0], "sender_id": r[1], "receiver_id": r[2],
                 "text": r[3], "sent_at": str(r[4])}
                for r in history
            ]
        })
    finally:
        db.close()

    try:
        while True:
            data = await websocket.receive_json()
            text_body = data.get("text", "").strip()
            if not text_body:
                continue

            msg = _save_message(caller_id, seller_id, item_id, text_body)
            msg["type"] = "message"

            # Fan-out via Redis → all instances deliver to their local sockets
            get_redis_client().publish(
                f"electrohub:chat:{conv_id}", json.dumps(msg)
            )

            kafka_publish("message_sent", {
                "buyer_id": caller_id, "seller_id": seller_id,
                "item_id": item_id, "ts": msg["sent_at"],
            }, key=caller_id)

            publish_notification("message_received", {
                "seller_id": seller_id, "buyer_id": caller_id,
                "item_id": item_id, "preview": text_body[:100],
            })

    except WebSocketDisconnect:
        manager.disconnect(websocket, conv_id)
        log.info("chat_ws_left", conv_id=conv_id, user=caller_id)


# ── REST endpoint (backwards compat / non-JS clients) ────────────────────── #

class ContactRequest(BaseModel):
    subject: str
    message: str


@router.post("/contact/{item_id}")
def contact_seller(
    item_id: int,
    body: ContactRequest,
    authorization: str | None = Header(default=None),
):
    if len(body.subject) < 5:
        raise ValidationException("Subject must be at least 5 characters")
    if len(body.message) < 20:
        raise ValidationException("Message must be at least 20 characters")

    buyer_id = _current_user(authorization)

    seller_info = get_seller_info(item_id)
    if not seller_info:
        raise ItemNotFoundException(f"Item {item_id} not found or inactive")

    redis = get_redis_client()
    rate_key = f"contact:{buyer_id}:{item_id}:{datetime.now().strftime('%Y-%m-%d')}"
    count = redis.incr(rate_key)
    if count == 1:
        redis.expire(rate_key, 86400)
    if count > 5:
        raise RateLimitException("Too many contact attempts today", retry_after=86400)

    msg = _save_message(
        buyer_id, seller_info.seller_id, item_id,
        f"Subject: {body.subject}\n\n{body.message}",
    )
    _after_message(msg, seller_info.seller_email, seller_info.seller_name)
    log.info("contact_seller_success", buyer=buyer_id, item=item_id)
    return {"success": True, "message": "Message sent to seller"}


@router.get("/unread-count")
def get_unread_count(authorization: str | None = Header(default=None)):
    user_id = _current_user(authorization)
    db = _Session()
    try:
        row = db.execute(text(
            "SELECT COUNT(*) FROM marketplace_messages WHERE receiver_id = :uid AND is_read = false"
        ), {"uid": user_id}).fetchone()
    finally:
        db.close()
    return {"unread": int(row[0])}


@router.get("/inbox")
def get_inbox(
    skip: int = 0,
    limit: int = 20,
    authorization: str | None = Header(default=None),
):
    user_id = _current_user(authorization)
    db = _Session()
    try:
        rows = db.execute(text("""
            SELECT message_id, sender_id, receiver_id, item_id,
                   message_text, sent_at, is_read
            FROM marketplace_messages
            WHERE receiver_id = :uid
            ORDER BY sent_at DESC
            LIMIT :limit OFFSET :skip
        """), {"uid": user_id, "limit": limit, "skip": skip}).fetchall()
    finally:
        db.close()

    return {"messages": [
        {"message_id": r[0], "sender_id": r[1], "receiver_id": r[2],
         "item_id": r[3], "text": r[4], "sent_at": str(r[5]), "is_read": r[6]}
        for r in rows
    ]}


@router.get("/conversation/{item_id}/{other_user_id}")
def get_conversation(
    item_id: int,
    other_user_id: str,
    authorization: str | None = Header(default=None),
):
    """Fetch full conversation history for a listing (REST fallback)."""
    caller_id = _current_user(authorization)
    db = _Session()
    try:
        rows = db.execute(text("""
            SELECT message_id, sender_id, receiver_id, message_text, sent_at, is_read
            FROM marketplace_messages
            WHERE item_id = :iid
              AND ((sender_id = :a AND receiver_id = :b)
                OR (sender_id = :b AND receiver_id = :a))
            ORDER BY sent_at ASC
        """), {"iid": item_id, "a": caller_id, "b": other_user_id}).fetchall()
    finally:
        db.close()

    return {"messages": [
        {"message_id": r[0], "sender_id": r[1], "receiver_id": r[2],
         "text": r[3], "sent_at": str(r[4]), "is_read": r[5]}
        for r in rows
    ]}
