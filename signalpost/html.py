"""Small stdlib HTML parser: visible text, metadata, links, feeds and JSON-LD."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "select", "option"}
BLOCK = {"p", "div", "section", "article", "header", "footer", "li", "ul", "ol", "br", "tr", "td", "th", "table", "h1", "h2",
         "h3", "h4", "h5", "h6", "address", "nav", "main", "aside", "form", "dd", "dt", "figure", "figcaption", "blockquote", "hr"}


@dataclass
class Link:
    url: str
    text: str
    in_footer: bool = False
    in_header: bool = False
    context: str = ""


@dataclass
class Page:
    url: str
    title: str = ""
    lang: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    canonical: str = ""
    jsonld: list[Any] = field(default_factory=list)
    text: str = ""
    footer_text: str = ""
    header_text: str = ""
    headings: list[str] = field(default_factory=list)
    times: list[tuple[str, str]] = field(default_factory=list)
    script_count: int = 0

    def evidence_text(self) -> str:
        """Text corpus the verification gate checks claims against (visible text + parsed metadata + links)."""
        lines = [self.text]
        if self.title:
            lines.append(f"[title] {self.title}")
        for key, value in sorted(self.meta.items()):
            lines.append(f"[meta {key}] {value}")
        for link in self.links:
            lines.append(f"[link] {link.url} {link.text}".strip())
        for item in self.jsonld_flat():
            lines.append("[json-ld] " + json.dumps(item, ensure_ascii=False)[:4000])
        return "\n".join(lines)

    def jsonld_flat(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                if "@graph" in value:
                    walk(value["@graph"])
                if "@type" in value:
                    out.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(self.jsonld)
        return out


class _Parser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.page = Page(url=base_url)
        self.stack: list[str] = []
        self.skip_depth = 0
        self.footer_depth = 0
        self.header_depth = 0
        self.chunks: list[str] = []
        self.footer_chunks: list[str] = []
        self.header_chunks: list[str] = []
        self.in_title = False
        self.title_chunks: list[str] = []
        self.current_link: dict[str, Any] | None = None
        self.in_jsonld = False
        self.jsonld_chunks: list[str] = []
        self.heading: list[str] | None = None
        self.time_attr: str | None = None
        self.time_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.page.lang = a["lang"]
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content"):
                self.page.meta.setdefault(key, html.unescape(a["content"]).strip())
            return
        if tag == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href", "")
            if "alternate" in rel and ("rss" in a.get("type", "") or "atom" in a.get("type", "")) and href:
                self.page.feeds.append(urllib.parse.urljoin(self.base, href))
            if rel == "canonical" and href:
                self.page.canonical = urllib.parse.urljoin(self.base, href)
            return
        if tag == "script":
            self.page.script_count += 1
            if "ld+json" in a.get("type", "").lower():
                self.in_jsonld = True
                self.jsonld_chunks = []
        if tag in SKIP and tag != "head":
            self.skip_depth += 1
        marker = f"{a.get('class', '')} {a.get('id', '')}".lower()
        if tag == "footer" or (tag in {"div", "section"} and re.search(r"\bfooter\b|site-footer|page-footer", marker)):
            self.footer_depth += 1
            self.stack.append(tag + "#footer")
        elif tag == "header":
            self.header_depth += 1
            self.stack.append(tag + "#header")
        elif tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "param", "track"}:
            self.stack.append(tag)
        if tag == "title":
            self.in_title = True
        if tag in BLOCK:
            self._emit("\n")
        if tag == "a" and a.get("href"):
            href = a["href"].strip()
            if not href.lower().startswith(("javascript:", "#", "data:")):
                self.current_link = {"url": urllib.parse.urljoin(self.base, href), "text": []}
        if tag in {"h1", "h2"}:
            self.heading = []
        if tag == "time":
            self.time_attr = a.get("datetime") or ""
            self.time_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_jsonld:
            self.in_jsonld = False
            raw = "".join(self.jsonld_chunks).strip()
            try:
                self.page.jsonld.append(json.loads(raw))
            except (ValueError, RecursionError):
                pass
        if tag in SKIP and tag != "head" and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
            self.page.title = re.sub(r"\s+", " ", "".join(self.title_chunks)).strip()
        if tag == "a" and self.current_link is not None:
            text = re.sub(r"\s+", " ", "".join(self.current_link["text"])).strip()
            self.page.links.append(Link(self.current_link["url"], text[:200], self.footer_depth > 0, self.header_depth > 0))
            self.current_link = None
        if tag in {"h1", "h2"} and self.heading is not None:
            text = re.sub(r"\s+", " ", "".join(self.heading)).strip()
            if text:
                self.page.headings.append(text[:200])
            self.heading = None
        if tag == "time":
            text = re.sub(r"\s+", " ", "".join(self.time_chunks)).strip()
            self.page.times.append((self.time_attr or "", text))
            self.time_attr = None
        # unwind stack
        for index in range(len(self.stack) - 1, -1, -1):
            name = self.stack[index]
            base = name.split("#")[0]
            if base == tag:
                for popped in self.stack[index:]:
                    if popped.endswith("#footer") and self.footer_depth:
                        self.footer_depth -= 1
                    if popped.endswith("#header") and self.header_depth:
                        self.header_depth -= 1
                del self.stack[index:]
                break
        if tag in BLOCK:
            self._emit("\n")

    def handle_data(self, data: str) -> None:
        if self.in_jsonld:
            self.jsonld_chunks.append(data)
            return
        if self.in_title:
            self.title_chunks.append(data)
            return
        if self.skip_depth:
            return
        self._emit(data)
        if self.current_link is not None:
            self.current_link["text"].append(data)
        if self.heading is not None:
            self.heading.append(data)
        if self.time_attr is not None:
            self.time_chunks.append(data)

    def _emit(self, data: str) -> None:
        self.chunks.append(data)
        if self.footer_depth:
            self.footer_chunks.append(data)
        if self.header_depth:
            self.header_chunks.append(data)


def _clean(chunks: list[str]) -> str:
    text = "".join(chunks).replace(" ", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_html(text: str, base_url: str) -> Page:
    parser = _Parser(base_url)
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    page = parser.page
    page.text = _clean(parser.chunks)
    page.footer_text = _clean(parser.footer_chunks)
    page.header_text = _clean(parser.header_chunks)
    return page
