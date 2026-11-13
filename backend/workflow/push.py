"""One bounded subprocess per send. No redirects/proxies or automatic retries."""
from __future__ import annotations

import base64
import http.client
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.api.contracts import ROOT, canonical
from .security import endpoint_host, public_address, validate_subscription


def public_key(path: Path) -> str:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("P-256 private key required")
    value = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class WebPushSender:
    def __init__(self, settings):
        self.path, self.subject = settings.vapid_private_key, settings.vapid_subject
        self.configured = settings.push_enabled and self.path is not None
        self.application_server_key = public_key(self.path) if self.configured else None
        if self.configured:
            try:
                from py_vapid import Vapid
                Vapid.from_file(str(self.path)).sign({"aud":"https://fcm.googleapis.com", "sub":self.subject})
            except Exception:
                raise RuntimeError("VAPID 키/subject의 로컬 서명 검사가 실패함") from None

    def send(self, subscription: dict, payload: dict) -> dict:
        if not self.configured:
            return {"status": "failed", "error_code": "PUSH_NOT_CONFIGURED"}
        try:
            process = subprocess.run([sys.executable, "-X", "utf8", "-m", "backend.workflow.push_worker"],
                cwd=ROOT, input=canonical({"subscription": subscription, "payload": payload,
                                          "private_key_file": str(self.path), "subject": self.subject}),
                capture_output=True, text=True, encoding="utf-8", timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, check=True)
            result = json.loads(process.stdout)
            if (not {"status","error_code"} <= set(result) or set(result) - {"status","error_code","retry_after_seconds"}
                    or result["status"] not in {"accepted", "failed", "expired", "unknown"}):
                raise ValueError
            if "retry_after_seconds" in result and (type(result["retry_after_seconds"]) is not int
                                                      or not 1 <= result["retry_after_seconds"] <= 604800):
                raise ValueError
            return result
        except (subprocess.SubprocessError, ValueError, OSError):
            # Timeout could follow a completed HTTP send. Never call it a certain
            # failure and never expose stdout/stderr/URLs or automatically retry.
            return {"status": "unknown", "error_code": "PUSH_OUTCOME_UNKNOWN"}


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=5, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.sock.close()
            raise


def send_once(data: dict, *, connection_factory=PinnedConnection, resolver=None) -> dict:
    """Called in an owned 12s child, bounding DNS, encryption and HTTP together."""
    sent = False
    try:
        from pywebpush import WebPusher
        from py_vapid import Vapid
        subscription = validate_subscription(data["subscription"], now_ms=int(time.time() * 1000))
        host = endpoint_host(subscription["endpoint"])
        address = public_address(host, **({"resolver": resolver} if resolver else {}))
        body = WebPusher(subscription).encode(canonical(data["payload"]).encode(), content_encoding="aes128gcm")["body"]
        headers = Vapid.from_file(data["private_key_file"]).sign({
            "aud": "https://" + host, "sub": data["subject"], "exp": int(time.time()) + 43200})
        headers.update({"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                        "TTL": "60", "Urgency": "normal"})
        connection = connection_factory(host, address)
        try:
            sent = True
            target = urlsplit(subscription["endpoint"])
            # WNS(Edge)는 token 쿼리가 주소의 일부다. 다른 중계망은 endpoint_host가 쿼리를 이미 거절한다.
            connection.request("POST", target.path + ("?" + target.query if target.query else ""), body, headers)
            response = connection.getresponse()
            # No redirect-following or response body reads, especially errors.
            status = response.status
            retry_header = getattr(response, "getheader", lambda _: None)("Retry-After") if status == 429 else None
        finally:
            connection.close()
        if 200 <= status < 300:
            return {"status": "accepted", "error_code": None}
        if status in (404, 410):
            return {"status": "expired", "error_code": "PUSH_SUBSCRIPTION_EXPIRED"}
        if status == 429:
            delay = 60
            try:
                delay = int(retry_header) if str(retry_header).isdigit() else int(
                    (parsedate_to_datetime(retry_header) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError, AttributeError):
                pass
            return {"status":"failed", "error_code":"PUSH_RATE_LIMITED", "retry_after_seconds":max(1,min(delay,604800))}
        if status >= 500:
            return {"status": "unknown", "error_code": "PUSH_OUTCOME_UNKNOWN"}
        return {"status": "failed", "error_code": "PUSH_REJECTED"}
    except Exception:
        return {"status": "unknown" if sent else "failed",
                "error_code": "PUSH_OUTCOME_UNKNOWN" if sent else "PUSH_VALIDATION_FAILED"}
