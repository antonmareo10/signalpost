"""Static, self-contained viewer for a batch of envelopes (find, compare and verify on desktop and mobile).

``out/site/index.html`` embeds a compact projection of the envelopes, so it opens from disk (file://) or any
static host with no server and no external requests.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

SPAN_LIMIT = 260
CLAIM_KEYS = ("url", "platform", "role_code", "account_type", "year", "location", "expires", "municipality", "employees",
              "proof_kind", "carried_forward_from", "event_date", "valid_to", "changed_labels", "code", "classification",
              "document_type")
SOURCE_LABELS = {
    "official_registry_live": "Brønnøysund Register Centre: entity record (live API)",
    "official_annual_accounts": "Register of Company Accounts: filed figures (API)",
    "official_annual_account_copies": "Register of Company Accounts: list of filed accounts documents (API)",
    "official_roles": "Brønnøysund Register Centre: roles (live API)",
    "official_subunits": "Brønnøysund Register Centre: registered workplaces (live API)",
    "official_group_structure": "Brønnøysund Register Centre: group structure (live API)",
    "official_registry_updates": "Brønnøysund Register Centre: dated update log (live API)",
    "official_classification": "Statistics Norway: industry classification (KLASS API)",
    "official_job_vacancy_feed": "NAV public job-vacancy feed",
    "company_owned_website": "The company's own website",
    "company_owned_feed": "The company's own news feed",
}


def _project(env: dict[str, Any]) -> dict[str, Any]:
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
    evidence = {}
    for ev in env.get("evidence", []):
        if ev["id"] not in used_evidence:
            continue
        span = ev.get("claim_span") or ""
        evidence[ev["id"]] = {"u": ev.get("source_url"), "c": ev.get("source_class"), "r": ev.get("retrieved_at"),
                              "h": (ev.get("content_sha256") or "")[:16], "l": ev.get("locator"), "m": ev.get("extraction_method"),
                              "x": span if len(span) <= SPAN_LIMIT else span[:SPAN_LIMIT] + "…", "tf": ev.get("transform")}
    summary = env.get("summary", {})
    return {
        "o": env["organisation_number"], "n": env.get("legal_name") or "(unknown)", "b": env.get("public_brand"), "st": env.get("status"),
        "sec": {k: {"s": v.get("state"), "n": v.get("note"), "c": v.get("claims")} for k, v in env.get("sections", {}).items()},
        "sum": [{"t": s["text"], "c": s.get("claim_ids", []), "p": s.get("part")} for s in summary.get("sentences", [])],
        "sig": [{"t": s["text"], "c": s.get("claim_ids", []), "k": s.get("tone", "info")} for s in summary.get("signals", [])],
        "unk": summary.get("unknowns", []),
        "unkd": summary.get("unknown_detail", []),
        "cl": claims, "ev": evidence,
        "ch": [{"t": c["type"], "m": c["materiality"], "d": c["description"], "c": c.get("claim_ids", [])} for c in env.get("changes", [])],
        "run": {"id": env.get("run", {}).get("run_id"), "at": env.get("run", {}).get("completed_at"),
                "prev": (env.get("refresh") or {}).get("previous_run_id")},
        "err": [e.get("error") for e in env.get("errors", [])][:5],
    }


def _short(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{v}" for v in value.values() if v not in (None, ""))[:200]
    return str(value)[:200]


def build_site(envelopes: list[dict[str, Any]], site_dir: Path, report: dict[str, Any] | None = None) -> Path:
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    data = [_project(e) for e in envelopes]
    meta = {"run": (report or {}).get("run_id"), "completed": (report or {}).get("completed_at"), "count": len(envelopes),
            "version": (report or {}).get("agent_version"), "sources": SOURCE_LABELS}
    payload = json.dumps({"meta": meta, "companies": data}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(f"Signalpost · {len(envelopes)} companies"))
    target = site_dir / "index.html"
    target.write_text(page, encoding="utf-8", newline="\n")
    return target


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="Evidence-first company profiles for Norwegian organisation numbers. Every fact links to its source.">
<style>
:root{--bg:#f5f6f8;--panel:#fff;--ink:#121720;--muted:#576170;--line:#e1e5ea;--accent:#0b5cad;--accent-ink:#fff;--ok:#11703b;--warn:#8a5300;--bad:#b42318;--chip:#edf2f9;--soft:#f8fafc;--shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.07)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0e1217;--panel:#151a21;--ink:#e8ecf1;--muted:#9ba5b3;--line:#29313b;--accent:#62a8ff;--accent-ink:#0b1220;--ok:#46c486;--warn:#e3a842;--bad:#ff7d70;--chip:#1c2532;--soft:#11161c;--shadow:none}}
:root[data-theme=dark]{--bg:#0e1217;--panel:#151a21;--ink:#e8ecf1;--muted:#9ba5b3;--line:#29313b;--accent:#62a8ff;--accent-ink:#0b1220;--ok:#46c486;--warn:#e3a842;--bad:#ff7d70;--chip:#1c2532;--soft:#11161c;--shadow:none}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-text-size-adjust:100%}
a{color:var(--accent)}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:6px}
header.top{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
.bar{display:flex;gap:12px;align-items:center;padding:10px 0;flex-wrap:wrap}
.brand{font-weight:750;letter-spacing:-.02em;font-size:18px;display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--ink)}
.brand svg{width:22px;height:22px}
.search{flex:1 1 260px;display:flex;position:relative}
.search input{width:100%;padding:10px 40px 10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font-size:16px;min-height:44px}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);font:12px/1 ui-monospace,monospace;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:3px 6px;background:var(--panel)}
.meta{color:var(--muted);font-size:13px}
.filters{display:flex;gap:8px;flex-wrap:wrap;padding:0 0 10px}
.chipbtn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer;min-height:36px}
.chipbtn[aria-pressed=true]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
select.sort{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 10px;font-size:13px;min-height:36px}
main{padding:16px 0 96px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px;min-width:0}
.card h3{margin:0;font-size:16px;line-height:1.3;overflow-wrap:anywhere}
.card h3 a{text-decoration:none;color:var(--ink)}.card h3 a:hover{color:var(--accent)}
.sub{color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.kpis{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--muted)}.kpis b{font-size:15px;display:block;color:var(--ink)}.kpis b.none{color:var(--muted);font-weight:500}
.dots{display:flex;gap:6px;flex-wrap:wrap}
.dot{font-size:11.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.dot.available{color:var(--ok);border-color:var(--ok)}
.dot.ambiguous,.dot.blocked{color:var(--warn);border-color:var(--warn)}
.dot.failed{color:var(--bad);border-color:var(--bad)}
.sigs{display:flex;gap:6px;flex-wrap:wrap}
.sig{font-size:12.5px;padding:3px 9px;border-radius:8px;background:var(--chip);color:var(--ink);border:1px solid transparent;display:inline-flex;align-items:center;gap:4px}
.sig.up{border-color:var(--ok)}.sig.down{border-color:var(--warn)}.sig.risk{border-color:var(--bad);color:var(--bad)}
.sig b{font-weight:650}
.cardfoot{display:flex;justify-content:space-between;align-items:center;margin-top:auto;gap:8px;flex-wrap:wrap}
label.cmp{display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer;min-height:40px}
label.cmp input{width:18px;height:18px}
.btn{border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);border-radius:10px;padding:8px 14px;font-weight:600;cursor:pointer;min-height:40px;text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-size:14px}
.btn.ghost{background:transparent;color:var(--accent)}
.btn.small{min-height:32px;padding:4px 10px;font-size:13px}
.tray{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);box-shadow:0 -4px 16px rgba(0,0,0,.08);padding:10px 0 calc(10px + env(safe-area-inset-bottom));display:none;z-index:6}
.tray .wrap{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);background:var(--ink);color:var(--panel);padding:8px 14px;border-radius:10px;font-size:14px;z-index:12;opacity:0;pointer-events:none;transition:opacity .15s}
.toast.show{opacity:1}
.empty{padding:40px 16px;text-align:center;color:var(--muted)}
.crumbs{margin:0 0 10px;font-size:14px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow)}
.hero h1{margin:0 0 4px;font-size:clamp(20px,3vw,28px);letter-spacing:-.02em;line-height:1.2;overflow-wrap:anywhere}
.parts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 22px;margin-top:14px}
.part{min-width:0}.part.wide{grid-column:1/-1}
.part h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 4px;font-weight:700}
.part p{margin:0 0 6px;font-size:15.5px;line-height:1.6;max-width:80ch}
@media (max-width:860px){.parts{grid-template-columns:1fr}}
sup.cite{font-size:11px;margin-left:2px;line-height:0}
sup.cite button{border:0;background:var(--chip);color:var(--accent);border-radius:6px;padding:1px 5px;cursor:pointer;font:inherit;font-weight:650;min-width:24px;min-height:24px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:860px){.cols{grid-template-columns:1fr}}
section.box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);min-width:0}
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
.tbl{width:100%;border-collapse:collapse;font-size:13.5px}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.src{font-size:12px;color:var(--muted)}
.bars{display:flex;align-items:flex-end;gap:8px;height:64px;margin:6px 0 20px;max-width:320px}
.bars div{flex:1;background:var(--accent);opacity:.75;border-radius:4px 4px 0 0;min-height:2px;position:relative}
.bars div.neg{background:var(--bad)}
.bars span{position:absolute;bottom:-18px;left:0;right:0;text-align:center;font-size:11px;color:var(--muted)}
.drawer{position:fixed;right:0;top:0;bottom:0;width:min(560px,100%);background:var(--panel);border-left:1px solid var(--line);box-shadow:-8px 0 24px rgba(0,0,0,.12);transform:translateX(105%);transition:transform .18s ease;z-index:10;display:flex;flex-direction:column;visibility:hidden}
.drawer.open{transform:none;visibility:visible}
.drawer header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);gap:8px}
.drawer .body{padding:14px 16px calc(14px + env(safe-area-inset-bottom));overflow:auto}
.ev{border:1px solid var(--line);border-radius:12px;padding:10px;margin:0 0 10px}
.ev q{display:block;background:var(--chip);border-radius:8px;padding:8px;margin:6px 0;font-size:13px;quotes:none;overflow-wrap:anywhere;white-space:pre-wrap}
.ev .k{color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.ev .ok{color:var(--ok);font-size:12.5px;font-weight:600}
.ev .row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.25);opacity:0;pointer-events:none;transition:opacity .18s;z-index:9}
.scrim.open{opacity:1;pointer-events:auto}
.cmpbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
.cmpbar input{flex:1 1 240px;padding:8px 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--ink);font-size:16px;min-height:40px}
.cmpt{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.cmpt th,.cmpt td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;font-size:14px;overflow-wrap:anywhere;min-width:150px;background:var(--panel)}
.cmpt tbody th{color:var(--muted);font-weight:600;min-width:118px;position:sticky;left:0;z-index:1;box-shadow:1px 0 0 var(--line)}
.cmpt thead th:first-child{position:sticky;left:0;z-index:2}
.cmpt td.diff{background:var(--soft)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px}
.change{padding-left:8px;border-left:3px solid var(--line)}.change.high{border-left-color:var(--bad)}.change.medium{border-left-color:var(--warn)}
details.help{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:0 0 12px}
details.help summary{cursor:pointer;font-weight:600}
details.help p{margin:8px 0 0;color:var(--muted);font-size:14px;max-width:90ch}
footer.foot{color:var(--muted);font-size:12.5px;padding:24px 0}
@media (prefers-reduced-motion:reduce){.drawer,.scrim,.toast{transition:none}}
#view:focus{outline:none}
@media (max-width:640px){header.top{position:static}.bar .meta{display:none}.search kbd{display:none}.filters{flex-wrap:nowrap;overflow-x:auto;padding-bottom:12px;scrollbar-width:none}.filters>*{flex:0 0 auto}.hero{padding:14px}.part p{font-size:15px}.cmpt th,.cmpt td{min-width:132px}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media print{header.top,.tray,.drawer,.scrim,label.cmp,.btn,.cardfoot{display:none!important}body{background:#fff}}
</style>
</head>
<body>
<a class="sr" href="#view">Skip to content</a>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="#/" aria-label="Signalpost home"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>Signalpost</a>
    <form class="search" role="search" id="searchform"><label class="sr" for="q">Search companies by name, organisation number, brand, place, person or industry</label>
      <input id="q" type="search" placeholder="Name, org. number, brand, place, person or industry" autocomplete="off" enterkeyhint="search"><kbd aria-hidden="true">/</kbd></form>
    <span class="meta" id="meta"></span>
    <button class="chipbtn" id="theme" type="button" aria-label="Switch between light and dark mode">◐</button>
  </div>
  <div class="filters" id="filters" role="group" aria-label="Filters and sorting"></div>
</div></header>
<main><div class="wrap" id="view" tabindex="-1"></div></main>
<div class="sr" id="live" aria-live="polite"></div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<div class="tray" id="tray" role="region" aria-label="Compare tray"><div class="wrap"><span id="traytext"></span><a class="btn" href="#/compare">Compare</a><button class="btn ghost" id="cmpclear" type="button">Clear</button></div></div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawertitle"><header><strong id="drawertitle">Evidence</strong><button class="btn ghost" id="drawerclose" type="button">Close</button></header><div class="body" id="drawerbody"></div></aside>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("data").textContent);
const C=DATA.companies;const byOrg=Object.fromEntries(C.map(c=>[c.o,c]));const SRC=(DATA.meta&&DATA.meta.sources)||{};
const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const SECTIONS=[["identity","Identity"],["accounts","Accounts"],["people","People & places"],["website","Website"],["hiring","Hiring"],["activity","Activity"]];
const STATE_LABEL={available:"found",not_available:"not found",blocked:"blocked",ambiguous:"ambiguous",failed:"failed",not_applicable:"n/a"};
const PARTS=[["what_it_does","What it does"],["money","Money"],["people_and_presence","People and presence"],["what_changed","What changed"],["unknown","Not found"]];
const fold=s=>String(s??"").toLowerCase().replace(/ø/g,"o").replace(/å/g,"a").replace(/æ/g,"ae").normalize("NFKD").replace(/[̀-ͯ]/g,"");
function nok(v){if(v==null)return"";const a=Math.abs(v),s=v<0?"-":"";if(a>=1e9)return`NOK ${s}${(a/1e9).toFixed(1)} bn`;if(a>=1e6)return`NOK ${s}${(a/1e6).toFixed(1)} m`;if(a>=1e3)return`NOK ${s}${(a/1e3).toFixed(0)} k`;return`NOK ${s}${a.toFixed(0)}`}
const claims=(c,f)=>c.cl.filter(x=>x.f===f);const first=(c,f)=>c.cl.find(x=>x.f===f);
const safeUrl=u=>/^https?:\/\//i.test(String(u||""))?String(u):"#";
const host=u=>String(u||"").replace(/^https?:\/\/(www\.)?/,"").replace(/\/$/,"");
const NONE=`<b class="none">not found</b>`;
function latestAcc(c){const rows=c.cl.filter(x=>x.f==="revenue");if(!rows.length)return null;const grp=rows.filter(r=>r.account_type==="KONSERN");const use=(grp.length?grp:rows).slice();use.sort((a,b)=>String(b.year).localeCompare(String(a.year)));return use[0]}
function emp(c){const e=first(c,"employees_registered");return e?e.v:null}
function industry(c){const e=first(c,"industry_en");if(e)return e.v;const n=first(c,"industry");return n?n.d:""}
function hay(c){if(!c._s)c._s=fold([c.o,c.o.replace(/(\d{3})(?=\d)/g,"$1 "),c.n,c.b,(first(c,"municipality")||{}).d,(first(c,"industry")||{}).d,industry(c),...claims(c,"role").map(r=>r.d),(first(c,"official_website")||{}).v,...claims(c,"former_name").map(r=>r.d)].join(" "));return c._s}
const FILTERS=[["website","Verified website",c=>(c.sec.website||{}).s==="available"],["hiring","Hiring now",c=>claims(c,"job_posting").length>0||claims(c,"careers_page").length>0],["profiles","Social profiles",c=>claims(c,"social_profile").length>0],["accounts","Filed accounts",c=>(c.sec.accounts||{}).s==="available"],["signals","Has signals",c=>c.sig.length>0],["changes","Changed since last run",c=>c.ch.some(x=>x.m!=="low")]];
let active=new Set();let sortKey="evidence";let cmp=new Set();let lastFocus=null;
try{cmp=new Set(JSON.parse(sessionStorage.getItem("signalpost-cmp")||"[]").filter(o=>byOrg[o]))}catch(e){}
function toast(msg){const t=$("#toast");t.textContent=msg;t.classList.add("show");clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove("show"),2600)}
function saveCmp(){try{sessionStorage.setItem("signalpost-cmp",JSON.stringify([...cmp]))}catch(e){}updTray()}
function updTray(){const t=$("#tray");if(cmp.size&&location.hash!=="#/compare"){t.style.display="block";$("#traytext").textContent=`${cmp.size} of 4 selected to compare`}else t.style.display="none"}
function toggleCmp(o,on){if(on){if(cmp.size>=4&&!cmp.has(o)){toast("You can compare up to 4 companies. Remove one first.");return false}cmp.add(o)}else cmp.delete(o);saveCmp();return true}
function renderFilters(){const f=$("#filters");f.innerHTML=FILTERS.map(([k,l])=>`<button type="button" class="chipbtn" data-f="${k}" aria-pressed="${active.has(k)}">${esc(l)}</button>`).join("")+`<label class="sr" for="sort">Sort by</label><select id="sort" class="sort"><option value="evidence">Most evidence</option><option value="name">Name A–Z</option><option value="revenue">Revenue</option><option value="employees">Employees</option></select>`;
  f.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{const k=b.dataset.f;active.has(k)?active.delete(k):active.add(k);renderFilters();goList()});
  const s=$("#sort");s.value=sortKey;s.onchange=()=>{sortKey=s.value;goList()}}
function goList(){if(location.hash.startsWith("#/c/")||location.hash==="#/compare")location.hash="#/";else list()}
function matches(){const q=fold($("#q").value.trim());const terms=q.split(/\s+/).filter(Boolean);return C.filter(c=>(!terms.length||terms.every(t=>hay(c).includes(t)))&&FILTERS.every(([k,,fn])=>!active.has(k)||fn(c)))}
function list(){let rows=matches();
  const val={evidence:c=>-c.cl.length,name:c=>c.n,revenue:c=>-((latestAcc(c)||{}).v??-1e18),employees:c=>-(emp(c)??-1)}[sortKey];
  rows.sort((a,b)=>{const x=val(a),y=val(b);return x<y?-1:x>y?1:0});
  const v=$("#view");$("#live").textContent=`${rows.length} of ${C.length} companies`;
  if(!rows.length){v.innerHTML=`<div class="empty"><p><strong>No companies match.</strong></p><p>Try another name or a 9-digit organisation number, or clear the filters.</p><button class="btn ghost" type="button" id="clearall">Clear search and filters</button></div>`;$("#clearall").onclick=()=>{$("#q").value="";active.clear();renderFilters();list()};return}
  const shown=rows.slice(0,240);
  v.innerHTML=help()+`<p class="meta">${rows.length} of ${C.length} companies${rows.length>240?". The first 240 are shown; refine the search to see the rest":""}</p><div class="grid">`+shown.map(card).join("")+`</div>`;
  v.querySelectorAll("input[data-cmp]").forEach(i=>i.onchange=()=>{if(!toggleCmp(i.dataset.cmp,i.checked))i.checked=false})}
function help(){return `<details class="help"><summary>How to use and verify this data</summary><p>Search by name, organisation number, brand, place, person or industry, and press Enter on an exact organisation number to open it. Tick Compare on up to four companies to see them side by side. Every fact carries a small numbered button: it opens the exact excerpt, the source URL, the retrieval time and the SHA-256 of the stored copy, so you can check it yourself. Anything we could not find is shown as not found, never as zero.</p></details>`}
function card(c){const acc=latestAcc(c),e=emp(c),site=first(c,"official_website"),jobs=claims(c,"job_posting").length,ind=industry(c);
  return `<article class="card"><h3><a href="#/c/${c.o}">${esc(c.n)}</a></h3>${c.b?`<div class="sub">trading as ${esc(c.b)}</div>`:""}<div class="sub">${c.o} · ${esc((first(c,"municipality")||{}).d||"")}${ind?" · "+esc(ind):""}</div>
  <div class="kpis"><span>${acc?`<b>${esc(nok(acc.v))}</b>`:NONE}revenue ${acc?esc(acc.year)+(acc.account_type==="KONSERN"?" group":""):""}</span><span>${e!=null?`<b>${esc(e)}</b>`:NONE}employees</span><span>${jobs?`<b>${jobs}</b>`:NONE}job ads</span></div>
  ${site?`<div class="sub">Website: <a href="${esc(safeUrl(site.v))}" rel="noopener noreferrer nofollow" target="_blank">${esc(host(site.v))}</a></div>`:""}
  ${c.sig.length?`<div class="sigs">${c.sig.slice(0,2).map(s=>`<span class="sig ${esc(s.k)}">${esc(s.t)}</span>`).join("")}</div>`:""}
  <div class="dots">${SECTIONS.map(([k,l])=>{const s=(c.sec[k]||{}).s||"not_available";return`<span class="dot ${esc(s)}" title="${esc(l)}: ${esc(STATE_LABEL[s]||s)}">${esc(l)}<span class="sr">: ${esc(STATE_LABEL[s]||s)}</span></span>`}).join("")}</div>
  <div class="cardfoot"><a href="#/c/${c.o}" class="btn ghost">Open profile</a><label class="cmp"><input type="checkbox" data-cmp="${c.o}" ${cmp.has(c.o)?"checked":""}> Compare</label></div></article>`}
let citeIndex={};
function cite(c,ids){ids=(ids||[]).filter(Boolean);if(!ids.length)return"";const n=ids.map(id=>{if(!(id in citeIndex))citeIndex[id]=Object.keys(citeIndex).length+1;return citeIndex[id]});const uniq=[...new Set(n)].sort((a,b)=>a-b);const contiguous=uniq[uniq.length-1]-uniq[0]===uniq.length-1;const label=uniq.length>3?(contiguous?`${uniq[0]}–${uniq[uniq.length-1]}`:`${uniq[0]} +${uniq.length-1}`):uniq.join(",");
  return `<sup class="cite"><button type="button" data-ev="${esc(ids.join(","))}" aria-label="Show ${ids.length} source${ids.length>1?"s":""} for this statement">${label}</button></sup>`}
function srcLabel(code){return SRC[code]||code||"source"}
function showEvidence(c,ids,trigger){const cl=c.cl.filter(x=>ids.includes(x.i));lastFocus=trigger||document.activeElement;
  $("#drawerbody").innerHTML=`<p class="note">${esc(c.n)} · org. ${esc(c.o)}</p>`+(cl.map(x=>{const evs=x.e.map(id=>[id,c.ev[id]]).filter(p=>p[1]);return `<div class="ev"><div><strong>${esc(x.d)}</strong></div>${x.p?`<div class="k">Reporting period ${esc(x.p)}</div>`:""}${x.t?`<div class="k">Effective ${esc(x.t)}</div>`:""}${x.carried_forward_from?`<div class="k">Carried forward from run ${esc(x.carried_forward_from)}: this run could not re-check the source</div>`:""}
  ${evs.map(([id,ev])=>`<q>${esc(ev.x)}</q><div class="ok">✓ Checked in code: the value appears in this excerpt of the stored source</div><div class="k">${esc(srcLabel(ev.c))}</div><div class="k">Source: <a href="${esc(safeUrl(ev.u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(ev.u)}</a></div><div class="k">Retrieved ${esc(ev.r)} · SHA-256 ${esc(ev.h)}… · ${ev.l&&ev.l.startsWith("/")?"JSON pointer ":"locator "}${esc(ev.l)} · ${esc(ev.m)}${ev.tf?" · "+esc(ev.tf):""}</div>
  <div class="row"><a class="btn small" href="${esc(safeUrl(ev.u))}" target="_blank" rel="noopener noreferrer nofollow">Open source</a><button type="button" class="btn ghost small" data-copy="${esc(x.i)}|${esc(id)}">Copy citation</button></div>`).join("")}</div>`}).join("")||"<p>No evidence.</p>");
  $("#drawertitle").textContent=`Evidence for ${cl.length} fact${cl.length===1?"":"s"}`;$("#drawer").classList.add("open");$("#scrim").classList.add("open");
  $("#drawerbody").querySelectorAll("[data-copy]").forEach(b=>b.onclick=()=>{const [ci,ei]=b.dataset.copy.split("|");const x=c.cl.find(z=>z.i===ci),ev=c.ev[ei]||{};const txt=`${c.n} (org. ${c.o}): ${x?x.d:""}\nSource: ${ev.u}\nRetrieved: ${ev.r}\nSHA-256 prefix: ${ev.h}\nLocator: ${ev.l}\nExcerpt: ${ev.x}`;
    (navigator.clipboard&&navigator.clipboard.writeText?navigator.clipboard.writeText(txt):Promise.reject()).then(()=>toast("Citation copied"),()=>toast("Copy is not available here; select the text instead"))});
  $("#drawerclose").focus()}
function closeDrawer(){if(!$("#drawer").classList.contains("open"))return;$("#drawer").classList.remove("open");$("#scrim").classList.remove("open");if(lastFocus&&document.contains(lastFocus))lastFocus.focus()}
$("#drawerclose").onclick=closeDrawer;$("#scrim").onclick=closeDrawer;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer();
  if(e.key==="Tab"&&$("#drawer").classList.contains("open")){const f=[...$("#drawer").querySelectorAll("a,button")];if(!f.length)return;const a=f[0],z=f[f.length-1];if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}
  if(e.key==="/"&&!/input|textarea|select/i.test((e.target||{}).tagName||"")){e.preventDefault();$("#q").focus()}});
function wireCites(find){document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=()=>{const ids=b.dataset.ev.split(",");const c=find(ids);if(c)showEvidence(c,ids,b)})}
const badge=(c,k)=>{const s=(c.sec[k]||{}).s||"not_available";return `<span class="dot ${esc(s)}">${esc(STATE_LABEL[s]||s)}</span>`};
const note=(c,k)=>{const n=(c.sec[k]||{}).n;return n?`<p class="note">${esc(n)}</p>`:""};
function fact(c,f,label){const xs=claims(c,f);if(!xs.length)return"";return `<dt>${esc(label)}</dt><dd>${xs.map(x=>esc(x.d)+cite(c,[x.i])).join("<br>")}</dd>`}
const link=(u,t)=>`<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(t||u)}</a>`;
function profile(o){const c=byOrg[o];citeIndex={};if(!c){$("#view").innerHTML=`<div class="empty">Unknown organisation number ${esc(o)}. <a href="#/">Back to the list</a></div>`;return}
  document.title=`${c.n} · Signalpost`;
  const site=first(c,"official_website");
  const byPart={};c.sum.forEach(s=>{(byPart[s.p||"what_it_does"]=byPart[s.p||"what_it_does"]||[]).push(s)});
  const sigHtml=c.sig.length?`<div class="sigs" style="margin-top:10px" aria-label="Signals">${c.sig.map(s=>`<span class="sig ${esc(s.k)}">${esc(s.t)}${cite(c,s.c)}</span>`).join("")}</div>`:"";
  const partsHtml=PARTS.filter(([k])=>byPart[k]).map(([k,l])=>`<div class="part${k==="what_it_does"?" wide":""}"><h2>${esc(l)}</h2>${byPart[k].map(s=>`<p>${esc(s.t)}${cite(c,s.c)}</p>`).join("")}</div>`).join("");
  const identFields=[["legal_name","Legal name"],["organisation_number","Org. number"],["public_brand","Public brand"],["legal_form","Legal form"],["business_address","Business address"],["postal_address","Postal address"],["industry_en","Industry (English)"],["industry","Industry (register)"],["secondary_industry_en","Other industries (English)"],["secondary_industry","Other industries"],["founded","Founded"],["registered_date","Registered"],["employees_registered","Employees (register)"],["share_capital","Share capital"],["vat_registered","VAT"],["business_register","Business register"],["part_of_group","Group"],["group_parent","Parent"],["group_ultimate_parent","Ultimate parent"],["group_subsidiary","Subsidiaries"],["former_name","Former names"],["registered_email","Registered e-mail"],["registered_phone","Registered phone"],["registered_website","Registered website"],["statutory_purpose","Statutory purpose"],["bankrupt","Bankruptcy"],["under_liquidation","Liquidation"]];
  const years=[...new Set(c.cl.filter(x=>x.f==="accounting_period").map(x=>x.year+"|"+x.account_type))].sort().reverse();
  const accFields=[["revenue","Revenue"],["operating_result","Operating result"],["profit_before_tax","Profit before tax"],["net_result","Net result"],["total_assets","Total assets"],["equity","Equity"],["debt","Debt"],["cash","Cash"],["salary_costs","Salary costs"]];
  let acc="";if(years.length){const cols=years.map(y=>y.split("|"));acc=`<div class="tblwrap"><table class="tbl"><caption class="sr">Filed annual accounts in NOK</caption><thead><tr><th scope="col">NOK</th>${cols.map(([y,t])=>`<th scope="col">${esc(y)}${t==="KONSERN"?" group":""}</th>`).join("")}</tr></thead><tbody>`+accFields.map(([f,l])=>`<tr><th scope="row">${esc(l)}</th>${cols.map(([y,t])=>{const x=c.cl.find(z=>z.f===f&&z.year===y&&z.account_type===t);return `<td>${x?esc(nok(x.v))+cite(c,[x.i]):`<span class="sr">not reported</span><span aria-hidden="true">·</span>`}</td>`}).join("")}</tr>`).join("")+`</tbody></table></div>`;
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
  const tlItems=[...claims(c,"website_post"),...claims(c,"registry_role_change"),...claims(c,"job_posting"),...claims(c,"registry_update"),...claims(c,"employees_history")].filter(x=>x.t).sort((a,b)=>String(b.t).localeCompare(String(a.t))).slice(0,14);
  const acts=tlItems.map(x=>`<li><time datetime="${esc(String(x.t).slice(0,10))}">${esc(String(x.t).slice(0,10))} · ${esc(TL[x.f]||x.f)}</time>${esc(x.f==="job_posting"?x.d:x.f==="registry_update"?"Updated: "+((x.changed_labels||[]).join(", ")||x.d):x.d.replace(/^\d{4}-\d\d-\d\d (—|-) /,""))}${cite(c,[x.i])}</li>`).join("");
  const changes=c.ch.map(x=>`<li class="change ${esc(x.m)}">${esc(x.d)} <span class="pill">${esc(x.m)}</span>${cite(c,x.c.filter(id=>c.cl.some(z=>z.i===id)))}</li>`).join("");
  const unkRows=(c.unkd&&c.unkd.length?c.unkd.map(u=>`<li><strong>${esc(u.item)}</strong>: ${esc(STATE_LABEL[u.state]||u.state)}${u.reason?` (${esc(u.reason)})`:""}</li>`):SECTIONS.filter(([k])=>(c.sec[k]||{}).s!=="available").map(([k,l])=>`<li><strong>${esc(l)}</strong>: ${esc(STATE_LABEL[(c.sec[k]||{}).s]||"not found")}${(c.sec[k]||{}).n?` (${esc(c.sec[k].n)})`:""}</li>`)).join("");
  $("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / ${esc(c.n)}</nav>
  <div class="hero"><h1>${esc(c.n)}</h1><div class="sub">Org. ${c.o}${c.b?` · trading as ${esc(c.b)}`:""}${site?" · "+link(site.v,host(site.v)):""}</div>
  <div class="dots" style="margin-top:8px">${SECTIONS.map(([k,l])=>`<span class="dot ${esc((c.sec[k]||{}).s)}">${esc(l)}: ${esc(STATE_LABEL[(c.sec[k]||{}).s]||"")}</span>`).join("")}</div>
  ${sigHtml}
  <div class="parts" aria-label="Summary">${partsHtml||"<p>No supported summary.</p>"}</div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;align-items:center"><label class="cmp"><input type="checkbox" id="pcmp" ${cmp.has(c.o)?"checked":""}> Add to compare</label>${link("https://data.brreg.no/enhetsregisteret/api/enheter/"+c.o,"Official register record")}<a href="#" id="dl">Download this profile (JSON)</a></div></div>
  <div class="cols">
   <section class="box" aria-labelledby="h-acc"><h2 id="h-acc">Annual accounts ${badge(c,"accounts")}</h2>${acc||"<p class='note'>No filed figures returned by the Register of Company Accounts.</p>"}${docsHtml}${note(c,"accounts")}</section>
   <section class="box" aria-labelledby="h-id"><h2 id="h-id">Legal identity ${badge(c,"identity")}</h2><dl class="facts">${ident}</dl>${note(c,"identity")}</section>
   <section class="box" aria-labelledby="h-people"><h2 id="h-people">Leadership ${badge(c,"people")}</h2>${roles?`<ul class="plain">${roles}</ul>`:"<p class='note'>No active roles registered.</p>"}${places?`<h3>Registered workplaces</h3><ul class="plain">${places}</ul>`:""}</section>
   <section class="box" aria-labelledby="h-web"><h2 id="h-web">Website and company profiles ${badge(c,"website")}</h2>${site?`<p>${link(site.v)}${cite(c,[site.i])}</p>`:""}${proofs?`<ul class="plain">${proofs}</ul>`:""}${extra?`<ul class="plain" style="margin-top:6px">${extra}</ul>`:""}${profiles?`<h3>Profiles linked from the verified site</h3><ul class="plain">${profiles}</ul>`:""}${note(c,"website")}</section>
   <section class="box" aria-labelledby="h-hire"><h2 id="h-hire">Hiring ${badge(c,"hiring")}</h2>${jobs?`<ul class="plain">${jobs}</ul>`:""}${careers?`<h3>Careers pages</h3><ul class="plain">${careers}</ul>`:""}${!jobs&&!careers?"<p class='note'>No active job ad found.</p>":""}${note(c,"hiring")}</section>
   <section class="box" aria-labelledby="h-act"><h2 id="h-act">Dated activity and register history ${badge(c,"activity")}</h2>${acts?`<ol class="tl">${acts}</ol>`:"<p class='note'>No dated activity found.</p>"}</section>
   <section class="box" aria-labelledby="h-chg"><h2 id="h-chg">Changes since the previous run</h2>${c.run.prev?(changes?`<ul class="plain">${changes}</ul>`:"<p class='note'>No changes since run "+esc(c.run.prev)+".</p>"):"<p class='note'>First observation: no previous run to compare.</p>"}</section>
   <section class="box" aria-labelledby="h-unk"><h2 id="h-unk">What could not be found</h2>${unkRows?`<ul class="plain">${unkRows}</ul>`:"<p class='note'>Every section has supported data.</p>"}${c.err.length?`<p class="note">Errors: ${esc(c.err.join("; "))}</p>`:""}</section>
  </div>
  <section class="box" style="margin-top:12px" aria-labelledby="h-ev"><h2 id="h-ev">All evidence: ${c.cl.length} facts from ${Object.keys(c.ev).length} source excerpts</h2><details><summary>Show every fact with its source</summary><div class="tblwrap"><table class="tbl"><thead><tr><th scope="col">Fact</th><th scope="col">Source</th><th scope="col">Retrieved</th></tr></thead><tbody>${c.cl.map(x=>{const ev=c.ev[x.e[0]]||{};return `<tr><td style="white-space:normal;text-align:left">${esc(x.d)}${cite(c,[x.i])}</td><td style="text-align:left">${link(ev.u,String(ev.u||"").replace(/^https?:\/\//,"").slice(0,48))}</td><td>${esc(String(ev.r||"").slice(0,10))}</td></tr>`}).join("")}</tbody></table></div></details></section>
  <footer class="foot">Run ${esc(c.run.id)} · completed ${esc(c.run.at)}${c.run.prev?` · compared with ${esc(c.run.prev)}`:""}. Every number and name is copied from the cited source; nothing is estimated. The numbered buttons open the exact excerpt, URL, retrieval time and content hash.</footer>`;
  wireCites(()=>c);const pc=$("#pcmp");pc.onchange=()=>{if(!toggleCmp(c.o,pc.checked))pc.checked=false};
  $("#dl").onclick=e=>{e.preventDefault();const blob=new Blob([JSON.stringify({organisation_number:c.o,legal_name:c.n,summary:c.sum,signals:c.sig,facts:c.cl.map(x=>({fact:x.d,field:x.f,effective:x.t,evidence:x.e.map(id=>c.ev[id])}))},null,1)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`signalpost-${c.o}.json`;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},500)};
  $("#view").focus({preventScroll:true});window.scrollTo(0,0)}
function compare(){document.title="Compare · Signalpost";const cs=[...cmp].map(o=>byOrg[o]).filter(Boolean);citeIndex={};
  const picker=`<form class="cmpbar" id="cmpform" role="search"><label class="sr" for="cmpq">Add a company to the comparison</label><input id="cmpq" list="cmplist" placeholder="Add a company: name or organisation number" autocomplete="off"><datalist id="cmplist">${C.slice(0,2000).map(c=>`<option value="${esc(c.o)}">${esc(c.n)}</option>`).join("")}</datalist><button class="btn small" type="submit">Add</button>${cs.length?`<button class="btn ghost small" type="button" id="cmpclear2">Clear all</button>`:""}</form>`;
  if(!cs.length){$("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / Compare</nav>${picker}<div class="empty"><p><strong>Nothing to compare yet.</strong></p><p>Tick Compare on up to four companies, or add one above.</p><a class="btn" href="#/">Browse companies</a></div>`;wirePicker();return}
  const row=(label,fn,diff)=>{const vals=cs.map(c=>fn(c));const differs=diff&&new Set(vals.map(v=>v.replace(/<sup[\s\S]*?<\/sup>/g,""))).size>1;return `<tr><th scope="row">${esc(label)}</th>${vals.map(v=>`<td${differs?' class="diff"':""}>${v}</td>`).join("")}</tr>`};
  const accv=(c,f)=>{const a=latestAcc(c);if(!a)return null;return f==="revenue"?a:c.cl.find(z=>z.f===f&&z.year===a.year&&z.account_type===a.account_type)};
  const nf=`<span class="note">not found</span>`;
  const show=(c,x,fmt)=>x?(fmt?fmt(x):esc(x.d))+cite(c,[x.i]):nf;
  const role=(c,code)=>{const x=claims(c,"role").find(r=>r.role_code===code);return x?esc(x.d.split(": ").pop())+cite(c,[x.i]):nf};
  $("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / Compare</nav>${picker}<div class="tblwrap"><table class="cmpt"><caption class="sr">Side-by-side comparison; shaded rows differ between the companies</caption><thead><tr><th scope="col">Company</th>${cs.map(c=>`<th scope="col"><a href="#/c/${c.o}">${esc(c.n)}</a><div class="sub">${c.o}</div><button type="button" class="chipbtn" data-rm="${c.o}" aria-label="Remove ${esc(c.n)} from the comparison">Remove</button></th>`).join("")}</tr></thead><tbody>
  ${row("Industry",c=>{const x=first(c,"industry_en")||first(c,"industry");return show(c,x,y=>esc(y.v||y.d))},true)}${row("Location",c=>show(c,first(c,"municipality")),true)}${row("Founded",c=>show(c,first(c,"founded")),true)}${row("Employees",c=>show(c,first(c,"employees_registered"),x=>esc(x.v)),true)}
  ${row("Revenue (latest)",c=>show(c,accv(c,"revenue"),x=>esc(nok(x.v))+" "+esc(x.year)+(x.account_type==="KONSERN"?" group":"")),true)}${row("Operating result",c=>show(c,accv(c,"operating_result"),x=>esc(nok(x.v))),true)}${row("Net result",c=>show(c,accv(c,"net_result"),x=>esc(nok(x.v))),true)}${row("Equity",c=>show(c,accv(c,"equity"),x=>esc(nok(x.v))),true)}
  ${row("Chief executive",c=>role(c,"DAGL"))}${row("Chair",c=>role(c,"LEDE"))}${row("Workplaces",c=>claims(c,"workplace").length?String(claims(c,"workplace").length):nf,true)}
  ${row("Website",c=>show(c,first(c,"official_website"),x=>link(x.v,host(x.v))))}${row("Profiles",c=>claims(c,"social_profile").map(x=>esc(x.platform)+cite(c,[x.i])).join(", ")||nf)}
  ${row("Open job ads",c=>claims(c,"job_posting").length?String(claims(c,"job_posting").length):nf,true)}${row("Signals",c=>c.sig.map(s=>esc(s.t)+cite(c,s.c)).join("<br>")||`<span class="note">none</span>`)}${row("Changes",c=>c.run.prev?(String(c.ch.filter(x=>x.m!=="low").length||"none")):"first run")}
  </tbody></table></div><p class="meta">Shaded cells differ between the companies. The numbered buttons open the exact source excerpt, URL, retrieval time and content hash.</p>`;
  wireCites(ids=>cs.find(c=>c.cl.some(x=>ids.includes(x.i))));wirePicker();
  document.querySelectorAll("[data-rm]").forEach(b=>b.onclick=()=>{toggleCmp(b.dataset.rm,false);compare()})}
function wirePicker(){const f=$("#cmpform");if(!f)return;f.onsubmit=e=>{e.preventDefault();const q=fold($("#cmpq").value.trim());if(!q)return;const digits=q.replace(/\D/g,"");const hit=byOrg[digits]||C.find(c=>fold(c.n)===q)||C.find(c=>hay(c).includes(q));if(!hit){toast("No company matches that name or number");return}if(cmp.has(hit.o)){toast("Already in the comparison");return}if(toggleCmp(hit.o,true))compare()};const cl=$("#cmpclear2");if(cl)cl.onclick=()=>{cmp.clear();saveCmp();compare()}}
function route(){closeDrawer();const h=location.hash||"#/";updTray();if(h.startsWith("#/c/"))return profile(decodeURIComponent(h.slice(4)));if(h==="#/compare")return compare();document.title=DATA.meta&&DATA.meta.count?`Signalpost · ${DATA.meta.count} companies`:"Signalpost";list()}
window.addEventListener("hashchange",route);let tmr;$("#q").addEventListener("input",()=>{clearTimeout(tmr);tmr=setTimeout(goList,120)});
$("#searchform").onsubmit=e=>{e.preventDefault();const digits=$("#q").value.replace(/\D/g,"");if(digits.length===9&&byOrg[digits]){location.hash="#/c/"+digits;return}const rows=matches();if(rows.length===1){location.hash="#/c/"+rows[0].o;return}goList()};
$("#cmpclear").onclick=()=>{cmp.clear();saveCmp();route()};
$("#theme").onclick=()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;r.dataset.theme=dark?"light":"dark"};
const m=DATA.meta;$("#meta").textContent=`${m.count} companies${m.run?" · run "+m.run:""}${m.completed?" · "+String(m.completed).slice(0,10):""}`;
renderFilters();updTray();route();
</script>
</body>
</html>
"""
