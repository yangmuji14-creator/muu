"""MCP Web Fetch Server — 网页抓取 (SSRF 防护)"""
import http.client
import ipaddress
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from .framing import FrameReader
else:
    from framing import FrameReader

def _send(msg):
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8") + body)
    sys.stdout.buffer.flush()

_reader = FrameReader(sys.stdin.buffer)

def _read():
    return _reader.read()

def ok(rid, res): _send({"jsonrpc": "2.0", "id": rid, "result": res})
def err(rid, code, msg): _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}})

# ── SSRF 防护 ──
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

def _resolve_public_address(url: str) -> tuple[str, str] | None:
    """Resolve once, reject mixed/private results, and return a pinned address."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        if not host or parsed.scheme not in ("http", "https"):
            return None
        if host.lower() in _BLOCKED_HOSTS:
            return None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(
                ipaddress.ip_address(result[4][0]) for result in results
            ))
        if not addresses or any(not address.is_global for address in addresses):
            return None
        return host, str(addresses[0])
    except Exception:
        return None


def _is_internal_url(url: str) -> bool:
    """检测 URL 是否未能解析为仅含公网地址的目标（SSRF 防护）"""
    return _resolve_public_address(url) is None


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, *, address, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_address = address

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_address, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, address, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_address = address

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_address, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so every fetched URL receives an SSRF check."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, address):
        super().__init__()
        self._address = address

    def http_open(self, request):
        return self.do_open(_PinnedHTTPConnection, request, address=self._address)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, address):
        super().__init__()
        self._address = address

    def https_open(self, request):
        return self.do_open(
            _PinnedHTTPSConnection, request, address=self._address,
            context=self._context,
        )


def _open_public_url(request: urllib.request.Request, address: str):
    """Fetch one already-validated public URL without following redirects."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirectHandler(),
        _PinnedHTTPHandler(address), _PinnedHTTPSHandler(address),
    )
    return opener.open(request, timeout=15)


def _read_limited(response) -> bytes:
    return response.read(_MAX_RESPONSE_BYTES + 1)[:_MAX_RESPONSE_BYTES]


def fetch(args):
    url = args.get("url", "")
    if not url: return "请提供 URL"
    if not url.startswith(("http://", "https://")): url = "https://" + url
    # SSRF 检查
    resolved = _resolve_public_address(url)
    if resolved is None:
        return "安全限制: 不允许访问内网地址"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with _open_public_url(req, resolved[1]) as resp:
            html = _read_limited(resp).decode("utf-8", errors="replace")
            # 提取文本（去标签）
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:4000] if len(text) > 4000 else text
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return f"抓取失败: {str(e)[:200]}"

def search(args):
    """Bing 搜索"""
    keyword = args.get("keyword", "")
    if not keyword: return "请提供关键词"
    try:
        q = urllib.parse.quote(keyword)
        url = f"https://www.bing.com/search?q={q}&mkt=zh-CN"
        resolved = _resolve_public_address(url)
        if resolved is None:
            return "安全限制: 搜索服务地址不可用"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with _open_public_url(req, resolved[1]) as resp:
            html = _read_limited(resp).decode("utf-8", errors="replace")
            results = []
            for m in re.finditer(r'<li class="b_algo"[^>]*>.*?<h2[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL):
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if title and len(title) > 3:
                    results.append(title)
            if not results:
                return f"未找到关于「{keyword}」的结果"
            return "\n".join(f"- {t}" for t in results[:10])
    except Exception as e:
        return f"搜索失败: {str(e)[:200]}"

H = {"fetch": fetch, "search": search}
T = [
    {"name": "fetch", "description": "抓取网页内容",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string", "description": "网页URL"}}, "required": ["url"]}},
    {"name": "search", "description": "搜索关键词",
     "inputSchema": {"type": "object", "properties": {"keyword": {"type": "string", "description": "搜索关键词"}}, "required": ["keyword"]}},
]

def main():
    """Run the local web-fetch MCP server over standard input/output."""
    while True:
        rid = None
        try:
            m = _read()
            if m is None: break
            rid, method = m.get("id"), m.get("method","")
            if method == "initialize":
                ok(rid, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "web-fetch", "version": "1.0"}, "capabilities": {"tools": {}}})
            elif method == "tools/list":
                ok(rid, {"tools": T})
            elif method == "tools/call":
                p = m["params"]; h = H.get(p["name"])
                if h: ok(rid, {"content": [{"type": "text", "text": h(p.get("arguments",{}))}]})
                else: err(rid, -32601, f"unknown tool: {p['name']}")
            elif method == "notifications/initialized": pass
            else: err(rid, -32601, f"unknown method: {method}")
        except KeyboardInterrupt: break
        except Exception as e:
            err(rid, -32603, "Internal error")
            sys.stderr.write(f"E: {e}\n"); sys.stderr.flush()


if __name__ == "__main__":
    main()
