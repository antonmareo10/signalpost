"""Local proxy for the Signalpost recall metric.

Builderr scores each external field family as 70% company recall + 30% claim recall against the union of
verified findings from every crawler. Locally we approximate that union with our own verified claims plus a
reference set (Builderr's public sample crawl and/or other runs), and we list every disagreement with the
reference so wrong-company risks can be audited by hand.

    python eval/score.py --envelopes out/envelopes.jsonl --reference eval/reference/builderr-sample-100.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signalpost.web import host_of, normalize_social, registrable  # noqa: E402

FAMILIES = ("website", "profiles", "jobs", "activity")


def ours(envelopes: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    found: dict[str, dict[str, set[str]]] = {f: defaultdict(set) for f in FAMILIES}
    for env in envelopes:
        org = env["organisation_number"]
        for claim in env["claims"]:
            field = claim["field"]
            if field in ("official_website", "additional_website"):
                found["website"][org].add(registrable(host_of(claim["value"])))
            elif field == "social_profile":
                normalized = normalize_social(claim.get("normalized_url") or claim["value"])
                if normalized:
                    found["profiles"][org].add(normalized[1].lower())
            elif field in ("job_posting", "careers_page"):
                found["jobs"][org].add(claim["key"])
            elif field == "website_post":
                found["activity"][org].add(claim["key"])
    return found


def reference(path: str) -> dict[str, dict[str, set[str]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    found: dict[str, dict[str, set[str]]] = {f: defaultdict(set) for f in FAMILIES}
    if "rows" in data:
        for row in data["rows"]:
            org = row["organisation_number"]
            if row.get("website"):
                found["website"][org].add(row["website"])
            for handle in row.get("handles", []):
                if handle.get("rights") == "approved":
                    found["profiles"][org].add(handle["url"])
    return found


def score(mine: dict[str, dict[str, set[str]]], pool: dict[str, dict[str, set[str]]], orgs: set[str]) -> dict[str, Any]:
    out = {}
    parts = []
    for family in FAMILIES:
        pool_orgs = {o for o in orgs if pool[family].get(o)}
        pool_claims = {(o, v) for o in pool_orgs for v in pool[family][o]}
        if not pool_orgs:
            out[family] = {"pool_companies": 0}
            continue
        hit_orgs = {o for o in pool_orgs if mine[family].get(o, set()) & pool[family][o]}
        hit_claims = {(o, v) for (o, v) in pool_claims if v in mine[family].get(o, set())}
        company_recall = len(hit_orgs) / len(pool_orgs)
        claim_recall = len(hit_claims) / len(pool_claims)
        family_score = 0.7 * company_recall + 0.3 * claim_recall
        parts.append(family_score)
        out[family] = {"pool_companies": len(pool_orgs), "pool_claims": len(pool_claims), "company_recall": round(company_recall, 3),
                       "claim_recall": round(claim_recall, 3), "family_score": round(family_score, 3)}
    out["recall_points_proxy"] = round(50 * sum(parts) / len(parts), 2) if parts else None
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--reference", action="append", default=[], help="reference JSON (Builderr sample) or other envelopes JSONL")
    args = parser.parse_args()
    envelopes = [json.loads(l) for l in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if l.strip()]
    orgs = {e["organisation_number"] for e in envelopes}
    mine = ours(envelopes)
    refs = []
    for path in args.reference:
        if path.endswith(".jsonl"):
            refs.append(ours([json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]))
        else:
            refs.append(reference(path))
    pool: dict[str, dict[str, set[str]]] = {f: defaultdict(set) for f in FAMILIES}
    for source in [mine] + refs:
        for family in FAMILIES:
            for org, values in source[family].items():
                pool[family][org] |= values
    report: dict[str, Any] = {"companies": len(orgs), "pooled": score(mine, pool, orgs)}
    for index, ref in enumerate(refs):
        report[f"vs_reference_{index}"] = score(mine, ref, orgs)
        disagreements = []
        for family in ("website", "profiles"):
            for org in sorted(orgs):
                a, b = mine[family].get(org, set()), ref[family].get(org, set())
                if a and b and not (a & b):
                    disagreements.append({"family": family, "org": org, "ours": sorted(a), "reference": sorted(b)})
                elif a - b and b:
                    disagreements.append({"family": family, "org": org, "extra_ours": sorted(a - b), "reference": sorted(b)})
        report[f"disagreements_{index}"] = disagreements
        report[f"missed_websites_{index}"] = sorted(f"{o}:{','.join(sorted(ref['website'][o]))}" for o in orgs
                                                    if ref["website"].get(o) and not mine["website"].get(o))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
