"""Real encryption/VAPID with fake DNS/HTTP; never contact a push endpoint."""
import base64
import json
import ssl
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import http_ece
import pytest

from backend.api.contracts import ApiError
from backend.workflow.push import PinnedConnection, WebPushSender, send_once
from backend.workflow.security import endpoint_host, public_address, validate_subscription
from tools.workflow_admin import generate


@pytest.fixture
def encrypted_input(tmp_path):
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    path = tmp_path / "server.pem"
    key = generate(path)
    return {"subscription": {"endpoint": "https://fcm.googleapis.com/fcm/send/SYNTHETIC-ONLY",
                             "keys": {"p256dh": encode(point), "auth": encode(b"synthetic-auth16")}},
            "private_key_file": str(path), "subject": "https://example.test",
            "payload": {"title": "반입맞춤 변경 알림", "body": "변경 내용을 확인해 주세요.",
                        "notification_id": "N-synthetic", "url": "/recipient#notification=N-synthetic"}}, private, key


def resolver(host, port, **kwargs):
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


@pytest.mark.parametrize("http_status,expected", [(201,"accepted"),(302,"failed"),(401,"failed"),
    (404,"expired"),(410,"expired"),(429,"failed"),(500,"unknown")])
def test_standard_encryption_vapid_statuses_and_no_redirect_or_body_read(encrypted_input, http_status, expected):
    data, private, key = encrypted_input
    calls = []
    class Connection:
        def __init__(self, host, address):
            calls.append((host,address))
        def request(self, method, path, body, headers):
            calls.append((method,path,body,headers))
        def getresponse(self):
            class Response:
                status = http_status
                def getheader(self,name):
                    return "120" if name == "Retry-After" else None
            return Response()
        def close(self):
            calls.append("closed")
    result = send_once(data, connection_factory=Connection, resolver=resolver)
    assert result["status"] == expected
    if http_status == 429:
        assert result["retry_after_seconds"] == 120 and result["error_code"] == "PUSH_RATE_LIMITED"
    assert calls[0] == ("fcm.googleapis.com", "8.8.8.8")
    assert len(calls) == 3 and calls[-1] == "closed"
    method, path, body, headers = calls[1]
    assert method == "POST" and path == "/fcm/send/SYNTHETIC-ONLY"
    assert "authorization" in {k.lower() for k in headers}
    assert headers["Content-Encoding"] == "aes128gcm"
    decoded = http_ece.decrypt(body, private_key=private, auth_secret=b"synthetic-auth16", version="aes128gcm")
    assert json.loads(decoded) == data["payload"]
    assert b"notification_id" not in body


@pytest.mark.parametrize("endpoint", ["http://fcm.googleapis.com/x", "https://127.0.0.1/x",
    "https://169.254.169.254/latest", "https://fcm.googleapis.com.evil.test/x", "https://fcm.googleapis.com@evil.test/x",
    "https://fcm.googleapis.com:444/x", "https://fcm.googleapis.com/x#secret", "https://fcm.googleapis.com/x?secret=1",
    "https://evil.push.apple.com.evil.test/x", "https://fcm.googleapis.com./x", "https://fcm.googleapis.com/\r\nx"])
def test_untrusted_endpoints_fail_before_dns_or_network(endpoint):
    with pytest.raises(ApiError):
        endpoint_host(endpoint)


@pytest.mark.parametrize("endpoint", ["https://wns2-par02p.notify.windows.com/x?token=AAA",
    "https://wns2-par02p.notify.windows.com/w/?token=AAA&x=1", "https://wns2-par02p.notify.windows.com/w/?other=AAA",
    "https://wns2-par02p.notify.windows.com/w/?token=", "https://notify.windows.com.evil.test/w/?token=AAA",
    "https://fcm.googleapis.com/w/?token=AAA", "http://wns2-par02p.notify.windows.com/w/?token=AAA"])
def test_wns_query_is_only_the_edge_token_form(endpoint):
    with pytest.raises(ApiError):
        endpoint_host(endpoint)


def test_edge_wns_endpoint_is_accepted_and_sent_with_its_token_query(encrypted_input):
    data, _, _ = encrypted_input
    data["subscription"]["endpoint"] = "https://wns2-par02p.notify.windows.com/w/?token=SYNTHETIC%2BONLY"
    assert endpoint_host(data["subscription"]["endpoint"]) == "wns2-par02p.notify.windows.com"
    calls = []
    class Connection:
        def __init__(self, host, address):
            calls.append(host)
        def request(self, method, path, body, headers):
            calls.append(path)
        def getresponse(self):
            return type("R", (), {"status": 201, "getheader": lambda self, n: None})()
        def close(self):
            pass
    assert send_once(data, connection_factory=Connection, resolver=resolver)["status"] == "accepted"
    assert calls == ["wns2-par02p.notify.windows.com", "/w/?token=SYNTHETIC%2BONLY"]


@pytest.mark.parametrize("addresses", [["127.0.0.1"],["10.0.0.1"],["169.254.169.254"],["::1"],
                                     ["8.8.8.8","192.168.0.1"]])
def test_private_or_mixed_dns_answers_are_rejected(addresses):
    with pytest.raises(ValueError):
        public_address("fcm.googleapis.com", resolver=lambda *a, **k: [(2,1,6,"",(value,443)) for value in addresses])


def test_dns_is_resolved_once_then_transport_uses_pinned_ip_and_original_sni(monkeypatch):
    connection = PinnedConnection("fcm.googleapis.com", "8.8.8.8")
    assert connection._context.verify_mode == ssl.CERT_REQUIRED and connection._context.check_hostname
    calls = []
    class Socket:
        def close(self):
            pass
    monkeypatch.setattr("backend.workflow.push.socket.create_connection", lambda address, timeout: calls.append(address) or Socket())
    class Context:
        def wrap_socket(self, sock, *, server_hostname):
            calls.append(server_hostname)
            return sock
    connection._context = Context()
    connection.connect()
    assert calls == [("8.8.8.8",443),"fcm.googleapis.com"]
    connection.close()


def test_owned_child_timeout_is_unknown_without_stderr_or_endpoint_leak(encrypted_input, monkeypatch):
    data, _, _ = encrypted_input
    class Settings:
        vapid_private_key = __import__('pathlib').Path(data["private_key_file"])
        vapid_subject = data["subject"]
        push_enabled = True
    sender = WebPushSender(Settings())
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 12 and "SYNTHETIC-ONLY" not in str(args)
        raise subprocess.TimeoutExpired("private-transport", 12, stderr="SECRET-SUBSCRIPTION")
    monkeypatch.setattr("backend.workflow.push.subprocess.run", timeout)
    result = sender.send(data["subscription"], data["payload"])
    assert result == {"status":"unknown", "error_code":"PUSH_OUTCOME_UNKNOWN"}
    assert "SECRET" not in str(result)


def test_vapid_generation_never_overwrites_existing_private_key(tmp_path):
    path = tmp_path / "server.pem"
    public = generate(path)
    before = path.read_bytes()
    assert len(base64.urlsafe_b64decode(public + "=" * (-len(public)%4))) == 65
    with pytest.raises(FileExistsError):
        generate(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("auth","bad"),("p256dh","bad")])
def test_invalid_subscription_key_cannot_enter_storage(encrypted_input, field, value):
    data, _, _ = encrypted_input
    data["subscription"]["keys"][field] = value
    with pytest.raises(ApiError):
        validate_subscription(data["subscription"], now_ms=0)
