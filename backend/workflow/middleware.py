"""Bound streamed request memory before JSON/model parsing."""
import json
import asyncio
import threading
import math
from uuid import uuid4

from backend.api.contracts import ApiError
from .security import MAX_BODY


class BodyLimit:
    def __init__(self, app):
        self.app = app
        self.slots = threading.BoundedSemaphore(16)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/v2/"):
            return await self.app(scope, receive, send)
        if not self.slots.acquire(blocking=False):
            return await self.error(send, 503, "REQUEST_CAPACITY", "동시 HTTP 요청 상한에 도달함")
        try:
            return await self.bounded(scope, receive, send)
        finally:
            self.slots.release()

    @staticmethod
    async def error(send, status, code, message):
        request_id = uuid4().hex
        data = json.dumps(ApiError(status, code, message).body(request_id)).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"cache-control", b"no-store"),
            (b"x-request-id", request_id.encode())]})
        return await send({"type": "http.response.body", "body": data})

    async def bounded(self, scope, receive, send):
        body = bytearray()
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return await self.error(send, 408, "REQUEST_TIMEOUT", "요청 본문 수신시간 상한 초과")
            try:
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                return await self.error(send, 408, "REQUEST_TIMEOUT", "요청 본문 수신시간 상한 초과")
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await self.error(send, 413, "REQUEST_TOO_LARGE", "요청 본문 상한은256KiB임")
            if not message.get("more_body", False):
                break
        delivered = False
        if body:
            headers = dict(scope.get("headers", []))
            if not headers.get(b"content-type", b"").lower().startswith(b"application/json"):
                return await self.error(send, 415, "JSON_REQUIRED", "JSON 본문이 필요함")
            def reject_constant(value):
                raise ValueError
            def finite_float(value):
                result = float(value)
                if not math.isfinite(result):
                    raise ValueError
                return result
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError
                    value[key] = item
                return value
            try:
                json.loads(body, parse_constant=reject_constant, parse_float=finite_float, object_pairs_hook=unique)
            except (ValueError, TypeError, RecursionError):
                return await self.error(send, 422, "REQUEST_VALIDATION_FAILED", "유한한 값과 중복 키 없는 JSON이 필요함")
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)
