"""Command line: ``python -m signalpost run --organisations batch.jsonl --output out/envelopes.jsonl``."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .agent import SECTIONS, Agent
from .refresh import latest_history, load_previous

FAMILIES = {
    "official_website": "website", "social_profile": "company_profiles", "job_posting": "jobs", "careers_page": "jobs",
    "website_post": "dated_activity", "role": "leadership", "workplace": "workplaces", "revenue": "annual_accounts",
    "legal_name": "identity", "website_description": "description", "public_brand": "brand",
}


def read_inputs(path: str) -> list[str]:
    source = Path(path)
    raw = source.read_bytes()
    if source.suffix == ".gz":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig")
    values: list[Any] = []
    stripped = text.strip()
    if stripped.startswith("["):
        values = json.loads(stripped)
    elif stripped.startswith("{") and "\n" not in stripped:
        body = json.loads(stripped)
        values = body.get("organisation_numbers") or body.get("organisations") or [body]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                values.append(json.loads(line))
            else:
                values.extend(part for part in re.split(r"[,;\t]", line) if part.strip())
    out: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("organisation_number") or value.get("organisasjonsnummer") or value.get("orgnr") or value.get("org") or ""
        digits = re.sub(r"\D", "", str(value))
        if not digits and not str(value).strip():
            continue
        if not digits and re.search(r"[a-z]", str(value), re.I):
            continue  # header row such as "organisation_number"
        out.append(digits if len(digits) == 9 else str(value).strip())
    seen: set[str] = set()
    unique = []
    for org in out:
        if org not in seen:
            seen.add(org)
            unique.append(org)
    return unique


def read_bulk(path: str | None, wanted: set[str]) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    source = Path(path)
    opener = gzip.open if source.suffix == ".gz" else open
    found: dict[str, dict[str, Any]] = {}
    with opener(source, "rt", encoding="utf-8", errors="replace") as handle:  # type: ignore[operator]
        first = handle.readline()
        handle.seek(0)
        if first.lstrip().startswith("{"):
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                org = str(row.get("organisation_number") or row.get("organisasjonsnummer") or "")
                if org in wanted:
                    found[org] = row
        else:
            reader = csv.DictReader(handle)
            for row in reader:
                org = row.get("organisasjonsnummer") or row.get("Organisasjonsnummer") or ""
                if org in wanted:
                    found[org] = {"organisation_number": org, "name": row.get("navn") or row.get("Navn"), "raw": row}
            # keep scanning cost bounded: the CSV is read once
    return found


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def failed_envelope(org: str, run_id: str, reason: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"schema": "signalpost.envelope/1", "organisation_number": org, "status": "failed", "legal_name": None, "public_brand": None,
            "run": {"run_id": run_id, "agent_version": __version__, "started_at": now, "completed_at": now, "terminal_status": "failed"},
            "sections": {s: {"state": "failed", "claims": 0, "note": reason} for s in SECTIONS},
            "summary": {"text": "", "sentences": [], "unknowns": []}, "claims": [], "evidence": [], "changes": [],
            "refresh": {}, "discovery": [], "rejected_claims": [], "errors": [{"error": reason}],
            "operations": {"runtime_ms": 0, "third_party_cost_usd": 0}}


def build_report(envelopes: list[dict[str, Any]], agent: Agent, args: argparse.Namespace, started: float, inputs: list[str]) -> dict[str, Any]:
    n = len(envelopes)
    status = Counter(e["status"] for e in envelopes)
    sections = {s: dict(Counter(e["sections"][s]["state"] for e in envelopes)) for s in SECTIONS}
    family_companies: Counter[str] = Counter()
    family_claims: Counter[str] = Counter()
    for env in envelopes:
        seen = set()
        for claim in env["claims"]:
            family = FAMILIES.get(claim["field"])
            if family:
                family_claims[family] += 1
                seen.add(family)
        for family in seen:
            family_companies[family] += 1
    runtimes = sorted(e["operations"].get("runtime_ms", 0) for e in envelopes)
    latencies = sorted(agent.fetcher.stats.latencies)
    orgs = [e["organisation_number"] for e in envelopes]
    validation = {
        "exact_expected_count": n == (args.expected_count or len(inputs)),
        "one_envelope_per_input": orgs == inputs,
        "unique_organisation_numbers": len(set(orgs)) == n,
        "all_states_terminal": all(e["status"] in {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
                                   and all(sec["state"] in {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
                                           for sec in e["sections"].values()) for e in envelopes),
        "every_claim_has_evidence": all(all(c["evidence_ids"] for c in e["claims"]) for e in envelopes),
        "every_evidence_has_source_time_hash": all(all(ev.get("source_url") and ev.get("retrieved_at") and ev.get("content_sha256")
                                                       for ev in e["evidence"]) for e in envelopes),
    }
    cost = round(sum(e["operations"].get("third_party_cost_usd", 0) for e in envelopes), 4)
    return {
        "run_id": args.run_id, "agent_version": __version__, "started_at": agent.started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "wall_clock_seconds": round(time.monotonic() - started, 1), "inputs": len(inputs), "emitted_envelopes": n,
        "status_counts": dict(status), "section_states": sections,
        "coverage": {family: {"companies": family_companies[family], "company_share": round(family_companies[family] / n, 3) if n else 0,
                              "claims": family_claims[family]} for family in sorted(set(FAMILIES.values()))},
        "operations": {"requests": agent.fetcher.stats.requests, "bytes": agent.fetcher.stats.bytes,
                       "p50_request_ms": latencies[len(latencies) // 2] if latencies else None,
                       "p95_request_ms": latencies[int(len(latencies) * 0.95) - 1] if latencies else None,
                       "p50_company_ms": runtimes[n // 2] if n else None, "p95_company_ms": runtimes[max(0, int(n * 0.95) - 1)] if n else None,
                       "third_party_cost_usd": cost, "search_provider": agent.search.name if agent.search else None,
                       "search_calls": agent.search.calls if agent.search else 0,
                       "nav_feed": {"state": agent.nav.state, "pages": agent.nav.feed_pages, "active_ads": len(agent.nav.active),
                                    "matched_companies": len(agent.nav.by_org), "error": agent.nav.error},
                       "top_hosts": dict(Counter(agent.fetcher.stats.by_host).most_common(8))},
        "validation": {"passed": all(validation.values()), "checks": validation},
    }


def cmd_run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    inputs = read_inputs(args.organisations)
    if args.expected_count and len(inputs) != args.expected_count:
        print(f"warning: expected {args.expected_count} organisations, received {len(inputs)} unique inputs", file=sys.stderr)
    valid = [org for org in inputs if re.fullmatch(r"\d{9}", org)]
    run_id = args.run_id or datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    args.run_id = run_id
    out = Path(args.output)
    history_dir = Path(args.history_dir) if args.history_dir else out.parent / "history"
    previous_path = args.previous or latest_history(history_dir, run_id)
    previous = load_previous(previous_path)
    bulk = read_bulk(args.bulk, set(valid))
    agent = Agent(run_id=run_id, snapshot_dir=args.snapshots or str(out.parent / "snapshots"), cache_dir=args.cache_dir,
                  workers=args.workers, time_budget_s=args.time_budget_minutes * 60, guess_domains=not args.no_guess,
                  nav_mode=args.nav_mode, use_search=not args.no_search, max_search=args.max_search,
                  log=lambda msg: print(msg, file=sys.stderr, flush=True))
    agent._errors = {}
    print(f"signalpost {__version__}: {len(inputs)} inputs, run {run_id}, previous={previous_path or 'none'}", file=sys.stderr)
    envelopes_by_org: dict[str, dict[str, Any]] = {}
    try:
        for envelope in agent.run(valid, bulk=bulk, previous=previous):
            envelopes_by_org[envelope["organisation_number"]] = envelope
    except Exception as exc:  # last-resort guarantee: still emit one envelope per input
        print(f"batch error: {type(exc).__name__}: {exc}", file=sys.stderr)
    envelopes = [envelopes_by_org.get(org) or failed_envelope(org, run_id, "invalid organisation number" if org not in valid
                                                               else "agent error before this company finished") for org in inputs]
    write_jsonl(out, envelopes)
    if args.profiles_output:
        write_jsonl(Path(args.profiles_output), envelopes)
    history_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, history_dir / f"{run_id}.jsonl")
    report = build_report(envelopes, agent, args, started, inputs)
    report["previous_envelopes"] = Path(previous_path).name if previous_path else None
    report_path = Path(args.report) if args.report else out.with_name("run-report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.no_site:
        from .site import build_site
        site_dir = Path(args.site) if args.site else out.parent / "site"
        build_site(envelopes, site_dir, report)
        print(f"viewer: {site_dir / 'index.html'}", file=sys.stderr)
    print(json.dumps({k: report[k] for k in ("emitted_envelopes", "status_counts", "coverage", "validation")}, indent=1), file=sys.stderr)
    return 0 if report["validation"]["passed"] else 1


def cmd_site(args: argparse.Namespace) -> int:
    from .site import build_site
    envelopes = [json.loads(line) for line in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if line.strip()]
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if args.report else {}
    build_site(envelopes, Path(args.site), report)
    print(Path(args.site) / "index.html")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalpost", description="Signalpost company-research agent for Norwegian organisation numbers")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="research a batch and write one envelope per input")
    run.add_argument("--organisations", "--input", required=True, help="JSON / JSONL / TXT / CSV with organisation numbers")
    run.add_argument("--output", default="out/envelopes.jsonl")
    run.add_argument("--report", default=None)
    run.add_argument("--bulk", default=None, help="optional frozen Brreg snapshot (CSV or JSONL[.gz]) used as identity fallback")
    run.add_argument("--run-id", default=None)
    run.add_argument("--expected-count", type=int, default=None)
    run.add_argument("--previous", default=None, help="previous envelopes JSONL (default: latest file in <output dir>/history)")
    run.add_argument("--history-dir", default=None)
    run.add_argument("--snapshots", default=None, help="raw evidence snapshot directory (default: <output dir>/snapshots)")
    run.add_argument("--cache-dir", default=os.environ.get("SIGNALPOST_CACHE", ".cache"))
    run.add_argument("--site", default=None, help="static viewer directory (default: <output dir>/site)")
    run.add_argument("--no-site", action="store_true")
    run.add_argument("--workers", type=int, default=int(os.environ.get("SIGNALPOST_WORKERS", "24")))
    run.add_argument("--time-budget-minutes", type=float, default=float(os.environ.get("SIGNALPOST_TIME_BUDGET_MINUTES", "55")))
    run.add_argument("--no-guess", action="store_true", help="disable domain guessing from the legal name")
    run.add_argument("--no-search", action="store_true", help="disable the optional search provider even if a key is set")
    run.add_argument("--max-search", type=int, default=int(os.environ.get("SIGNALPOST_MAX_SEARCH", "400")))
    run.add_argument("--nav-mode", choices=("names", "full"), default=os.environ.get("SIGNALPOST_NAV_MODE", "names"))
    # accepted for drop-in compatibility with the starter kit's batch command line
    run.add_argument("--profiles-output", default=None, help="also write the envelopes here (starter-kit compatibility)")
    run.add_argument("--checkpoint-every", type=int, default=None, help=argparse.SUPPRESS)
    run.add_argument("--resume", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--modules", default=None, help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)
    site = sub.add_parser("site", help="rebuild the static viewer from an envelopes file")
    site.add_argument("--envelopes", required=True)
    site.add_argument("--report", default=None)
    site.add_argument("--site", default="out/site")
    site.set_defaults(func=cmd_site)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
