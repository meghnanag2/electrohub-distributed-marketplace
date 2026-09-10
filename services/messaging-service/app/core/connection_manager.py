"""
WebSocket connection manager for real-time buyer-seller chat.

Multi-instance fan-out via Redis Pub/Sub:

  Instance A holds buyer's WebSocket
  Instance B holds seller's WebSocket
                                            Redis channel
  Buyer sends message → Instance A → publish("chat:{conv_id}", msg)
                                            │
                              ┌─────────────┘
                              │
                    All messaging-service instances subscribe
                    Instance A → delivers to buyer's socket
                    Instance B → delivers to seller's socket

This ensures delivery even when buyer and seller are connected
to different service replicas (essential for horizontal scaling).
"""

import asyncio
import json
from collections import defaultdict

import structlog
from fastapi import WebSocket

log = structlog.get_logger()


class ConversationManager:
    def __init__(self):
        # conv_id → list of active WebSocket connections on THIS instance
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    def conv_id(self, item_id: int, user_a: str, user_b: str) -> str:
        """Stable ID regardless of who connects first."""
        return f"{item_id}_{min(user_a, user_b)}_{max(user_a, user_b)}"

    async def connect(self, ws: WebSocket, conv_id: str) -> None:
        await ws.accept()
        self._connections[conv_id].append(ws)
        log.info("ws_connected", conv_id=conv_id,
                 total=len(self._connections[conv_id]))

    def disconnect(self, ws: WebSocket, conv_id: str) -> None:
        self._connections[conv_id].remove(ws)
        log.info("ws_disconnected", conv_id=conv_id,
                 total=len(self._connections[conv_id]))

    async def broadcast_local(self, conv_id: str, message: dict) -> None:
        """Push to all sockets on this instance for this conversation."""
        dead = []
        for ws in self._connections.get(conv_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[conv_id].remove(ws)


manager = ConversationManager()


async def redis_fanout_subscriber() -> None:
    """
    Background asyncio task — subscribes to Redis and delivers messages
    published by OTHER instances to local WebSocket connections.
    """
    from app.core.redis_client import get_redis_client
    redis = get_redis_client()
    pubsub = redis.pubsub()
    pubsub.psubscribe("electrohub:chat:*")   # pattern subscribe
    log.info("ws_fanout_subscribed")

    while True:
        try:
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
            if msg and msg.get("type") == "pmessage":
                channel = msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                conv_id = channel.split("electrohub:chat:")[-1]
                data = json.loads(msg["data"])
                await manager.broadcast_local(conv_id, data)
        except asyncio.CancelledError:
            pubsub.punsubscribe()
            return
        except Exception as exc:
            log.error("fanout_error", error=str(exc))
        await asyncio.sleep(0.01)
