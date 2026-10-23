"""Independent evidence audit: re-open every stored snapshot and check that each claim's excerpt is really there.

    python eval/audit_evidence.py --envelopes out/envelopes.jsonl --snapshots out/snapshots

JSON evidence is re-resolved by its JSON pointer; HTML/feed evidence is re-parsed with the same parser and the
excerpt must occur in the page text. NAV job ads are verified against a projection without contact persons
(their raw bodies are deliberately not stored), so they are reported separately.
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signalpost.html import parse_html  # noqa: E402
from signalpost.ledger import canonical_json, resolve_pointer, squash, supports  # noqa: E402
from signalpost.net import _to_text  # noqa: E402


def feed_titles(body: bytes) -> set[str]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        try:
            root = ET.fromstring(_to_text(body, "").lstrip("﻿").encode("utf-8"))
        except ET.ParseError:
            return set()
    titles = set()
    for node in root.iter():
        if node.tag.split("}")[-1] in ("item", "entry"):
            for child in node:
                if child.tag.split("}")[-1] == "title":
                    titles.add(re.sub(r"\s+", " ", html.unescape(child.text or "")).strip())
    return titles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--snapshots", required=True)
    args = parser.parse_args()
    snapshots = Path(args.snapshots)
    outcome: Counter[str] = Counter()
    failures = []
    for line in Path(args.envelopes).read_text(encoding="utf-8").splitlines():
        env = json.loads(line)
        claims_by_ev: dict[str, list[dict]] = {}
        for claim in env["claims"]:
            for ev_id in claim["evidence_ids"]:
                claims_by_ev.setdefault(ev_id, []).append(claim)
        for ev in env["evidence"]:
            if ev["source_class"] == "official_job_vacancy_feed":
                outcome["nav_projection_not_stored_by_design"] += 1
                continue
            path = snapshots / ev["content_sha256"][:2] / f"{ev['content_sha256']}.gz"
            if not path.exists():
                outcome["snapshot_missing"] += 1
                failures.append({"org": env["organisation_number"], "evidence": ev["id"], "why": "snapshot missing", "url": ev["source_url"]})
                continue
            body = gzip.decompress(path.read_bytes())
            raw = _to_text(body, "application/json" if ev["source_class"].startswith("official") else "")
            span = ev["claim_span"]
            ok = False
            if ev["locator"].startswith("/") or (ev["locator"] == "" and ev["source_class"].startswith("official")):
                try:
                    found = resolve_pointer(json.loads(raw.lstrip("﻿")), ev["locator"])
                    text = found if isinstance(found, str) else canonical_json(found)
                    ok = squash(span)[:200] in squash(text) or squash(text) in squash(span) or \
                        all(supports(c["value"], text) for c in claims_by_ev.get(ev["id"], []))
                except Exception:
                    ok = False
            elif ev["locator"] == "final_url":
                ok = True  # the fetch record itself (URL, time, hash) is the evidence
            else:
                if raw.lstrip().lstrip("﻿").startswith(("<?xml", "<rss", "<feed", "<rdf")):
                    # the cited title must be one of the feed's item titles (entities decoded, spaces collapsed)
                    title = span.replace("[feed item]", "").split("|")[0].strip()
                    ok = title[:60] in raw or title in feed_titles(body)
                else:
                    page = parse_html(raw, ev["final_url"] or ev["source_url"])
                    ok = squash(span) in squash(page.evidence_text())
            outcome["verified" if ok else "mismatch"] += 1
            if not ok:
                failures.append({"org": env["organisation_number"], "evidence": ev["id"], "why": "excerpt not found", "url": ev["source_url"],
                                 "span": span[:120]})
    total = sum(outcome.values())
    print(json.dumps({"evidence_items": total, "outcome": dict(outcome),
                      "validity_rate_checked": round(outcome["verified"] / max(1, outcome["verified"] + outcome["mismatch"]), 4),
                      "failures": failures[:25]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
