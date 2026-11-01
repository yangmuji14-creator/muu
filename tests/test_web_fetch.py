import socket

from mcp_servers import web_fetch


def _addrinfo(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))


def test_rejects_host_with_any_private_dns_result(monkeypatch):
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo",
        lambda *_args, **_kwargs: [
            _addrinfo("93.184.216.34"), _addrinfo("10.0.0.8")
        ],
    )
    assert web_fetch._resolve_public_address("https://example.test") is None


def test_resolves_all_public_records_and_returns_pinned_ip(monkeypatch):
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo",
        lambda *_args, **_kwargs: [
            _addrinfo("93.184.216.34"),
            _addrinfo("2606:2800:220:1:248:1893:25c8:1946"),
        ],
    )
    assert web_fetch._resolve_public_address("https://example.test") == (
        "example.test", "93.184.216.34"
    )


def test_pinned_http_connection_uses_validated_address(monkeypatch):
    seen = []
    monkeypatch.setattr(
        web_fetch.socket, "create_connection",
        lambda address, *_args, **_kwargs: seen.append(address) or object(),
    )
    connection = web_fetch._PinnedHTTPConnection(
        "example.test", address="93.184.216.34", timeout=4
    )
    connection.connect()
    assert seen == [("93.184.216.34", 80)]


def test_fetch_caps_response_read(monkeypatch):
    requested_lengths = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, length):
            requested_lengths.append(length)
            return b"<html><body>bounded</body></html>"

    monkeypatch.setattr(
        web_fetch, "_resolve_public_address",
        lambda _url: ("example.test", "93.184.216.34"),
    )
    monkeypatch.setattr(
        web_fetch, "_open_public_url",
        lambda _request, address: Response() if address == "93.184.216.34" else None,
    )
    assert web_fetch.fetch({"url": "https://example.test"}) == "bounded"
    assert requested_lengths == [web_fetch._MAX_RESPONSE_BYTES + 1]
