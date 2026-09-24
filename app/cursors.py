"""Signed pagination state. A cursor is not account-access authorization."""

import base64
import binascii
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models import TransactionType


class InvalidCursor(ValueError):
    pass


class TransactionCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    account_id: str
    from_date: str | None
    to_date: str | None
    transaction_type: TransactionType | None
    snapshot_id: int = Field(ge=1, le=9223372036854775807)
    last_id: int = Field(ge=1, le=9223372036854775807)
    last_created_at: str = Field(max_length=40)


def encode_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_part(value: str) -> bytes:
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if encode_part(decoded) != value:
        raise InvalidCursor()
    return decoded


def encode_cursor(cursor: TransactionCursor, secret: bytes) -> str:
    payload = cursor.model_dump_json().encode("utf-8")
    signature = hmac.digest(secret, payload, hashlib.sha256)
    return encode_part(payload) + "." + encode_part(signature)


def decode_cursor(token: str, secret: bytes) -> TransactionCursor:
    try:
        if not token or len(token) > 4096:
            raise InvalidCursor()
        payload_part, signature_part = token.split(".")
        payload = decode_part(payload_part)
        signature = decode_part(signature_part)
        expected_signature = hmac.digest(secret, payload, hashlib.sha256)
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidCursor()
        cursor = TransactionCursor.model_validate_json(payload)
        timestamp = datetime.fromisoformat(cursor.last_created_at)
        if timestamp.utcoffset() != timedelta(0) or cursor.last_id > cursor.snapshot_id:
            raise InvalidCursor()
        return cursor
    except (ValueError, binascii.Error, ValidationError) as error:
        raise InvalidCursor("invalid cursor") from error
