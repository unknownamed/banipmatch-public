"""Workflow secrets, strict endpoint validation and bounded public input."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.fernet import Fernet

from backend.api.contracts import ApiError, canonical, validate
from backend.api.storage_checks import storage_checks

MAX_BODY = 256 * 1024
LIMITS = {"jobs": 20, "vehicles": 10, "locations": 32, "windows": 20,
          "travel_times": 1024, "baseline_assignments": 20, "baseline_unassigned_job_ids": 20}
IDENTIFIER = re.compile(r"[a-f0-9]{32}")


def hashed(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_id(prefix="") -> str:
    return prefix + secrets.token_hex(16)


class Secrets:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        raw = path.read_bytes()
        self.cipher = Fernet(raw)
        self.signing_key = base64.urlsafe_b64decode(raw)

    def token(self, kind: str, sid: str, identifier: str) -> str:
        signature = hmac.new(self.signing_key, f"{kind}:{sid}:{identifier}".encode(), hashlib.sha256).hexdigest()
        return f"{sid}.{identifier}.{signature}"

    def verify(self, token: str, kind: str) -> tuple[str, str]:
        try:
            sid, identifier, signature = token.split(".")
            if not IDENTIFIER.fullmatch(sid) or not IDENTIFIER.fullmatch(identifier):
                raise ValueError
            if not hmac.compare_digest(self.token(kind, sid, identifier), token):
                raise ValueError
            return sid, identifier
        except (ValueError, TypeError, AttributeError):
            raise ApiError(401, "RECIPIENT_REQUIRED", "유효한 초대/수신자 권한이 필요함") from None

    def encrypt(self, value: dict) -> str:
        return self.cipher.encrypt(canonical(value).encode()).decode()

    def decrypt(self, value: str) -> dict:
        return json.loads(self.cipher.decrypt(value.encode()))

    def fingerprint(self, endpoint: str) -> str:
        return hmac.new(self.signing_key, endpoint.encode(), hashlib.sha256).hexdigest()


def csrf(cookie: str) -> str:
    return hashed("csrf:" + cookie)


def validate_snapshot_bounds(snapshot: dict) -> None:
    validate("Snapshot", snapshot)
    storage_checks(snapshot)
    if any(len(snapshot[k]) > limit for k, limit in LIMITS.items()):
        raise ApiError(422, "INPUT_LIMIT_EXCEEDED", "모의 입력 규모가 서버 상한을 넘음")
    def evidence(node):
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "evidence":
                    if item["kind"] not in {"simulated", "assumed"}:
                        raise ApiError(422, "DEMO_EVIDENCE_ONLY", "공개 시연에는 명시적 모의/가정 근거만 허용")
                else:
                    evidence(item)
        elif isinstance(node, list):
            for item in node:
                evidence(item)
    evidence(snapshot)


def endpoint_host(endpoint: str) -> str:
    try:
        if not isinstance(endpoint, str) or len(endpoint) > 2048 or not endpoint.isascii():
            raise ValueError
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        # Windows Edge는 WNS(…notify.windows.com/w/?token=…)를 쓴다. 쿼리는 WNS의 token 하나만 허용.
        wns = bool(re.fullmatch(r"[a-z0-9-]+\.notify\.windows\.com", host))
        allowed = (host in {"fcm.googleapis.com", "updates.push.services.mozilla.com"}
                   or bool(re.fullmatch(r"[a-z0-9-]+\.push\.apple\.com", host)) or wns)
        query_ok = (not parsed.query if not wns
                    else parsed.path == "/w/" and bool(re.fullmatch(r"token=[A-Za-z0-9%._~-]+", parsed.query)))
        if (parsed.scheme != "https" or not allowed or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or not query_ok or not parsed.path or parsed.path == "/"
                or any(ord(c) < 33 or ord(c) > 126 for c in endpoint) or "\\" in endpoint):
            raise ValueError
        return host
    except (ValueError, TypeError, AttributeError):
        raise ApiError(422, "SUBSCRIPTION_INVALID", "지원하는 HTTPS 푸시 구독 주소가 필요함") from None


def decoded_key(value: str, length: int) -> bytes:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(raw) != length:
            raise ValueError
        return raw
    except (ValueError, TypeError):
        raise ApiError(422, "SUBSCRIPTION_INVALID", "푸시 구독키 형식이 맞지 않음") from None


def validate_subscription(value: dict, *, now_ms: int) -> dict:
    if not isinstance(value, dict) or set(value) - {"endpoint", "keys", "expirationTime"}:
        raise ApiError(422, "SUBSCRIPTION_INVALID", "푸시 구독 형식을 확인해야 함")
    endpoint_host(value.get("endpoint"))
    keys = value.get("keys")
    if not isinstance(keys, dict) or set(keys) != {"p256dh", "auth"}:
        raise ApiError(422, "SUBSCRIPTION_INVALID", "푸시 구독키가 필요함")
    point = decoded_key(keys["p256dh"], 65)
    decoded_key(keys["auth"], 16)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except ValueError:
        raise ApiError(422, "SUBSCRIPTION_INVALID", "유효한 P-256 공개키가 필요함") from None
    expiration = value.get("expirationTime")
    if expiration is not None and (type(expiration) is not int or not now_ms < expiration <= now_ms + 366 * 86400000):
        raise ApiError(422, "SUBSCRIPTION_INVALID", "구독 만료시각을 확인해야 함")
    return {"endpoint": value["endpoint"], "keys": dict(keys), "expirationTime": expiration}


def public_address(host: str, resolver=socket.getaddrinfo) -> str:
    """Reject mixed public/private DNS too. The transport pins the returned IP."""
    records = resolver(host, 443, type=socket.SOCK_STREAM)
    addresses = [record[4][0] for record in records]
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("unsafe push DNS")
    return addresses[0]
