from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from .errors import AppError

Scope = Literal["admin", "terminal"]


@dataclass(frozen=True, slots=True)
class Principal:
    scope: Scope
    fingerprint: str


def key_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def authenticate(api_key: str | None, expected: str, scope: Scope) -> Principal:
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise AppError("invalid_api_key", "API key is invalid", 401)
    return Principal(scope=scope, fingerprint=key_fingerprint(api_key))


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    if not value or len(value) > 4096:
        raise ValueError("invalid token part")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class Confirmation:
    identity_id: UUID
    issued_at: datetime
    expires_at: datetime
    token_id: UUID


class TokenSigner:
    def __init__(self, signing_key: str, ttl_seconds: int) -> None:
        if not signing_key:
            raise ValueError("signing key is required")
        self._key = signing_key.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def issue(self, identity_id: UUID, now: datetime | None = None) -> tuple[str, datetime]:
        current = now or datetime.now(UTC)
        issued_at = int(current.timestamp())
        expires_at = issued_at + self._ttl_seconds
        header = {"alg": "HS256", "typ": "attendance-confirmation"}
        payload = {
            "aud": "attendance-confirmation",
            "exp": expires_at,
            "iat": issued_at,
            "jti": str(uuid4()),
            "sub": str(identity_id),
        }
        encoded_header = _encode(json.dumps(header, separators=(",", ":")).encode())
        encoded_payload = _encode(json.dumps(payload, separators=(",", ":")).encode())
        message = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self._key, message, hashlib.sha256).digest()
        return f"{encoded_header}.{encoded_payload}.{_encode(signature)}", datetime.fromtimestamp(
            expires_at, UTC
        )

    def verify(self, token: str, now: datetime | None = None) -> Confirmation:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("invalid token shape")
            encoded_header, encoded_payload, encoded_signature = parts
            message = f"{encoded_header}.{encoded_payload}".encode("ascii")
            expected_signature = hmac.new(self._key, message, hashlib.sha256).digest()
            supplied_signature = _decode(encoded_signature)
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ValueError("invalid signature")
            header = json.loads(_decode(encoded_header))
            payload = json.loads(_decode(encoded_payload))
            if header != {"alg": "HS256", "typ": "attendance-confirmation"}:
                raise ValueError("invalid header")
            if payload.get("aud") != "attendance-confirmation":
                raise ValueError("invalid audience")
            identity_id = UUID(payload["sub"])
            issued_at = int(payload["iat"])
            expires_at = int(payload["exp"])
            token_id = UUID(payload["jti"])
            if expires_at <= issued_at or expires_at - issued_at > self._ttl_seconds:
                raise ValueError("invalid lifetime")
            current = int((now or datetime.now(UTC)).timestamp())
            if issued_at > current + 30 or expires_at <= current:
                raise ValueError("expired token")
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            binascii.Error,
            OverflowError,
        ):
            raise AppError(
                "invalid_confirmation_token", "Confirmation token is invalid or expired", 401
            ) from None
        return Confirmation(
            identity_id=identity_id,
            issued_at=datetime.fromtimestamp(issued_at, UTC),
            expires_at=datetime.fromtimestamp(expires_at, UTC),
            token_id=token_id,
        )
