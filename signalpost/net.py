"""Safe, polite HTTP for the Signalpost agent.

Every outbound request goes through ``Fetcher.get``:
- only http/https on ports 80/443, and every hop (including redirects) must resolve to
  public IP addresses (no SSRF into private networks);
- robots.txt is honoured for crawled websites (official APIs are documented endpoints);
- per-host concurrency is bounded and responses are size-capped;
- every response gets a SHA-256 and a retrieval timestamp, and can be persisted as an
  immutable gzip snapshot keyed by that hash.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "SignalpostResearchAgent/1.0 (+https://builderr.ai/challenges/signalpost; company-research bot)"
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
MAX_REDIRECTS = 6


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class UnsafeURL(ValueError):
    pass


_dns_cache: dict[str, tuple[float, list[str] | None]] = {}
_dns_lock = threading.Lock()


def resolve(host: str) -> list[str] | None:
    with _dns_lock:
        hit = _dns_cache.get(host)
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = sorted({item[4][0] for item in infos})
    except (socket.gaierror, UnicodeError, OSError):
        addresses = None
    with _dns_lock:
        _dns_cache[host] = (time.monotonic(), addresses)
    return addresses


def assert_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeURL(f"scheme not allowed: {parsed.scheme!r}")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeURL("local host blocked")
    if parsed.port not in (None, 80, 443):
        raise UnsafeURL("non-standard port blocked")
    if parsed.username or parsed.password:
        raise UnsafeURL("credentials in URL blocked")
    addresses = resolve(host)
    if not addresses:
        raise UnsafeURL("hostname did not resolve")
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise UnsafeURL("non-public address blocked")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        chain = getattr(req, "redirect_chain", [])
        if len(chain) >= MAX_REDIRECTS:
            raise urllib.error.HTTPError(newurl, 310, "too many redirects", headers, fp)
        assert_public_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.redirect_chain = chain + [newurl]  # type: ignore[attr-defined]
        return new


_ssl_context = ssl.create_default_context()
_opener = urllib.request.build_opener(_SafeRedirect(), urllib.request.HTTPSHandler(context=_ssl_context))


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    content_type: str = ""
    body: bytes = b""
    text: str = ""
    sha256: str = ""
    retrieved_at: str = ""
    elapsed_ms: int = 0
    error: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    blocked: bool = False  # robots.txt or policy refusal

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    def json(self) -> Any:
        return json.loads(self.text) if self.text else None


@dataclass
class Stats:
    requests: int = 0
    bytes: int = 0
    latencies: list[int] = field(default_factory=list)
    by_host: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, host: str, size: int, elapsed: int) -> None:
        with self.lock:
            self.requests += 1
            self.bytes += size
            self.latencies.append(elapsed)
            self.by_host[host] = self.by_host.get(host, 0) + 1


class Fetcher:
    def __init__(self, snapshot_dir: str | Path | None = None, host_concurrency: int = 2,
                 api_concurrency: int = 8, timeout: float = 15.0) -> None:
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else None
        if self.snapshot_dir:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.host_concurrency = host_concurrency
        self.api_concurrency = api_concurrency
        self.api_hosts = {"data.brreg.no", "pam-stilling-feed.nav.no", "query.wikidata.org", "api.tavily.com", "api.anthropic.com"}
        self._host_locks: dict[str, threading.BoundedSemaphore] = {}
        self._locks_guard = threading.Lock()
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._robots_guard = threading.Lock()
        self.stats = Stats()

    # -- concurrency -----------------------------------------------------------------------
    def _semaphore(self, host: str) -> threading.BoundedSemaphore:
        with self._locks_guard:
            if host not in self._host_locks:
                size = self.api_concurrency if host in self.api_hosts else self.host_concurrency
                self._host_locks[host] = threading.BoundedSemaphore(size)
            return self._host_locks[host]

    # -- robots ------------------------------------------------------------------------------
    def robots_allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._robots_guard:
            known = origin in self._robots
            parser = self._robots.get(origin)
        if not known:
            parser = None
            result = self._raw_get(origin + "/robots.txt", accept="text/plain", max_bytes=300_000, timeout=8)
            # RFC 9309: 4xx = no robots policy (allowed); 5xx/unreachable = assume disallowed
            if result.status == 200 and result.text and "<html" not in result.text[:300].lower():
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(result.text.splitlines())
            elif result.status is not None and result.status >= 500:
                parser = urllib.robotparser.RobotFileParser()
                parser.disallow_all = True
            with self._robots_guard:
                self._robots[origin] = parser
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url) and parser.can_fetch("*", url)

    # -- fetch ---------------------------------------------------------------------------------
    def get(self, url: str, *, accept: str = BROWSER_ACCEPT, headers: dict[str, str] | None = None,
            respect_robots: bool = False, max_bytes: int = 3_000_000, timeout: float | None = None,
            retries: int = 1, snapshot: bool = True, data: bytes | None = None) -> FetchResult:
        try:
            assert_public_url(url)
        except UnsafeURL as exc:
            return FetchResult(url, url, None, error=f"unsafe_url: {exc}", retrieved_at=utc_now(), blocked=True)
        if respect_robots and not self.robots_allowed(url):
            return FetchResult(url, url, None, error="robots.txt disallows this URL", retrieved_at=utc_now(), blocked=True)
        attempt = 0
        while True:
            result = self._raw_get(url, accept=accept, headers=headers, max_bytes=max_bytes, timeout=timeout, data=data)
            transient = result.status in (429, 500, 502, 503, 504) or (result.status is None and bool(result.error)
                                                                        and not result.error.startswith("unsafe"))
            if transient and attempt < retries:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            break
        if snapshot and result.body and self.snapshot_dir:
            self._persist(result)
        return result

    def _raw_get(self, url: str, *, accept: str, headers: dict[str, str] | None = None, max_bytes: int,
                 timeout: float | None = None, data: bytes | None = None) -> FetchResult:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        request_headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6",
                           "Accept-Encoding": "gzip, deflate"}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers, data=data)
        request.redirect_chain = []  # type: ignore[attr-defined]
        started = time.monotonic()
        retrieved_at = utc_now()
        status: int | None = None
        body = b""
        final_url = url
        content_type = ""
        error = None
        chain: list[str] = []
        sem = self._semaphore(host)
        with sem:
            try:
                with _opener.open(request, timeout=timeout or self.timeout) as response:
                    status = response.status
                    final_url = response.geturl()
                    content_type = response.headers.get("Content-Type", "")
                    raw = response.read(max_bytes + 1)
                    encoding = (response.headers.get("Content-Encoding") or "").lower()
                    chain = getattr(request, "redirect_chain", [])
                    body = _decode_body(raw[:max_bytes], encoding)
            except urllib.error.HTTPError as exc:
                status = exc.code
                final_url = exc.geturl() or url
                content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
                try:
                    body = _decode_body(exc.read(200_000), (exc.headers.get("Content-Encoding") or "").lower() if exc.headers else "")
                except Exception:
                    body = b""
                error = f"HTTP {exc.code}"
            except UnsafeURL as exc:
                error = f"unsafe_redirect: {exc}"
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError,
                    http.client.HTTPException, OSError, ValueError) as exc:
                reason = getattr(exc, "reason", exc)
                error = f"{type(exc).__name__}: {reason}"[:300]
        elapsed = int((time.monotonic() - started) * 1000)
        self.stats.add(host, len(body), elapsed)
        text = _to_text(body, content_type)
        return FetchResult(url=url, final_url=final_url, status=status, content_type=content_type, body=body, text=text,
                           sha256=hashlib.sha256(body).hexdigest() if body else "", retrieved_at=retrieved_at,
                           elapsed_ms=elapsed, error=error, redirect_chain=chain)

    def _persist(self, result: FetchResult) -> None:
        assert self.snapshot_dir is not None
        persist_snapshot(self.snapshot_dir, result.sha256, result.body)


def persist_snapshot(snapshot_dir: Path, sha256: str, body: bytes) -> None:
    """Write an immutable, content-addressed gzip snapshot. Never raises: evidence storage must not break research."""
    target = snapshot_dir / sha256[:2] / f"{sha256}.gz"
    if target.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{sha256}.{threading.get_ident()}.tmp")
        with gzip.open(tmp, "wb") as handle:
            handle.write(body)
        if target.exists():
            tmp.unlink(missing_ok=True)
        else:
            tmp.replace(target)
    except OSError:
        pass


def _decode_body(raw: bytes, encoding: str, limit: int = 12_000_000) -> bytes:
    """Decompress gzip/deflate bodies, tolerating streams truncated by the size cap (partial output is kept)."""
    if "gzip" not in encoding and "deflate" not in encoding:
        return raw
    for wbits in ((16 + zlib.MAX_WBITS,) if "gzip" in encoding else (zlib.MAX_WBITS, -zlib.MAX_WBITS)):
        try:
            decoder = zlib.decompressobj(wbits)
            return decoder.decompress(raw, limit)
        except zlib.error:
            continue
    return b"" if raw[:2] == b"\x1f\x8b" else raw


def _to_text(body: bytes, content_type: str) -> str:
    if not body:
        return ""
    charset = None
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";")[0].strip().strip('"')
    if not charset:
        head = body[:3000].decode("ascii", "ignore").lower()
        marker = head.find("charset=")
        if marker >= 0:
            charset = head[marker + 8:marker + 30].strip(" \"'").split('"')[0].split("'")[0].split(";")[0].split(">")[0].strip()
    for candidate in (charset, "utf-8", "cp1252"):
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")
