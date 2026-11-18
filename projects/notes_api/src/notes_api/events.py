"""Domain events: outbox rows, Redis channels and signed webhooks. No FastAPI here."""

import hashlib
import hmac
import json
from datetime import datetime

from notes_api.models import OutboxEvent

SIGNATURE_HEADER = "X-Notes-Signature"
EVENT_ID_HEADER = "X-Notes-Event-Id"
SIGNATURE_TOLERANCE_SECONDS = 300


def user_channel(user_id: int) -> str:
    """The Redis pub/sub channel that carries one user's live events."""
    return f"notes:user:{user_id}"


def new_event(user_id: int, event_type: str, data: dict[str, object]) -> OutboxEvent:
    """An outbox row; the caller adds it to the same session (same transaction) as the change."""
    return OutboxEvent(user_id=user_id, event_type=event_type, payload=json.dumps(data))


def event_message(event: OutboxEvent) -> dict[str, object]:
    """The JSON body used for WebSocket messages and webhooks."""
    created = event.created_at.isoformat() if isinstance(event.created_at, datetime) else None
    return {
        "id": event.id,
        "type": event.event_type,
        "created_at": created,
        "data": json.loads(event.payload),
    }


def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    """'t=<unix time>,v1=<hex HMAC-SHA256 of "t.body">' (the scheme Stripe popularised)."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_webhook(secret: str, header: str, body: bytes, now: int) -> bool:
    """What a receiver does: recompute, compare in constant time, reject old timestamps."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except KeyError, ValueError:
        return False
    if abs(now - timestamp) > SIGNATURE_TOLERANCE_SECONDS:  # replayed long after sending
        return False
    expected = sign_webhook(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))
