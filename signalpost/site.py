"""Static viewer for a batch of envelopes: find, compare and verify company information on desktop and mobile.

``site/index.html`` carries a compact index of every company (search, filters, cards, comparison). Each company's full
profile (summary with numbered sources, every claim, the evidence excerpts) is embedded in the page when the batch is
small, or written to ``site/data/<org>.js`` and loaded when the profile is opened, so a 1,000-company batch still opens
at once on a phone. Both ways work from disk (file://) and from any static host, because profiles load through a
``<script>`` tag rather than fetch(). No server, no external requests, no keys.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from .ledger import SOURCE_LABELS

SPAN_LIMIT = 260
INLINE_LIMIT_BYTES = 1_500_000  # above this, profiles go to data/<org>.js and load on demand
SECTION_ORDER = ("identity", "accounts", "people", "website", "hiring", "activity")
STATE_CODES = {"available": "a", "not_available": "n", "blocked": "b", "ambiguous": "m", "failed": "f", "not_applicable": "x"}
CLAIM_KEYS = ("url", "platform", "role_code", "account_type", "year", "location", "expires", "municipality", "employees",
              "proof_kind", "carried_forward_from", "event_date", "valid_to", "changed_labels", "code", "classification",
              "document_type")
DATA_FILE = re.compile(r"^(\d{9}|x[0-9a-f]{12})\.js$")


def _project(env: dict[str, Any]) -> dict[str, Any]:
    """Everything one profile page needs. Source documents are listed once and evidence points at them by index."""
    claims = []
    used_evidence: set[str] = set()
    for c in env.get("claims", []):
        item = {"i": c["id"], "f": c["field"], "s": c["section"], "d": c.get("display") or _short(c.get("value")),
                "e": c.get("evidence_ids", []), "t": c.get("effective_at") or c.get("event_date"), "p": c.get("reporting_period")}
        for key in CLAIM_KEYS:
            if c.get(key) not in (None, "", []):
                item[key] = c[key]
        if isinstance(c.get("value"), (int, float)) and not isinstance(c.get("value"), bool):
            item["v"] = c["value"]
        elif c["field"] in ("official_website", "additional_website", "careers_page", "social_profile"):
            item["v"] = c.get("normalized_url") or c.get("value")
        elif c["field"] in ("industry_en", "secondary_industry_en", "annual_accounts_copy", "accounts_filed_event"):
            item["v"] = c.get("value")
        claims.append(item)
        used_evidence.update(item["e"])
    docs: list[list[Any]] = []
    doc_index: dict[tuple[Any, ...], int] = {}
    evidence = {}
    for ev in env.get("evidence", []):
        if ev["id"] not in used_evidence:
            continue
        key = (ev.get("source_url"), ev.get("source_class"), ev.get("retrieved_at"), (ev.get("content_sha256") or "")[:16])
        if key not in doc_index:
            doc_index[key] = len(docs)
            docs.append(list(key))
        span = ev.get("claim_span") or ""
        item = {"d": doc_index[key], "l": ev.get("locator"), "m": ev.get("extraction_method"),
                "x": span if len(span) <= SPAN_LIMIT else span[:SPAN_LIMIT] + "…"}
        if ev.get("transform"):
            item["tf"] = ev["transform"]
        evidence[ev["id"]] = item
    summary = env.get("summary") or {}
    return {
        "o": env["organisation_number"], "n": env.get("legal_name") or "(unknown)", "b": env.get("public_brand"), "st": env.get("status"),
        "sec": {k: {"s": v.get("state"), "n": v.get("note"), "c": v.get("claims")} for k, v in (env.get("sections") or {}).items()},
        "sum": [{"t": s["text"], "c": s.get("claim_ids", []), "p": s.get("part"), "n": s.get("sources", [])} for s in summary.get("sentences", [])],
        "src": [{"n": s["n"], "u": s["url"], "c": s.get("source_class"), "r": s.get("retrieved_at")} for s in summary.get("sources", [])],
        "sig": [{"t": s["text"], "c": s.get("claim_ids", []), "k": s.get("tone", "info")} for s in summary.get("signals", [])],
        "unk": summary.get("unknowns", []),
        "unkd": summary.get("unknown_detail", []),
        "cl": claims, "ev": evidence, "dc": docs,
        "ch": [{"t": c["type"], "m": c["materiality"], "d": c["description"], "c": c.get("claim_ids", [])} for c in env.get("changes", [])],
        "run": {"id": (env.get("run") or {}).get("run_id"), "at": (env.get("run") or {}).get("completed_at"),
                "prev": (env.get("refresh") or {}).get("previous_run_id"), "prevat": (env.get("refresh") or {}).get("previous_completed_at")},
        "err": [e.get("error") for e in env.get("errors", [])][:5],
    }


def _index_row(env: dict[str, Any]) -> dict[str, Any]:
    """The few fields the list, the filters, the search and the comparison picker need for every company."""
    claims = env.get("claims", [])

    def first(field: str) -> dict[str, Any] | None:
        return next((c for c in claims if c["field"] == field), None)

    def count(field: str) -> int:
        return sum(1 for c in claims if c["field"] == field)

    revenue = [c for c in claims if c["field"] == "revenue" and isinstance(c.get("value"), (int, float))]
    group = [c for c in revenue if c.get("account_type") == "KONSERN"]
    rows = sorted(group or revenue, key=lambda c: str(c.get("year") or ""), reverse=True)
    latest = rows[0] if rows else None
    change = None
    if latest and len(rows) > 1 and rows[1]["value"]:
        change = round((latest["value"] - rows[1]["value"]) / abs(rows[1]["value"]) * 100, 1)
    industry_en, industry, municipality = first("industry_en"), first("industry"), first("municipality")
    website, employees, founded = first("official_website"), first("employees_registered"), first("founded")
    sections = env.get("sections") or {}
    names = [c.get("display", "").split(": ", 1)[-1] for c in claims if c["field"] == "role"]
    names += [str(c.get("value")) for c in claims if c["field"] == "former_name"]
    names += [str(c.get("display") or "") for c in claims if c["field"] == "workplace"]
    org = env["organisation_number"]
    keywords = " ".join(dict.fromkeys(filter(None, [
        re.sub(r"(\d{3})(?=\d)", r"\1 ", org), (industry or {}).get("display") or _short((industry or {}).get("value")),
        (industry or {}).get("value", {}).get("code") if isinstance((industry or {}).get("value"), dict) else None,
        _host(website.get("normalized_url") or website.get("value")) if website else None, *names])))
    summary = env.get("summary") or {}
    return {
        "o": org, "n": env.get("legal_name") or "(unknown)", "b": env.get("public_brand"),
        "m": str((municipality or {}).get("value") or "").title() or None,
        "i": (industry_en or {}).get("value") or ((industry or {}).get("value") or {}).get("description") if (industry_en or industry) else None,
        "ic": ((industry or {}).get("value") or {}).get("code") if industry and isinstance(industry.get("value"), dict) else None,
        "fy": str((founded or {}).get("value") or "")[:4] or None,
        "e": (employees or {}).get("value"),
        "r": [latest["value"], latest.get("year"), 1 if latest.get("account_type") == "KONSERN" else 0] if latest else None,
        "rc": change,
        "w": _host(website.get("normalized_url") or website.get("value")) if website else None,
        "j": count("job_posting"), "cp": count("careers_page"), "p": count("social_profile"), "po": count("website_post"),
        "s": "".join(STATE_CODES.get((sections.get(k) or {}).get("state") or "not_available", "n") for k in SECTION_ORDER),
        "g": [[s["text"], s.get("tone", "info")] for s in (summary.get("signals") or [])[:3]],
        "ch": sum(1 for c in env.get("changes", []) if c.get("materiality") in ("high", "medium")),
        "pv": 1 if (env.get("refresh") or {}).get("previous_run_id") else 0,
        "nc": len(claims), "k": keywords,
    }


def _static_list(envelopes: list[dict[str, Any]]) -> str:
    """Plain HTML list of every company with its "In brief" overview. The script replaces it at once; it is what a reader
    without JavaScript (or a text-only fetch of the page) gets."""
    items = []
    for env in envelopes:
        org = html.escape(env["organisation_number"])
        summary = env.get("summary") or {}
        overview = summary.get("overview") or " ".join((summary.get("parts") or {}).get("what_it_does", [])[:1])
        items.append(f'<li><a href="#/c/{org}">{html.escape(env.get("legal_name") or "(unknown)")}</a> (org. {org}): '
                     f'{html.escape(overview)}</li>')
    return ("<section id=\"static\"><h1>Companies</h1><p>Each line is the company's overview, built only from cited facts. "
            "Open a company for every fact with its source and retrieval date (needs JavaScript).</p><ol>" + "".join(items) + "</ol></section>")


def _host(url: Any) -> str:
    return re.sub(r"^https?://(www\.)?", "", str(url or "")).rstrip("/")


def _short(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{v}" for v in value.values() if v not in (None, ""))[:200]
    return str(value)[:200]


def _file_key(org: str) -> str:
    return org if re.fullmatch(r"\d{9}", org or "") else "x" + hashlib.sha1(str(org).encode("utf-8")).hexdigest()[:12]


def build_site(envelopes: list[dict[str, Any]], site_dir: Path, report: dict[str, Any] | None = None,
               inline_limit: int = INLINE_LIMIT_BYTES) -> Path:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    details = [_project(e) for e in envelopes]
    index = [_index_row(e) for e in envelopes]
    blobs = [json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in details]
    inline = sum(len(b.encode("utf-8")) for b in blobs) <= inline_limit
    data_dir = site_dir / "data"
    if data_dir.is_dir():  # profiles of an earlier build of this viewer (only our own file names are removed)
        for stale in data_dir.iterdir():
            if stale.is_file() and DATA_FILE.match(stale.name):
                stale.unlink()
    meta = {"run": (report or {}).get("run_id"), "completed": (report or {}).get("completed_at"), "count": len(envelopes),
            "version": (report or {}).get("agent_version"), "sources": SOURCE_LABELS, "profiles": "inline" if inline else "files"}
    payload: dict[str, Any] = {"meta": meta, "companies": index}
    if inline:
        payload["details"] = {d["o"]: d for d in details}
    else:
        data_dir.mkdir(exist_ok=True)
        for row, blob in zip(index, blobs):
            row["f"] = _file_key(row["o"])
            (data_dir / f"{row['f']}.js").write_text(f"SP_DETAIL({json.dumps(row['o'])},{blob});\n", encoding="utf-8", newline="\n")
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = (TEMPLATE.replace("__DATA__", text).replace("__TITLE__", html.escape(f"Signalpost · {len(envelopes)} companies"))
            .replace("__STATIC__", _static_list(envelopes)))
    target = site_dir / "index.html"
    target.write_text(page, encoding="utf-8", newline="\n")
    return target


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<script>document.documentElement.classList.add("js")</script>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="Evidence-first company profiles for Norwegian organisation numbers. Find, compare and verify: every fact links to its source and retrieval date.">
<style>
:root{--bg:#f5f6f8;--panel:#fff;--ink:#121720;--muted:#556070;--line:#dde2e8;--accent:#0b5cad;--accent-ink:#fff;--ok:#11703b;--warn:#8a5300;--bad:#b42318;--chip:#edf2f9;--soft:#f3f6fa;--hl:#fff4cc;--shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.07)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1217;--panel:#151a21;--ink:#e8ecf1;--muted:#a3adba;--line:#2b333d;--accent:#6aadff;--accent-ink:#0b1220;--ok:#4cc98b;--warn:#e7ad48;--bad:#ff8577;--chip:#1c2532;--soft:#111821;--hl:#3a3216;--shadow:none}}
:root[data-theme=dark]{--bg:#0e1217;--panel:#151a21;--ink:#e8ecf1;--muted:#a3adba;--line:#2b333d;--accent:#6aadff;--accent-ink:#0b1220;--ok:#4cc98b;--warn:#e7ad48;--bad:#ff8577;--chip:#1c2532;--soft:#111821;--hl:#3a3216;--shadow:none}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-text-size-adjust:100%}
a{color:var(--accent)}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:6px}
h1,h2,h3{text-wrap:balance}
header.top{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
.bar{display:flex;gap:12px;align-items:center;padding:10px 0;flex-wrap:wrap}
.brand{font-weight:750;letter-spacing:-.02em;font-size:18px;display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--ink)}
.brand svg{width:22px;height:22px}
.search{flex:1 1 260px;display:flex;position:relative}
.search input{width:100%;padding:10px 64px 10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font-size:16px;min-height:44px}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);font:12px/1 ui-monospace,monospace;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:3px 6px;background:var(--panel)}
.meta{color:var(--muted);font-size:13px}
.filters{display:flex;gap:8px;flex-wrap:wrap;padding:0 0 10px;align-items:center}
.chipbtn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer;min-height:36px}
.chipbtn[aria-pressed=true]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.chipbtn .cnt{font-variant-numeric:tabular-nums;font-weight:650}
select.sort{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 10px;font-size:13px;min-height:36px}
main{padding:16px 0 104px}
.listhead{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap;margin:4px 0 10px}
.listhead h1{font-size:20px;margin:0;letter-spacing:-.01em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px;min-width:0}
.card h2{margin:0;font-size:16px;line-height:1.3;overflow-wrap:anywhere}
.card h2 a{text-decoration:none;color:var(--ink)}.card h2 a:hover{color:var(--accent);text-decoration:underline}
.sub{color:var(--muted);font-size:13px;overflow-wrap:anywhere;margin:0}
.kpis{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--muted)}.kpis b{font-size:15px;display:block;color:var(--ink)}.kpis b.none{color:var(--muted);font-weight:500}
.states{display:flex;gap:6px;flex-wrap:wrap;margin:0;padding:0;list-style:none}
.st{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap;display:inline-flex;gap:4px;align-items:center;background:var(--panel)}
.st i{font-style:normal;font-weight:700}
.st.available{color:var(--ok);border-color:var(--ok)}
.st.ambiguous,.st.blocked{color:var(--warn);border-color:var(--warn)}
.st.failed{color:var(--bad);border-color:var(--bad)}
.sigs{display:flex;gap:6px;flex-wrap:wrap}
.sig{font-size:12.5px;padding:3px 9px;border-radius:8px;background:var(--chip);color:var(--ink);border:1px solid transparent;display:inline-flex;align-items:center;gap:4px}
.sig.up{border-color:var(--ok)}.sig.down{border-color:var(--warn)}.sig.risk{border-color:var(--bad)}
.cardfoot{display:flex;justify-content:space-between;align-items:center;margin-top:auto;gap:8px;flex-wrap:wrap}
label.cmp{display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer;min-height:40px}
label.cmp input{width:18px;height:18px}
.btn{border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);border-radius:10px;padding:8px 14px;font-weight:600;cursor:pointer;min-height:40px;text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-size:14px}
.btn.ghost{background:transparent;color:var(--accent)}
.btn.small{min-height:32px;padding:4px 10px;font-size:13px}
.more{display:flex;justify-content:center;margin:16px 0}
.tray{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);box-shadow:0 -4px 16px rgba(0,0,0,.08);padding:10px 0 calc(10px + env(safe-area-inset-bottom));display:none;z-index:6}
.tray .wrap{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);background:var(--ink);color:var(--panel);padding:8px 14px;border-radius:10px;font-size:14px;z-index:12;opacity:0;pointer-events:none;transition:opacity .15s}
.toast.show{opacity:1}
.empty{padding:40px 16px;text-align:center;color:var(--muted)}
.crumbs{margin:0 0 10px;font-size:14px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow)}
.hero h1{margin:0 0 4px;font-size:clamp(21px,3vw,30px);letter-spacing:-.02em;line-height:1.2;overflow-wrap:anywhere}
.lede{margin:14px 0 4px;padding:12px 14px;border-left:4px solid var(--accent);background:var(--soft);border-radius:0 10px 10px 0}
.lede h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 4px;font-weight:700}
.lede p{margin:0;font-size:16.5px;line-height:1.65;max-width:85ch}
.parts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 22px;margin-top:14px}
.part{min-width:0}.part.wide{grid-column:1/-1}
.part h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 4px;font-weight:700}
.part p{margin:0 0 6px;font-size:15px;line-height:1.6;max-width:80ch}
@media (max-width:860px){.parts{grid-template-columns:1fr}}
sup.cite{font-size:11px;margin-left:3px;line-height:0;white-space:nowrap;vertical-align:baseline;position:relative;top:-.4em}
sup.cite button{border:0;background:var(--chip);color:var(--accent);border-radius:6px;padding:0 5px;cursor:pointer;font:inherit;font-weight:650;min-width:24px;height:24px;line-height:24px}
sup.cite button:hover{text-decoration:underline}
.jump{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 0;padding:0;list-style:none}
.jump button{border:1px solid var(--line);background:var(--panel);color:var(--accent);border-radius:999px;padding:4px 10px;font-size:13px;cursor:pointer;min-height:32px}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;align-items:center}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:860px){.cols{grid-template-columns:1fr}}
section.box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);min-width:0;scroll-margin-top:120px}
section.box h2{font-size:15px;margin:0 0 8px;display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}
section.box h3{font-size:13px;margin:12px 0 6px;color:var(--muted);font-weight:650}
.note{color:var(--muted);font-size:13px;margin:4px 0 0}
dl.facts{display:grid;grid-template-columns:minmax(110px,36%) 1fr;gap:6px 12px;margin:0}
dl.facts dt{color:var(--muted);font-size:13px}dl.facts dd{margin:0;overflow-wrap:anywhere}
ul.plain{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
ul.plain li{overflow-wrap:anywhere}
ul.docs{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:6px}
ul.docs a{display:inline-block;padding:3px 9px;border:1px solid var(--line);border-radius:8px;text-decoration:none;font-size:13px}
ol.tl{list-style:none;margin:0;padding:0 0 0 14px;border-left:2px solid var(--line);display:flex;flex-direction:column;gap:8px}
ol.tl li{position:relative;overflow-wrap:anywhere}ol.tl li::before{content:"";position:absolute;left:-20px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--panel);border:2px solid var(--accent)}
ol.tl time{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12.5px;display:block}
ol.srcs{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:8px;counter-reset:none}
ol.srcs li{display:grid;grid-template-columns:32px 1fr;gap:8px;align-items:start;overflow-wrap:anywhere}
ol.srcs .num{display:inline-flex;justify-content:center;align-items:center;min-width:26px;height:24px;border-radius:6px;background:var(--chip);color:var(--accent);font-weight:700;font-size:12.5px}
ol.srcs li.flash{background:var(--hl);border-radius:8px}
.tbl{width:100%;border-collapse:collapse;font-size:13.5px}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.tblwrap:focus-visible{outline:3px solid var(--accent)}
.src{font-size:12px;color:var(--muted)}
.bars{display:flex;align-items:flex-end;gap:8px;height:64px;margin:6px 0 20px;max-width:320px}
.bars div{flex:1;background:var(--accent);border-radius:4px 4px 0 0;min-height:2px;position:relative}
.bars div.neg{background:var(--bad)}
.bars span{position:absolute;bottom:-18px;left:0;right:0;text-align:center;font-size:11px;color:var(--muted)}
.drawer{position:fixed;right:0;top:0;bottom:0;width:min(560px,100%);background:var(--panel);border-left:1px solid var(--line);box-shadow:-8px 0 24px rgba(0,0,0,.12);transform:translateX(105%);transition:transform .18s ease;z-index:10;display:flex;flex-direction:column;visibility:hidden}
.drawer.open{transform:none;visibility:visible}
.drawer .dh{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);gap:8px}
.drawer h2{font-size:16px;margin:0}
.drawer .body{padding:14px 16px calc(14px + env(safe-area-inset-bottom));overflow:auto}
.ev{border:1px solid var(--line);border-radius:12px;padding:10px;margin:0 0 10px}
.ev blockquote{display:block;background:var(--chip);border-radius:8px;padding:8px;margin:6px 0;font-size:13px;overflow-wrap:anywhere;white-space:pre-wrap}
.ev .k{color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}
.ev .ok{color:var(--ok);font-size:12.5px;font-weight:600}
.ev .row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.ev .when{display:flex;gap:6px 14px;flex-wrap:wrap;font-size:13px;margin:4px 0}
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.25);opacity:0;pointer-events:none;transition:opacity .18s;z-index:9}
.scrim.open{opacity:1;pointer-events:auto}
.cmpbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
.cmpbar input{flex:1 1 240px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);font-size:16px;min-height:40px}
.suggest{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0 0 12px;font-size:13px;color:var(--muted)}
.cmpt{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.cmpt th,.cmpt td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;font-size:14px;overflow-wrap:anywhere;min-width:170px;background:var(--panel)}
.cmpt tbody th{color:var(--muted);font-weight:600;min-width:118px;position:sticky;left:0;z-index:1;box-shadow:1px 0 0 var(--line)}
.cmpt thead th:first-child{position:sticky;left:0;z-index:2}
.cmpt td.diff{background:var(--soft)}
.cmpt td .note{margin:0}
.cmpt .ico{display:inline-flex;vertical-align:middle}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px}
.change{padding-left:8px;border-left:3px solid var(--line)}.change.high{border-left-color:var(--bad)}.change.medium{border-left-color:var(--warn)}
details.help{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 12px}
details.help summary{cursor:pointer;font-weight:600}
details.help p{margin:8px 0 0;color:var(--muted);font-size:14px;max-width:90ch}
details.legend summary{cursor:pointer;color:var(--accent);font-size:13px;margin-top:8px}
dl.legend{display:grid;grid-template-columns:max-content 1fr;gap:6px 12px;margin:8px 0 0;font-size:13.5px;align-items:start}
dl.legend dd{margin:0;color:var(--ink)}
.loading{color:var(--muted)}
.skel{height:14px;border-radius:6px;background:linear-gradient(90deg,var(--chip),var(--soft),var(--chip));background-size:200% 100%;animation:sk 1.2s linear infinite;margin:8px 0;max-width:600px}
@keyframes sk{to{background-position:-200% 0}}
footer.foot{color:var(--muted);font-size:12.5px;padding:24px 0}
@media (prefers-reduced-motion:reduce){.drawer,.scrim,.toast{transition:none}.skel{animation:none}}
#view:focus{outline:none}
.js #static{display:none}#static ol{padding-left:22px}#static li{margin:0 0 8px}
@media (max-width:640px){header.top{position:static}.bar .meta{display:none}.search kbd{display:none}.search input{padding-right:12px}.filters{flex-wrap:nowrap;overflow-x:auto;padding-bottom:12px;scrollbar-width:none}.filters>*{flex:0 0 auto}.hero{padding:14px}.lede p{font-size:16px}.cmpt th,.cmpt td{min-width:150px}dl.facts{grid-template-columns:1fr;gap:0 0}dl.facts dt{margin-top:6px}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
a.sr:focus{position:fixed;left:12px;top:12px;width:auto;height:auto;clip:auto;z-index:20;background:var(--panel);color:var(--accent);padding:8px 12px;border-radius:8px;border:2px solid var(--accent)}
@media print{header.top,.tray,.drawer,.scrim,label.cmp,.btn,.cardfoot,.jump,.actions{display:none!important}body{background:#fff}}
</style>
</head>
<body>
<a class="sr" href="#view">Skip to content</a>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="#/" aria-label="Signalpost: all companies"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>Signalpost</a>
    <form class="search" role="search" id="searchform" aria-label="Search companies"><label class="sr" for="q">Search companies by name, organisation number, brand, place, person or industry</label>
      <input id="q" type="search" placeholder="Name or org. number (also brand, place, person, industry)" autocomplete="off" enterkeyhint="search" aria-describedby="searchhint"><kbd aria-hidden="true">/</kbd><span class="sr" id="searchhint">Press Enter on a 9-digit organisation number to open that company.</span></form>
    <span class="meta" id="meta"></span>
    <button class="chipbtn" id="theme" type="button" aria-label="Switch between light and dark mode">◐</button>
  </div>
  <div class="filters" id="filters" role="group" aria-label="Filters and sorting"></div>
</div></header>
<main><div class="wrap" id="view" tabindex="-1">__STATIC__</div></main>
<div class="sr" id="live" aria-live="polite"></div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<div class="tray" id="tray" role="region" aria-label="Comparison"><div class="wrap"><span id="traytext"></span><a class="btn" id="traygo" href="#/compare">Compare</a><button class="btn ghost" id="cmpclear" type="button">Clear</button></div></div>
<div class="scrim" id="scrim"></div>
<div class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawertitle"><div class="dh"><h2 id="drawertitle">Evidence</h2><button class="btn ghost" id="drawerclose" type="button">Close</button></div><div class="body" id="drawerbody"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("data").textContent);
const C=DATA.companies;const byOrg=Object.fromEntries(C.map(c=>[c.o,c]));const SRC=(DATA.meta&&DATA.meta.sources)||{};
const INLINE=DATA.details||null;const cache={};const pending={};
const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const SECTIONS=[["identity","Identity"],["accounts","Accounts"],["people","People & places"],["website","Website"],["hiring","Hiring"],["activity","Activity"]];
const CODE_STATE={a:"available",n:"not_available",b:"blocked",m:"ambiguous",f:"failed",x:"not_applicable"};
const STATE_LABEL={available:"found",not_available:"not found",blocked:"blocked",ambiguous:"ambiguous",failed:"failed",not_applicable:"n/a"};
const STATE_ICON={available:"✓",not_available:"○",blocked:"⊘",ambiguous:"?",failed:"!",not_applicable:"–"};
const STATE_HELP=[["available","Found: published, and every value cites the exact excerpt it was copied from."],["not_available","Not found: the permitted sources were checked and nothing could be tied to this exact company. It is a gap, never a zero."],["blocked","Blocked: the source refused automated access (robots.txt or HTTP 401, 403, 429), so nothing was read from it."],["ambiguous","Ambiguous: a candidate might belong to another company (for example it prints a different organisation number), so nothing was published."],["failed","Failed: the source could not be reached in this run; values from the previous run are kept and marked as carried forward."],["not_applicable","Not applicable: the field does not apply to this kind of entity."]];
const PARTS=[["what_it_does","What it does"],["money","Money"],["people_and_presence","People and presence"],["what_changed","What changed"],["unknown","Not found"]];
const fold=s=>String(s??"").toLowerCase().replace(/ø/g,"o").replace(/å/g,"a").replace(/æ/g,"ae").normalize("NFKD").replace(/[̀-ͯ]/g,"");
function nok(v){if(v==null)return"";const a=Math.abs(v),s=v<0?"-":"";if(a>=1e9)return`NOK ${s}${(a/1e9).toFixed(1)} bn`;if(a>=1e6)return`NOK ${s}${(a/1e6).toFixed(1)} m`;if(a>=1e3)return`NOK ${s}${(a/1e3).toFixed(0)} k`;return`NOK ${s}${a.toFixed(0)}`}
const safeUrl=u=>/^https?:\/\//i.test(String(u||""))?String(u):"#";
const host=u=>String(u||"").replace(/^https?:\/\/(www\.)?/,"").replace(/\/$/,"");
const day=t=>String(t||"").slice(0,10);
const title=t=>String(t||"").toLowerCase().replace(/(^|[\s-])(\p{L})/gu,(m,p,ch)=>p+ch.toUpperCase());
const NONE=`<b class="none">not found</b>`;
const stateOf=(c,k)=>CODE_STATE[(c.s||"")[SECTIONS.findIndex(s=>s[0]===k)]]||"not_available";
const badge=(s,label)=>`<span class="st ${esc(s)}"><i aria-hidden="true">${STATE_ICON[s]||"·"}</i>${label?esc(label)+": ":""}${esc(STATE_LABEL[s]||s)}</span>`;
function legend(open){return `<details class="legend"${open?" open":""}><summary>What do found, not found, blocked, ambiguous and failed mean?</summary><dl class="legend">${STATE_HELP.map(([s,t])=>`<dt>${badge(s)}</dt><dd>${esc(t)}</dd>`).join("")}</dl></details>`}
// -- profiles: embedded, or loaded on demand from data/<org>.js (works from disk and from any static host) --------------
window.SP_DETAIL=(o,d)=>{cache[o]=d;const p=pending[o];delete pending[o];if(p)p.forEach(x=>x.ok(d))};
function detail(o){if(cache[o])return Promise.resolve(cache[o]);if(INLINE&&INLINE[o]){cache[o]=INLINE[o];return Promise.resolve(cache[o])}
  const row=byOrg[o];if(!row||!row.f)return Promise.reject(new Error("no profile data"));
  return new Promise((ok,fail)=>{const firstAsk=!pending[o];(pending[o]=pending[o]||[]).push({ok,fail});if(!firstAsk)return;
    const s=document.createElement("script");s.src="data/"+row.f+".js";s.async=true;
    s.onerror=()=>{const p=pending[o]||[];delete pending[o];s.remove();p.forEach(x=>x.fail(new Error("could not load data/"+row.f+".js")))};
    document.head.appendChild(s)})}
const claims=(c,f)=>c.cl.filter(x=>x.f===f);const first=(c,f)=>c.cl.find(x=>x.f===f);
const doc=(c,ev)=>{const d=(c.dc||[])[ev.d]||[];return{u:d[0],c:d[1],r:d[2],h:d[3]}};
function hay(c){if(!c._s)c._s=fold([c.o,c.n,c.b,c.m,c.i,c.w,c.k].join(" "));return c._s}
const FILTERS=[["website","Verified website",c=>stateOf(c,"website")==="available"],["hiring","Hiring now",c=>c.j>0||c.cp>0],["profiles","Social profiles",c=>c.p>0],["posts","Dated posts",c=>c.po>0],["accounts","Filed accounts",c=>stateOf(c,"accounts")==="available"],["signals","Has signals",c=>c.g.length>0],["changes","Changed since last run",c=>c.ch>0]];
const PAGE=matchMedia("(max-width:640px)").matches?48:120;
let active=new Set();let sortKey="relevance";let cmp=new Set();let lastFocus=null;let shownCount=PAGE;let current="";
try{cmp=new Set(JSON.parse(sessionStorage.getItem("signalpost-cmp")||"[]").filter(o=>byOrg[o]).slice(0,4))}catch(e){}
function toast(msg){const t=$("#toast");t.textContent=msg;t.classList.add("show");clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),2600)}
function cmpHash(list){return "#/compare/"+[...(list||cmp)].join(",")}
function saveCmp(){try{sessionStorage.setItem("signalpost-cmp",JSON.stringify([...cmp]))}catch(e){}updTray()}
function updTray(){const t=$("#tray");if(cmp.size&&!location.hash.startsWith("#/compare")){t.style.display="block";$("#traytext").textContent=`${cmp.size} of 4 selected to compare${cmp.size<2?": add at least one more":""}`;$("#traygo").href=cmpHash()}else t.style.display="none"}
function toggleCmp(o,on){if(on){if(cmp.size>=4&&!cmp.has(o)){toast("You can compare up to 4 companies. Remove one first.");return false}cmp.add(o)}else cmp.delete(o);saveCmp();return true}
const FCOUNT=Object.fromEntries(FILTERS.map(([k,,fn])=>[k,C.filter(fn).length]));
function renderFilters(){const f=$("#filters");f.innerHTML=FILTERS.map(([k,l])=>`<button type="button" class="chipbtn" data-f="${k}" aria-pressed="${active.has(k)}">${esc(l)} <span class="cnt">${FCOUNT[k]}</span></button>`).join("")+`<label class="sr" for="sort">Sort by</label><select id="sort" class="sort"><option value="relevance">Best match, then most data</option><option value="evidence">Most data found</option><option value="name">Name A–Z</option><option value="revenue">Revenue</option><option value="employees">Employees</option></select>`;
  f.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{const k=b.dataset.f;active.has(k)?active.delete(k):active.add(k);b.setAttribute("aria-pressed",active.has(k));shownCount=PAGE;goList()});
  const s=$("#sort");s.value=sortKey;s.onchange=()=>{sortKey=s.value;goList()}}
function goList(){if(location.hash.startsWith("#/c/")||location.hash.startsWith("#/compare"))location.hash="#/";else list()}
function query(){const raw=$("#q").value.trim();return{raw,q:fold(raw),terms:fold(raw).split(/\s+/).filter(Boolean),digits:raw.replace(/\D/g,"")}}
function score(c,Q){if(!Q.q)return 0;let s=0;const n=fold(c.n);if(Q.digits.length>=6&&c.o.startsWith(Q.digits))s+=1000;if(n===Q.q)s+=500;else if(n.startsWith(Q.q))s+=300;else if(n.includes(Q.q))s+=150;if(c.b&&fold(c.b).includes(Q.q))s+=100;return s}
function matches(){const Q=query();return C.filter(c=>(!Q.terms.length||Q.terms.every(t=>hay(c).includes(t))||(Q.digits.length>=6&&c.o.startsWith(Q.digits)))&&FILTERS.every(([k,,fn])=>!active.has(k)||fn(c)))}
function list(){const Q=query();let rows=matches();
  const val={evidence:c=>-c.nc,name:c=>c.n,revenue:c=>-((c.r||[])[0]??-1e18),employees:c=>-(c.e??-1),relevance:c=>-(score(c,Q)*1e4+c.nc)}[sortKey];
  rows.sort((a,b)=>{const x=val(a),y=val(b);return x<y?-1:x>y?1:a.n.localeCompare(b.n)});
  const v=$("#view");$("#live").textContent=`${rows.length} of ${C.length} companies`;
  if(!rows.length){v.innerHTML=`<div class="empty"><h1 class="sr">Companies</h1><p><strong>No companies match.</strong></p><p>Try another name or a 9-digit organisation number, or clear the filters.</p><button class="btn ghost" type="button" id="clearall">Clear search and filters</button></div>`;$("#clearall").onclick=()=>{$("#q").value="";active.clear();renderFilters();list()};return}
  const shown=rows.slice(0,shownCount);
  v.innerHTML=`<div class="listhead"><h1>Companies</h1><p class="meta">${rows.length} of ${C.length}${Q.raw?` matching “${esc(Q.raw)}”`:""}${active.size?" with the chosen filters":""}</p></div>`+help()+`<div class="grid">`+shown.map(card).join("")+`</div>`+(rows.length>shown.length?`<div class="more"><button class="btn ghost" type="button" id="showmore">Show ${Math.min(PAGE,rows.length-shown.length)} more (${rows.length-shown.length} not shown yet)</button></div>`:"");
  v.querySelectorAll("input[data-cmp]").forEach(i=>i.onchange=()=>{if(!toggleCmp(i.dataset.cmp,i.checked))i.checked=false});
  const sm=$("#showmore");if(sm)sm.onclick=()=>{const at=shownCount;shownCount+=PAGE;list();const next=document.querySelectorAll(".card h2 a")[at];if(next)next.focus()}}
function help(){return `<details class="help"><summary>How to find, compare and verify</summary><p><strong>Find:</strong> search by name or organisation number (with or without spaces), or by brand, place, person or industry; Enter on an exact organisation number opens it. <strong>Compare:</strong> tick Compare on two to four companies, or use “Compare with…” on a profile; the comparison has its own link you can share. <strong>Verify:</strong> every statement carries numbered source buttons. Each opens the exact excerpt, the source, the URL, the retrieval date and the SHA-256 of the stored copy; the numbers match the profile's list of sources. Anything we could not find is shown as not found, never as zero.</p>${legend(false)}</details>`}
function card(c){const st=SECTIONS.map(([k,l])=>`<li>${badge(stateOf(c,k),l)}</li>`).join("");
  return `<article class="card" aria-labelledby="t-${c.o}"><h2 id="t-${c.o}"><a href="#/c/${c.o}">${esc(c.n)}</a></h2>${c.b?`<p class="sub">trading as ${esc(c.b)}</p>`:""}<p class="sub">Org. ${c.o}${c.m?" · "+esc(c.m):""}${c.i?" · "+esc(c.i):""}</p>
  <div class="kpis"><span>${c.r?`<b>${esc(nok(c.r[0]))}</b>`:NONE}revenue ${c.r?esc(c.r[1])+(c.r[2]?" group":""):""}</span><span>${c.e!=null?`<b>${esc(c.e)}</b>`:NONE}employees</span><span>${c.j?`<b>${c.j}</b>`:NONE}job ads</span></div>
  ${c.w?`<p class="sub">Website: ${esc(c.w)}</p>`:""}
  ${c.g.length?`<div class="sigs">${c.g.slice(0,2).map(s=>`<span class="sig ${esc(s[1])}">${esc(s[0])}</span>`).join("")}</div>`:""}
  <ul class="states" aria-label="What was found for ${esc(c.n)}">${st}</ul>
  <div class="cardfoot"><a href="#/c/${c.o}" class="btn ghost">Open profile<span class="sr"> of ${esc(c.n)}</span></a><label class="cmp"><input type="checkbox" data-cmp="${c.o}" ${cmp.has(c.o)?"checked":""}> Compare<span class="sr"> ${esc(c.n)}</span></label></div></article>`}
// -- citations: numbers are sources (the same numbers as the summary's list of sources); the button opens the excerpts ----
let srcMap=new Map();
function seedSources(c){srcMap=new Map();(c.src||[]).forEach(s=>srcMap.set(s.u,{n:s.n,c:s.c,r:s.r}))}
function srcNo(u,cls,r){if(!srcMap.has(u))srcMap.set(u,{n:srcMap.size+1,c:cls,r});return srcMap.get(u).n}
function cite(c,ids,compact){ids=(ids||[]).filter(id=>c.cl.some(x=>x.i===id));if(!ids.length)return"";const seen=new Set(),nums=[],tips=[];
  ids.forEach(id=>{const x=c.cl.find(z=>z.i===id);(x.e||[]).forEach(eid=>{const ev=c.ev[eid];if(!ev)return;const d=doc(c,ev);if(seen.has(d.u))return;seen.add(d.u);const n=compact?0:srcNo(d.u,d.c,d.r);nums.push(n);tips.push(`${compact?"":n+". "}${srcLabel(d.c)}, retrieved ${day(d.r)}`)})});
  if(!tips.length)return"";nums.sort((a,b)=>a-b);const label=compact?"src":nums.length>3?`${nums[0]}–${nums[nums.length-1]}`:nums.join(",");
  return `<sup class="cite"><button type="button" data-ev="${esc(ids.join(","))}" title="${esc(tips.join("\n"))}" aria-label="${compact?"src":"Source "+label}: ${esc(tips.join("; "))}">${label}</button></sup>`}
function srcLabel(code){return SRC[code]||code||"source"}
function showEvidence(c,ids,trigger){const cl=c.cl.filter(x=>ids.includes(x.i));lastFocus=trigger||document.activeElement;
  $("#drawerbody").innerHTML=`<p class="note">${esc(c.n)} · org. ${esc(c.o)}</p>`+(cl.map(x=>{const evs=(x.e||[]).map(id=>c.ev[id]).filter(Boolean);return `<div class="ev"><div><strong>${esc(x.d)}</strong></div><div class="when">${x.p?`<span>Reporting period: ${esc(x.p)}</span>`:""}${x.t?`<span>As of: ${esc(day(x.t))}</span>`:""}</div>${x.carried_forward_from?`<div class="k">Carried forward from run ${esc(x.carried_forward_from)}: this run could not re-check the source</div>`:""}
  ${evs.map(ev=>{const d=doc(c,ev);return `<blockquote>${esc(ev.x)}</blockquote><div class="ok">✓ Checked in code: the value appears in this excerpt of the stored source</div><div class="when"><span><strong>Source:</strong> ${esc(srcLabel(d.c))}</span><span><strong>Retrieved:</strong> ${esc(String(d.r||"").replace("T"," ").replace("Z"," UTC"))}</span></div><div class="k">URL: <a href="${esc(safeUrl(d.u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(d.u)}</a></div><div class="k">SHA-256 of the stored copy ${esc(d.h)}… · ${ev.l&&String(ev.l).startsWith("/")?"JSON pointer ":"locator "}${esc(ev.l)} · ${esc(ev.m)}${ev.tf?" · "+esc(ev.tf):""}</div>
  <div class="row"><a class="btn small" href="${esc(safeUrl(d.u))}" target="_blank" rel="noopener noreferrer nofollow">Open source</a><button type="button" class="btn ghost small" data-copy="${esc(x.i)}|${esc(ev.d)}|${esc((x.e||[]).find(id=>c.ev[id]===ev))}">Copy citation</button></div>`}).join("")}</div>`}).join("")||"<p>No evidence.</p>");
  $("#drawertitle").textContent=`Evidence for ${cl.length} fact${cl.length===1?"":"s"}`;$("#drawer").classList.add("open");$("#scrim").classList.add("open");
  $("#drawerbody").querySelectorAll("[data-copy]").forEach(b=>b.onclick=()=>{const [ci,,ei]=b.dataset.copy.split("|");const x=c.cl.find(z=>z.i===ci),ev=c.ev[ei]||{},d=doc(c,ev);const txt=`${c.n} (org. ${c.o}): ${x?x.d:""}\nSource: ${srcLabel(d.c)}\nURL: ${d.u}\nRetrieved: ${d.r}\nSHA-256 prefix: ${d.h}\nLocator: ${ev.l}\nExcerpt: ${ev.x}`;
    (navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText(txt):Promise.reject()).then(()=>toast("Citation copied"),()=>toast("Copy is not available here; select the text instead"))});
  $("#drawerclose").focus()}
function closeDrawer(){if(!$("#drawer").classList.contains("open"))return;$("#drawer").classList.remove("open");$("#scrim").classList.remove("open");if(lastFocus&&document.contains(lastFocus))lastFocus.focus()}
$("#drawerclose").onclick=closeDrawer;$("#scrim").onclick=closeDrawer;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer();
  if(e.key==="Tab"&&$("#drawer").classList.contains("open")){const f=[...$("#drawer").querySelectorAll("a,button")];if(!f.length)return;const a=f[0],z=f[f.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}
  const typing=/input|textarea|select/i.test((e.target||{}).tagName||"");
  if((e.key==="/"&&!typing)||((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k")){e.preventDefault();$("#q").focus();$("#q").select()}});
function wireCites(find){document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=()=>{const ids=b.dataset.ev.split(",");const c=find(ids);if(c)showEvidence(c,ids,b)})}
const note=(c,k)=>{const n=((c.sec||{})[k]||{}).n;return n?`<p class="note">${esc(n)}</p>`:""};
const secState=(c,k)=>(((c.sec||{})[k]||{}).s)||"not_available";
function fact(c,f,label){const xs=claims(c,f);if(!xs.length)return"";return `<dt>${esc(label)}</dt><dd>${xs.map(x=>esc(x.d)+cite(c,[x.i])).join("<br>")}</dd>`}
const link=(u,t)=>`<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(t||u)}</a>`;
function latestAcc(c){const rows=c.cl.filter(x=>x.f==="revenue");if(!rows.length)return null;const grp=rows.filter(r=>r.account_type==="KONSERN");const use=(grp.length?grp:rows).slice();use.sort((a,b)=>String(b.year).localeCompare(String(a.year)));return use[0]}
function loadingView(row,what){return `<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / ${esc(row?row.n:what)}</nav><div class="hero"><h1>${esc(row?row.n:what)}</h1><p class="sub">${row?"Org. "+row.o:""}</p><p class="loading" role="status">Loading…</p><div class="skel"></div><div class="skel"></div><div class="skel" style="max-width:420px"></div></div>`}
function failView(o,err){return `<div class="empty" role="alert"><p><strong>The profile data could not be loaded.</strong></p><p>${esc(err&&err.message||"")}. The viewer keeps each profile in <code>data/${esc(o)}.js</code> next to this page; keep the <code>data</code> folder with <code>index.html</code>.</p><a class="btn ghost" href="#/">Back to all companies</a></div>`}
function profile(o){const row=byOrg[o];closeDrawer();if(!row){$("#view").innerHTML=`<div class="empty"><h1>Unknown organisation number ${esc(o)}</h1><p>It is not in this run. <a href="#/">Back to all companies</a></p></div>`;return}
  document.title=`${row.n} · Signalpost`;
  if(!cache[o]&&!(INLINE&&INLINE[o]))$("#view").innerHTML=loadingView(row);
  const token=current="c:"+o;
  detail(o).then(c=>{if(current!==token)return;renderProfile(row,c)},err=>{if(current===token)$("#view").innerHTML=failView(o,err)})}
function renderProfile(row,c){seedSources(c);
  const site=first(c,"official_website");
  const byPart={};(c.sum||[]).forEach(s=>{(byPart[s.p||"what_it_does"]=byPart[s.p||"what_it_does"]||[]).push(s)});
  const sent=s=>`${esc(s.t)}${cite(c,s.c)}`;
  const lede=byPart.overview?`<div class="lede"><h2>In brief</h2><p>${byPart.overview.map(sent).join(" ")}</p></div>`:"";
  const sigHtml=c.sig.length?`<div class="sigs" style="margin-top:10px" aria-label="Signals">${c.sig.map(s=>`<span class="sig ${esc(s.k)}">${esc(s.t)}${cite(c,s.c)}</span>`).join("")}</div>`:"";
  const partsHtml=PARTS.filter(([k])=>byPart[k]).map(([k,l])=>`<div class="part${k==="what_it_does"?" wide":""}"><h2>${esc(l)}</h2>${byPart[k].map(s=>`<p>${sent(s)}</p>`).join("")}</div>`).join("");
  const identFields=[["legal_name","Legal name"],["organisation_number","Org. number"],["public_brand","Public brand"],["legal_form","Legal form"],["business_address","Business address"],["postal_address","Postal address"],["industry_en","Industry (English)"],["industry","Industry (register)"],["secondary_industry_en","Other industries (English)"],["secondary_industry","Other industries"],["founded","Founded"],["registered_date","Registered"],["employees_registered","Employees (register)"],["share_capital","Share capital"],["vat_registered","VAT"],["business_register","Business register"],["part_of_group","Group"],["group_parent","Parent"],["group_ultimate_parent","Ultimate parent"],["group_subsidiary","Subsidiaries"],["former_name","Former names"],["registered_email","Registered e-mail"],["registered_phone","Registered phone"],["registered_website","Registered website"],["statutory_purpose","Statutory purpose"],["bankrupt","Bankruptcy"],["under_liquidation","Liquidation"]];
  const years=[...new Set(c.cl.filter(x=>x.f==="accounting_period").map(x=>x.year+"|"+x.account_type))].sort().reverse();
  const accFields=[["revenue","Revenue"],["operating_result","Operating result"],["profit_before_tax","Profit before tax"],["net_result","Net result"],["total_assets","Total assets"],["equity","Equity"],["debt","Debt"],["cash","Cash"],["salary_costs","Salary costs"]];
  let acc="";if(years.length){const cols=years.map(y=>y.split("|"));acc=`<div class="tblwrap" tabindex="0" role="region" aria-label="Filed annual accounts table"><table class="tbl"><caption class="sr">Filed annual accounts in NOK; each value links to its source</caption><thead><tr><th scope="col">NOK</th>${cols.map(([y,t])=>`<th scope="col">${esc(y)}${t==="KONSERN"?" group":""}</th>`).join("")}</tr></thead><tbody>`+accFields.map(([f,l])=>`<tr><th scope="row">${esc(l)}</th>${cols.map(([y,t])=>{const x=c.cl.find(z=>z.f===f&&z.year===y&&z.account_type===t);return `<td>${x?esc(nok(x.v))+cite(c,[x.i]):`<span class="sr">not reported</span><span aria-hidden="true">·</span>`}</td>`}).join("")}</tr>`).join("")+`</tbody></table></div>`;
    const rev=cols.filter(([y,t])=>t!=="KONSERN").map(([y,t])=>c.cl.find(z=>z.f==="revenue"&&z.year===y&&z.account_type===t)).filter(Boolean).reverse();const mx=Math.max(...rev.map(r=>Math.abs(r.v)),1);
    if(rev.length>1)acc=`<div class="bars" role="img" aria-label="Revenue by year: ${esc(rev.map(r=>r.year+" "+nok(r.v)).join(", "))}">${rev.map(r=>`<div class="${r.v<0?"neg":""}" style="height:${Math.max(3,Math.abs(r.v)/mx*100)}%" title="${esc(r.year)}: ${esc(nok(r.v))}"><span>${esc(r.year)}</span></div>`).join("")}</div>`+acc}
  const docs=claims(c,"annual_accounts_copy").sort((a,b)=>String(b.year).localeCompare(String(a.year)));
  const docsHtml=docs.length?`<h3>Official copies of the filed accounts (PDF)</h3><ul class="docs">${docs.map(x=>`<li>${link(x.url,x.year)}${cite(c,[x.i])}</li>`).join("")}</ul>`:"";
  const ident=identFields.map(([f,l])=>fact(c,f,l)).join("");
  const li=(xs,fn)=>xs.map(x=>`<li>${fn(x)}${cite(c,[x.i])}</li>`).join("");
  const roles=li(claims(c,"role"),x=>esc(x.d));
  const places=li(claims(c,"workplace"),x=>esc(x.d)+(x.employees!=null?` <span class="pill">${esc(x.employees)} employees</span>`:""));
  const profiles=li(claims(c,"social_profile"),x=>`<span class="pill">${esc(x.platform)}</span> `+link(x.v,host(x.v)));
  const proofs=li(claims(c,"website_identity_proof"),x=>esc(x.d));
  const extra=li(claims(c,"additional_website"),x=>"Also verified: "+link(x.v))+li(claims(c,"website_description"),x=>"“"+esc(x.d)+"”")+li(claims(c,"website_email"),x=>esc(x.d));
  const jobs=claims(c,"job_posting").sort((a,b)=>String(b.t||"").localeCompare(String(a.t||""))).map(x=>`<li>${link(x.url,x.d)}${cite(c,[x.i])}<div class="src">published ${esc(x.t||"?")}${x.expires?` · apply by ${esc(x.expires)}`:""}</div></li>`).join("");
  const careers=li(claims(c,"careers_page"),x=>link(x.v));
  const TL={website_post:"Own channels",registry_role_change:"Roles register",job_posting:"Job ad",registry_update:"Register",accounts_filed_event:"Accounts filed",employees_history:"Employees"};
  const tlItems=[...claims(c,"website_post"),...claims(c,"registry_role_change"),...claims(c,"job_posting"),...claims(c,"registry_update").filter(x=>!((x.changed_labels||[]).length===1&&x.changed_labels[0]==="employee count")),...claims(c,"employees_history")].filter(x=>x.t).sort((a,b)=>String(b.t).localeCompare(String(a.t))).slice(0,14);
  const acts=tlItems.map(x=>`<li><time datetime="${esc(day(x.t))}">${esc(day(x.t))} · ${esc(TL[x.f]||x.f)}</time>${esc(x.f==="job_posting"?x.d:x.f==="registry_update"?"Updated: "+((x.changed_labels||[]).join(", ")||x.d):x.d.replace(/^\d{4}-\d\d-\d\d (—|-) /,""))}${cite(c,[x.i])}</li>`).join("");
  const changes=c.ch.map(x=>`<li class="change ${esc(x.m)}">${esc(x.d)} <span class="pill">${esc(x.m)}</span>${cite(c,x.c)}</li>`).join("");
  const unkRows=(c.unkd&&c.unkd.length?c.unkd.map(u=>`<li>${badge(u.state)} <strong>${esc(u.item)}</strong>${u.reason?`: ${esc(u.reason)}`:""}</li>`):SECTIONS.filter(([k])=>secState(c,k)!=="available").map(([k,l])=>`<li>${badge(secState(c,k))} <strong>${esc(l)}</strong>${note(c,k)}</li>`)).join("");
  const bx=(id,title,k,body)=>`<section class="box" id="${id}" aria-labelledby="${id}-h" tabindex="-1"><h2 id="${id}-h">${esc(title)} ${k?badge(secState(c,k)):""}</h2>${body}</section>`;
  const sectionsHtml=`<div class="cols">
   ${bx("s-acc","Annual accounts","accounts",(acc||"<p class='note'>No filed figures returned by the Register of Company Accounts.</p>")+docsHtml+note(c,"accounts"))}
   ${bx("s-id","Legal identity","identity",`<dl class="facts">${ident}</dl>`+note(c,"identity"))}
   ${bx("s-people","Leadership and workplaces","people",(roles?`<ul class="plain">${roles}</ul>`:"<p class='note'>No active roles registered.</p>")+(places?`<h3>Registered workplaces</h3><ul class="plain">${places}</ul>`:""))}
   ${bx("s-web","Website and company profiles","website",(site?`<p>${link(site.v)}${cite(c,[site.i])}</p>`:"")+(proofs?`<ul class="plain">${proofs}</ul>`:"")+(extra?`<ul class="plain" style="margin-top:6px">${extra}</ul>`:"")+(profiles?`<h3>Profiles linked from the verified site</h3><ul class="plain">${profiles}</ul>`:"")+note(c,"website"))}
   ${bx("s-hire","Hiring","hiring",(jobs?`<ul class="plain">${jobs}</ul>`:"")+(careers?`<h3>Careers pages</h3><ul class="plain">${careers}</ul>`:"")+(!jobs&&!careers?"<p class='note'>No active job ad found.</p>":"")+note(c,"hiring"))}
   ${bx("s-act","Dated activity and register history","activity",acts?`<ol class="tl">${acts}</ol>`:"<p class='note'>No dated activity found.</p>")}
   ${bx("s-chg","Changes since the previous run","",c.run.prev?(changes?`<ul class="plain">${changes}</ul>`:`<p class='note'>No changes since our previous run${c.run.prevat?" on "+esc(day(c.run.prevat)):""}.</p>`):"<p class='note'>First run for this company: there is no earlier run of ours to compare with. The dated register history is under Dated activity.</p>")}
   ${bx("s-unk","What could not be found","",(unkRows?`<ul class="plain">${unkRows}</ul>`:"<p class='note'>Every section has supported data.</p>")+(c.err.length?`<p class="note">Errors: ${esc(c.err.join("; "))}</p>`:"")+legend(false))}
  </div>`;
  const allRows=c.cl.map(x=>{const ev=c.ev[(x.e||[])[0]];const d=ev?doc(c,ev):{};return `<tr><td style="white-space:normal;text-align:left">${esc(x.d)}${cite(c,[x.i])}</td><td style="text-align:left">${esc(srcLabel(d.c))}</td><td>${esc(day(d.r))}</td></tr>`}).join("");
  const allEv=`<section class="box" id="s-all" style="margin-top:12px" aria-labelledby="s-all-h" tabindex="-1"><h2 id="s-all-h">All ${c.cl.length} facts with their source and date</h2><details><summary>Show every fact</summary><div class="tblwrap" tabindex="0" role="region" aria-label="Every fact with its source"><table class="tbl"><thead><tr><th scope="col">Fact</th><th scope="col">Source</th><th scope="col">Retrieved</th></tr></thead><tbody>${allRows}</tbody></table></div></details></section>`;
  const srcList=[...srcMap.entries()].sort((a,b)=>a[1].n-b[1].n).map(([u,s])=>`<li id="src-${s.n}"><span class="num">${s.n}</span><span>${esc(srcLabel(s.c))}, retrieved ${esc(day(s.r))}<br>${link(u,u.replace(/^https?:\/\//,"").slice(0,90)+(u.replace(/^https?:\/\//,"").length>90?"…":""))}</span></li>`).join("");
  const srcBox=`<section class="box" id="s-src" style="margin-top:12px" aria-labelledby="s-src-h" tabindex="-1"><h2 id="s-src-h">Sources (${srcMap.size})</h2><p class="note">The numbers on every statement refer to this list. A number opens the exact excerpt, checked in code against the stored copy.</p><ol class="srcs">${srcList}</ol></section>`;
  const jumps=[["s-acc","Accounts"],["s-id","Identity"],["s-people","Leadership"],["s-web","Website"],["s-hire","Hiring"],["s-act","Activity"],["s-chg","Changes"],["s-unk","Not found"],["s-src","Sources"]];
  const sameInd=C.filter(x=>x.o!==row.o&&row.ic&&x.ic===row.ic).length;
  $("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / ${esc(c.n)}</nav>
  <div class="hero"><h1>${esc(c.n)}</h1><p class="sub">Org. ${c.o}${c.b?` · trading as ${esc(c.b)}`:""}${site?" · "+link(site.v,host(site.v)):""} · checked ${esc(day(c.run.at))}</p>
  <ul class="states" style="margin-top:10px" aria-label="What was found">${SECTIONS.map(([k,l])=>`<li>${badge(secState(c,k),l)}</li>`).join("")}</ul>${legend(false)}
  ${lede}${sigHtml}
  <div class="parts">${partsHtml||"<p>No supported summary.</p>"}</div>
  <div class="actions"><label class="cmp"><input type="checkbox" id="pcmp" ${cmp.has(c.o)?"checked":""}> Add to comparison</label><a class="btn small ghost" href="${cmpHash([...new Set([c.o,...cmp])].slice(0,4))}">Compare with…</a>${link("https://data.brreg.no/enhetsregisteret/api/enheter/"+c.o,"Official register record")}<a href="#" id="dl">Download this profile (JSON)</a></div>
  <ul class="jump" aria-label="Jump to a section">${jumps.map(([id,l])=>`<li><button type="button" data-jump="${id}">${esc(l)}</button></li>`).join("")}</ul></div>
  ${sectionsHtml}${srcBox}${allEv}
  <footer class="foot">Run ${esc(c.run.id)} · completed ${esc(c.run.at)}${c.run.prev?` · compared with run ${esc(c.run.prev)}`:""}${sameInd?` · ${sameInd} other compan${sameInd===1?"y":"ies"} in this run share its industry code`:""}. Every number and name is copied from the cited source; nothing is estimated.</footer>`;
  wireCites(()=>c);const pc=$("#pcmp");pc.onchange=()=>{if(!toggleCmp(c.o,pc.checked))pc.checked=false};
  document.querySelectorAll("[data-jump]").forEach(b=>b.onclick=()=>{const t=document.getElementById(b.dataset.jump);if(t){t.scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});t.focus({preventScroll:true})}});
  $("#dl").onclick=e=>{e.preventDefault();const blob=new Blob([JSON.stringify({organisation_number:c.o,legal_name:c.n,summary:c.sum,sources:c.src,signals:c.sig,not_found:c.unkd,facts:c.cl.map(x=>({fact:x.d,field:x.f,effective:x.t,evidence:(x.e||[]).map(id=>{const ev=c.ev[id];if(!ev)return null;const d=doc(c,ev);return{source:srcLabel(d.c),url:d.u,retrieved_at:d.r,sha256_prefix:d.h,locator:ev.l,excerpt:ev.x}})}))},null,1)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`signalpost-${c.o}.json`;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},500)};
  $("#view").focus({preventScroll:true});window.scrollTo(0,0)}
function similar(cs){const have=new Set(cs.map(c=>c.o));const out=[];const add=x=>{if(!have.has(x.o)&&!out.includes(x)&&out.length<4)out.push(x)};const base=cs[0];if(!base)return out;
  C.filter(x=>base.ic&&x.ic===base.ic).sort((a,b)=>b.nc-a.nc).forEach(add);C.filter(x=>base.ic&&x.ic&&x.ic.slice(0,2)===base.ic.slice(0,2)).sort((a,b)=>b.nc-a.nc).forEach(add);C.filter(x=>base.m&&x.m===base.m).sort((a,b)=>b.nc-a.nc).forEach(add);return out}
function compare(param){document.title="Compare · Signalpost";closeDrawer();const token=current="compare:"+(param||"");
  if(param!==null){const orgs=[...new Set(param.split(",").map(s=>s.replace(/\D/g,"")).filter(o=>byOrg[o]))].slice(0,4);cmp=new Set(orgs);saveCmp()}
  const rows=[...cmp].map(o=>byOrg[o]).filter(Boolean);
  const picker=`<form class="cmpbar" id="cmpform" role="search" aria-label="Add a company to the comparison"><label class="sr" for="cmpq">Add a company to the comparison by name or organisation number</label><input id="cmpq" list="cmplist" placeholder="Add a company: name or organisation number" autocomplete="off"><datalist id="cmplist">${C.slice(0,3000).map(c=>`<option value="${esc(c.o)}">${esc(c.n)}</option>`).join("")}</datalist><button class="btn small" type="submit">Add</button>${rows.length?`<button class="btn ghost small" type="button" id="cmpclear2">Clear all</button><button class="btn ghost small" type="button" id="cmplink">Copy link to this comparison</button>`:""}</form>`;
  const sim=similar(rows);const simHtml=rows.length&&rows.length<4&&sim.length?`<div class="suggest"><span>Similar companies in this run:</span>${sim.map(x=>`<button type="button" class="chipbtn" data-add="${x.o}">Add ${esc(x.n)}</button>`).join("")}</div>`:"";
  const head=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / Compare</nav><h1 style="font-size:20px;margin:0 0 10px">Compare companies</h1>${picker}${simHtml}`;
  if(!rows.length){$("#view").innerHTML=head+`<div class="empty"><p><strong>Nothing to compare yet.</strong></p><p>Tick Compare on two to four companies, or add one above by name or organisation number.</p><a class="btn" href="#/">Browse companies</a></div>`;wirePicker();return}
  $("#view").innerHTML=head+`<p class="loading" role="status">Loading ${rows.length} profile${rows.length>1?"s":""}…</p>`;wirePicker();
  Promise.all(rows.map(r=>detail(r.o))).then(cs=>{if(current!==token)return;renderCompare(head,rows,cs)},err=>{if(current!==token)return;$("#view").innerHTML=head+failView("<org>",err);wirePicker()})}
function renderCompare(head,rows,cs){
  const row=(label,fn,diff)=>{const vals=cs.map((c,i)=>fn(c,rows[i]));const differs=diff&&cs.length>1&&new Set(vals.map(v=>v.replace(/<sup[\s\S]*?<\/sup>/g,""))).size>1;return `<tr><th scope="row">${esc(label)}</th>${vals.map(v=>`<td${differs?' class="diff"':""}>${v}</td>`).join("")}</tr>`};
  const accv=(c,f)=>{const a=latestAcc(c);if(!a)return null;return f==="revenue"?a:c.cl.find(z=>z.f===f&&z.year===a.year&&z.account_type===a.account_type)};
  const nf=`<span class="note">not found</span>`;
  const show=(c,x,fmt)=>x?(fmt?fmt(x):esc(x.d))+cite(c,[x.i],true):nf;
  const role=(c,code)=>{const x=claims(c,"role").find(r=>r.role_code===code);return x?esc(x.d.split(": ").pop())+cite(c,[x.i],true):nf};
  const brief=c=>{const s=(c.sum||[]).filter(x=>x.p==="overview").slice(0,2);return s.length?s.map(x=>esc(x.t)+cite(c,x.c,true)).join(" "):nf};
  const posts=c=>{const p=claims(c,"website_post").sort((a,b)=>String(b.t||"").localeCompare(String(a.t||"")))[0];return p?esc(day(p.t))+": "+esc(p.d.replace(/^\d{4}-\d\d-\d\d (—|-) /,""))+cite(c,[p.i],true):nf};
  $("#view").innerHTML=head+`<div class="tblwrap" tabindex="0" role="region" aria-label="Comparison table"><table class="cmpt"><caption class="sr">Side-by-side comparison; shaded rows differ between the companies</caption><thead><tr><th scope="col">Company</th>${cs.map(c=>`<th scope="col"><a href="#/c/${c.o}">${esc(c.n)}</a><div class="sub">Org. ${c.o}</div><button type="button" class="chipbtn" data-rm="${c.o}" aria-label="Remove ${esc(c.n)} from the comparison">Remove</button></th>`).join("")}</tr></thead><tbody>
  ${row("In brief",c=>brief(c))}
  ${row("Data found",c=>`<ul class="states">${SECTIONS.map(([k,l])=>`<li>${badge(secState(c,k),l)}</li>`).join("")}</ul>`)}
  ${row("Industry",c=>{const x=first(c,"industry_en")||first(c,"industry");return show(c,x,y=>esc(y.v||y.d))},true)}${row("Location",c=>show(c,first(c,"municipality"),x=>esc(title(x.d))),true)}${row("Founded",c=>show(c,first(c,"founded")),true)}${row("Employees (register)",c=>show(c,first(c,"employees_registered"),x=>esc(x.v)),true)}
  ${row("Revenue (latest filed)",c=>show(c,accv(c,"revenue"),x=>esc(nok(x.v))+" in "+esc(x.year)+(x.account_type==="KONSERN"?" (group)":"")),true)}${row("Revenue change",(c,r)=>r.rc!=null?`${r.rc>=0?"+":""}${esc(r.rc)}% on the year before`+cite(c,c.cl.filter(z=>z.f==="revenue"&&z.account_type===(accv(c,"revenue")||{}).account_type).map(z=>z.i),true):nf,true)}${row("Operating result",c=>show(c,accv(c,"operating_result"),x=>esc(nok(x.v))),true)}${row("Net result",c=>show(c,accv(c,"net_result"),x=>esc(nok(x.v))),true)}${row("Equity",c=>show(c,accv(c,"equity"),x=>esc(nok(x.v))),true)}
  ${row("Chief executive",c=>role(c,"DAGL"),true)}${row("Chair",c=>role(c,"LEDE"),true)}${row("Workplaces",c=>claims(c,"workplace").length?String(claims(c,"workplace").length)+cite(c,claims(c,"workplace").map(x=>x.i),true):nf,true)}
  ${row("Website",c=>show(c,first(c,"official_website"),x=>link(x.v,host(x.v))),true)}${row("Social profiles",c=>claims(c,"social_profile").map(x=>esc(x.platform)+cite(c,[x.i],true)).join(", ")||nf,true)}
  ${row("Open job ads",c=>claims(c,"job_posting").length?String(claims(c,"job_posting").length)+cite(c,claims(c,"job_posting").map(x=>x.i),true):nf,true)}${row("Latest own post",c=>posts(c),true)}
  ${row("Signals",c=>c.sig.map(s=>esc(s.t)+cite(c,s.c,true)).join("<br>")||`<span class="note">none</span>`)}${row("Changes since our previous run",c=>c.run.prev?(String(c.ch.filter(x=>x.m!=="low").length||"none")):"first run",true)}
  ${row("Not found",c=>(c.unkd||[]).map(u=>badge(u.state)+" "+esc(u.item)).join("<br>")||`<span class="note">nothing missing</span>`)}
  ${row("Checked",c=>esc(day(c.run.at)))}
  </tbody></table></div><p class="meta">Shaded rows differ between the companies. Each “src” button opens the exact source excerpt, the URL and the retrieval date.</p>`;
  wireCites(ids=>cs.find(c=>c.cl.some(x=>ids.includes(x.i))));wirePicker();
  document.querySelectorAll("[data-rm]").forEach(b=>b.onclick=()=>{toggleCmp(b.dataset.rm,false);location.hash=cmpHash()})}
function wirePicker(){const f=$("#cmpform");if(!f)return;f.onsubmit=e=>{e.preventDefault();const q=fold($("#cmpq").value.trim());if(!q)return;const digits=q.replace(/\D/g,"");const hit=byOrg[digits]||C.find(c=>fold(c.n)===q)||C.find(c=>hay(c).includes(q));if(!hit){toast("No company matches that name or number");return}if(cmp.has(hit.o)){toast("Already in the comparison");return}if(toggleCmp(hit.o,true))location.hash=cmpHash()};
  const cl=$("#cmpclear2");if(cl)cl.onclick=()=>{cmp.clear();saveCmp();location.hash="#/compare"};
  const lk=$("#cmplink");if(lk)lk.onclick=()=>{(navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText(location.href):Promise.reject()).then(()=>toast("Link copied"),()=>toast("Copy the address from the address bar"))};
  document.querySelectorAll("[data-add]").forEach(b=>b.onclick=()=>{if(toggleCmp(b.dataset.add,true))location.hash=cmpHash()})}
function route(){closeDrawer();const h=location.hash||"#/";updTray();if(h.startsWith("#/c/"))return profile(decodeURIComponent(h.slice(4)).replace(/\D/g,""));if(h.startsWith("#/compare"))return compare(h.startsWith("#/compare/")?decodeURIComponent(h.slice(10)):null);current="list";document.title=DATA.meta&&DATA.meta.count?`Signalpost · ${DATA.meta.count} companies`:"Signalpost";list()}
window.addEventListener("hashchange",route);let tmr;$("#q").addEventListener("input",()=>{clearTimeout(tmr);shownCount=PAGE;tmr=setTimeout(goList,120)});
$("#searchform").onsubmit=e=>{e.preventDefault();clearTimeout(tmr);const digits=$("#q").value.replace(/\D/g,"");if(digits.length===9&&byOrg[digits]){location.hash="#/c/"+digits;return}const rows=matches();if(rows.length===1){location.hash="#/c/"+rows[0].o;return}goList()};
$("#cmpclear").onclick=()=>{cmp.clear();saveCmp();route()};
$("#theme").onclick=()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;r.dataset.theme=dark?"light":"dark"};
const m=DATA.meta;$("#meta").textContent=`${m.count} companies${m.completed?" · checked "+day(m.completed):""}${m.version?" · v"+m.version:""}`;
renderFilters();updTray();route();
</script>
</body>
</html>
"""
