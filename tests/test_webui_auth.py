import pytest
from aiohttp import BasicAuth, web
from aiohttp.test_utils import TestClient, TestServer

from webui.server import _web_auth_config, _web_auth_middleware


def test_loopback_does_not_require_credentials(monkeypatch):
    monkeypatch.delenv("MU_WEB_AUTH_USER", raising=False)
    monkeypatch.delenv("MU_WEB_AUTH_PASSWORD", raising=False)
    assert _web_auth_config("127.0.0.1") is None
    assert _web_auth_config("::1") is None
    assert _web_auth_config("localhost") is None


def test_non_loopback_requires_both_credentials(monkeypatch):
    monkeypatch.delenv("MU_WEB_AUTH_USER", raising=False)
    monkeypatch.delenv("MU_WEB_AUTH_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="MU_WEB_AUTH_USER"):
        _web_auth_config("0.0.0.0")
    monkeypatch.setenv("MU_WEB_AUTH_USER", "user")
    with pytest.raises(RuntimeError, match="MU_WEB_AUTH_PASSWORD"):
        _web_auth_config("192.168.1.20")
    monkeypatch.setenv("MU_WEB_AUTH_PASSWORD", "short")
    with pytest.raises(RuntimeError, match="16 characters"):
        _web_auth_config("192.168.1.20")


@pytest.mark.asyncio
async def test_remote_middleware_authenticates_all_requests(monkeypatch):
    monkeypatch.setenv("MU_WEB_AUTH_USER", "companion")
    monkeypatch.setenv("MU_WEB_AUTH_PASSWORD", "correct horse battery staple")
    app = web.Application(middlewares=[_web_auth_middleware("0.0.0.0")])

    async def index(_request):
        return web.Response(text="ok")

    app.router.add_get("/", index)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        assert (await client.get("/")).status == 401
        assert (await client.get("/", auth=BasicAuth("companion", "wrong"))).status == 401
        response = await client.get(
            "/", auth=BasicAuth("companion", "correct horse battery staple")
        )
        assert response.status == 200
        assert await response.text() == "ok"
    finally:
        await client.close()
