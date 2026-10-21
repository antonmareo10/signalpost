"""Claims, evidence and the verification gate.

Every published claim points at evidence that was actually fetched in this run. Before a claim
is accepted the gate checks two things in code:

1. the evidence excerpt (``claim_span``) really occurs in the fetched document, and
2. the claimed value is supported by that excerpt (numbers equal, names/tokens present, URLs present).

Anything that fails is dropped into ``rejected`` with a reason instead of being published.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "å": "aa", "Å": "AA", "æ": "ae", "Æ": "AE", "ö": "o", "ä": "a", "ü": "u", "é": "e"})


def fold(text: Any) -> str:
    value = str(text or "").translate(TRANSLIT)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"\s+", " ", value).strip()


def tokens(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def squash(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def short_hash(*parts: Any, size: int = 12) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:size]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    if pointer in ("", "/"):
        return current
    for raw in pointer.lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(pointer)
    return current


NUMBER_RE = re.compile(r"-?\d[\d\s .,]*")


def _numbers_in(text: str) -> set[float]:
    found: set[float] = set()
    for match in NUMBER_RE.findall(text):
        raw = match.strip().replace(" ", " ")
        variants = {raw.replace(" ", "").replace(",", ""), raw.replace(" ", "").replace(".", "").replace(",", "."),
                    raw.replace(" ", "")}
        for variant in variants:
            try:
                found.add(float(variant))
            except ValueError:
                continue
    return found


def supports(value: Any, span: str) -> bool:
    """True when ``span`` (the cited excerpt) contains the claimed value."""
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() in span.lower()
    if isinstance(value, (int, float)):
        return float(value) in _numbers_in(span)
    if isinstance(value, dict):
        return all(supports(v, span) for v in value.values() if v not in (None, "", []))
    if isinstance(value, (list, tuple)):
        return all(supports(v, span) for v in value if v not in (None, ""))
    text = str(value).strip()
    if not text:
        return False
    if text.startswith(("http://", "https://")):
        bare = re.sub(r"^https?://(www\.)?", "", text).rstrip("/").lower()
        return bare in re.sub(r"https?://(www\.)?", "", span.lower())
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        y, m, d = text.split("-")
        return text in span or f"{d}.{m}.{y}" in span or f"{int(d)}.{int(m)}.{y}" in span
    wanted = tokens(text)
    have = set(tokens(span))
    return bool(wanted) and all(token in have for token in wanted)


@dataclass
class Document:
    """One fetched source document as the gate sees it."""
    url: str
    source_class: str
    retrieved_at: str
    sha256: str
    text: str = ""          # normalised visible text (HTML) or canonical JSON
    raw: str = ""           # raw HTML (for attribute evidence such as href)
    data: Any = None        # parsed JSON for pointer evidence
    final_url: str | None = None
    status: int | None = 200
    transform: str | None = None
    _norm_text: str | None = None
    _norm_raw: str | None = None

    @property
    def norm_text(self) -> str:
        if self._norm_text is None:
            self._norm_text = squash(self.text)
        return self._norm_text

    @property
    def norm_raw(self) -> str:
        if self._norm_raw is None:
            self._norm_raw = squash(self.raw)
        return self._norm_raw


@dataclass
class Ledger:
    organisation_number: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)

    # -- evidence --------------------------------------------------------------------------
    def _evidence(self, doc: Document, locator: str, span: str, method: str, effective_at: str | None) -> str:
        ev_id = "ev-" + short_hash(doc.url, doc.sha256, locator, span, size=10)
        if ev_id not in self.evidence:
            self.evidence[ev_id] = {
                "id": ev_id,
                "source_url": doc.url,
                "final_url": doc.final_url if doc.final_url and doc.final_url != doc.url else None,
                "source_class": doc.source_class,
                "retrieved_at": doc.retrieved_at,
                "content_sha256": doc.sha256,
                "locator": locator,
                "claim_span": span,
                "extraction_method": method,
                "effective_at": effective_at,
                "transform": doc.transform,
            }
        return ev_id

    def _accept(self, section: str, field_name: str, value: Any, ev_id: str, *, qualifier: str | None, display: str | None,
                period: str | None, effective_at: str | None, confidence: float, extra: dict[str, Any] | None) -> dict[str, Any] | None:
        key = f"{field_name}|{qualifier or ''}"
        stable_value = canonical_json(value) if not isinstance(value, str) else value
        claim_id = "c-" + short_hash(self.organisation_number, key, stable_value, size=10)
        if claim_id in self.keys:
            # same fact from a second source: attach evidence instead of duplicating the claim
            for claim in self.claims:
                if claim["id"] == claim_id and ev_id not in claim["evidence_ids"]:
                    claim["evidence_ids"].append(ev_id)
            return None
        self.keys.add(claim_id)
        claim = {
            "id": claim_id,
            "section": section,
            "field": field_name,
            "key": key,
            "value": value,
            "display": display if display is not None else (value if isinstance(value, str) else None),
            "availability": "available",
            "confidence": confidence,
            "reporting_period": period,
            "effective_at": effective_at,
            "evidence_ids": [ev_id],
        }
        if extra:
            claim.update(extra)
        self.claims.append(claim)
        return claim

    def json_claim(self, doc: Document, pointer: str, section: str, field_name: str, *, value: Any = None,
                   qualifier: str | None = None, display: str | None = None, period: str | None = None,
                   effective_at: str | None = None, confidence: float = 1.0, method: str = "json_pointer",
                   extra: dict[str, Any] | None = None, span_keys: tuple[str, ...] | None = None) -> dict[str, Any] | None:
        """Claim backed by a JSON pointer into an official API response."""
        try:
            found = resolve_pointer(doc.data, pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            self._reject(field_name, value, f"pointer {pointer} not present in {doc.url}")
            return None
        if found in (None, "", [], {}):
            return None
        claimed = found if value is None else value
        if isinstance(found, dict) and span_keys:
            span = canonical_json({k: found.get(k) for k in span_keys if k in found})
        elif isinstance(found, dict):
            span = canonical_json({k: v for k, v in found.items() if k not in ("children", "_links")})
        else:
            span = found if isinstance(found, str) else canonical_json(found)
        if len(span) > 1500:
            span = span[:1500]
        if not supports(claimed, span):
            self._reject(field_name, claimed, f"value not supported by {pointer}")
            return None
        ev_id = self._evidence(doc, pointer, span, method, effective_at)
        return self._accept(section, field_name, claimed, ev_id, qualifier=qualifier, display=display, period=period,
                            effective_at=effective_at, confidence=confidence, extra=extra)

    def text_claim(self, doc: Document, span: str, section: str, field_name: str, value: Any, *, qualifier: str | None = None,
                   display: str | None = None, period: str | None = None, effective_at: str | None = None,
                   confidence: float = 0.95, method: str = "html_text", locator: str = "visible_text",
                   in_raw: bool = False, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Claim backed by an excerpt of a fetched page (visible text or raw HTML attribute)."""
        span = squash(span)[:500]
        haystack = doc.norm_raw if in_raw else doc.norm_text
        if not span or span not in haystack:
            self._reject(field_name, value, f"excerpt not found in {doc.url}")
            return None
        if not supports(value, span):
            self._reject(field_name, value, f"value not supported by excerpt from {doc.url}")
            return None
        ev_id = self._evidence(doc, locator, span, method, effective_at)
        return self._accept(section, field_name, value, ev_id, qualifier=qualifier, display=display, period=period,
                            effective_at=effective_at, confidence=confidence, extra=extra)

    def _reject(self, field_name: str, value: Any, reason: str) -> None:
        self.rejected.append({"field": field_name, "value": value if isinstance(value, (str, int, float)) else str(value)[:200],
                              "reason": reason})

    def by_field(self, field_name: str) -> list[dict[str, Any]]:
        return [c for c in self.claims if c["field"] == field_name]

    def first(self, field_name: str) -> dict[str, Any] | None:
        found = self.by_field(field_name)
        return found[0] if found else None

    def section_claims(self, section: str) -> list[dict[str, Any]]:
        return [c for c in self.claims if c["section"] == section]


def excerpt_around(text: str, needle: str, width: int = 140) -> str | None:
    """Return a whitespace-normalised excerpt of ``text`` containing ``needle`` (case-sensitive first, then folded)."""
    clean = squash(text)
    index = clean.find(needle)
    if index < 0:
        lowered = clean.lower()
        index = lowered.find(needle.lower())
        if index < 0:
            return None
    start = max(0, index - width // 2)
    end = min(len(clean), index + len(needle) + width // 2)
    # expand to word boundaries
    while start > 0 and clean[start - 1] not in " ":
        start -= 1
    while end < len(clean) and clean[end] not in " ":
        end += 1
    return clean[start:end].strip()
