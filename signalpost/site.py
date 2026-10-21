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


def _project(env: dict[str, Any]) -> dict[str, Any]:
    claims = []
    used_evidence: set[str] = set()
    for c in env.get("claims", []):
        item = {"i": c["id"], "f": c["field"], "s": c["section"], "d": c.get("display") or _short(c.get("value")),
                "e": c.get("evidence_ids", []), "t": c.get("effective_at") or c.get("event_date"), "p": c.get("reporting_period")}
        for key in ("url", "platform", "role_code", "account_type", "year", "location", "expires", "municipality", "employees",
                    "proof_kind", "carried_forward_from"):
            if c.get(key) not in (None, ""):
                item[key] = c[key]
        if isinstance(c.get("value"), (int, float)) and not isinstance(c.get("value"), bool):
            item["v"] = c["value"]
        elif c["field"] in ("official_website", "additional_website", "careers_page", "social_profile"):
            item["v"] = c.get("normalized_url") or c.get("value")
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
    return {
        "o": env["organisation_number"], "n": env.get("legal_name") or "(unknown)", "b": env.get("public_brand"), "st": env.get("status"),
        "sec": {k: {"s": v.get("state"), "n": v.get("note"), "c": v.get("claims")} for k, v in env.get("sections", {}).items()},
        "sum": [{"t": s["text"], "c": s.get("claim_ids", [])} for s in env.get("summary", {}).get("sentences", [])],
        "unk": env.get("summary", {}).get("unknowns", []),
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
            "version": (report or {}).get("agent_version")}
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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<meta name="description" content="Evidence-first company profiles for Norwegian organisation numbers. Every fact links to its source.">
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14181f;--muted:#5b6472;--line:#e3e6eb;--accent:#0b5cad;--accent-ink:#fff;--ok:#127a3f;--warn:#9a5b00;--bad:#b42318;--chip:#eef3fa;--shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1318;--panel:#161b22;--ink:#e7ebf0;--muted:#9aa4b2;--line:#2a313c;--accent:#5aa2ff;--accent-ink:#0b1220;--ok:#3fbf7f;--warn:#e0a63b;--bad:#ff7a6e;--chip:#1d2633;--shadow:none}}
:root[data-theme=dark]{--bg:#0f1318;--panel:#161b22;--ink:#e7ebf0;--muted:#9aa4b2;--line:#2a313c;--accent:#5aa2ff;--accent-ink:#0b1220;--ok:#3fbf7f;--warn:#e0a63b;--bad:#ff7a6e;--chip:#1d2633;--shadow:none}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
a{color:var(--accent)}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:6px}
header.top{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);box-shadow:var(--shadow)}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
.bar{display:flex;gap:12px;align-items:center;padding:10px 0;flex-wrap:wrap}
.brand{font-weight:750;letter-spacing:-.02em;font-size:18px;display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--ink)}
.brand svg{width:22px;height:22px}
.search{flex:1 1 260px;display:flex}
.search input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink);font-size:16px;min-height:44px}
.meta{color:var(--muted);font-size:13px}
.filters{display:flex;gap:8px;flex-wrap:wrap;padding:0 0 10px}
.chipbtn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer;min-height:36px}
.chipbtn[aria-pressed=true]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
select.sort{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 10px;font-size:13px;min-height:36px}
main{padding:16px 0 90px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px;min-width:0}
.card h3{margin:0;font-size:16px;line-height:1.3;overflow-wrap:anywhere}
.card h3 a{text-decoration:none;color:var(--ink)}.card h3 a:hover{color:var(--accent)}
.sub{color:var(--muted);font-size:13px;overflow-wrap:anywhere}
.kpis{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--muted)}.kpis b{font-size:15px;display:block;color:var(--ink)}
.dots{display:flex;gap:6px;flex-wrap:wrap}
.dot{font-size:11.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.dot.available{color:var(--ok);border-color:var(--ok)}
.dot.ambiguous,.dot.blocked{color:var(--warn);border-color:var(--warn)}
.dot.failed{color:var(--bad);border-color:var(--bad)}
.cardfoot{display:flex;justify-content:space-between;align-items:center;margin-top:auto;gap:8px;flex-wrap:wrap}
label.cmp{display:flex;gap:6px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer;min-height:40px}
label.cmp input{width:18px;height:18px}
.btn{border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);border-radius:10px;padding:8px 14px;font-weight:600;cursor:pointer;min-height:40px;text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-size:14px}
.btn.ghost{background:transparent;color:var(--accent)}
.tray{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);box-shadow:0 -4px 16px rgba(0,0,0,.08);padding:10px 0;display:none;z-index:6}
.tray .wrap{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.empty{padding:40px 16px;text-align:center;color:var(--muted)}
.crumbs{margin:0 0 10px;font-size:14px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow)}
.hero h1{margin:0 0 4px;font-size:clamp(20px,3vw,28px);letter-spacing:-.02em;line-height:1.2;overflow-wrap:anywhere}
.summary{font-size:16px;line-height:1.65;margin:12px 0 0;max-width:80ch}
.summary .s{margin:0 0 6px}
sup.cite{font-size:11px;margin-left:2px;line-height:0}
sup.cite button{border:0;background:var(--chip);color:var(--accent);border-radius:6px;padding:1px 5px;cursor:pointer;font:inherit;font-weight:650;min-width:22px;min-height:22px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:860px){.cols{grid-template-columns:1fr}}
section.box{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);min-width:0}
section.box h2{font-size:15px;margin:0 0 8px;display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}
.note{color:var(--muted);font-size:13px;margin:4px 0 0}
dl.facts{display:grid;grid-template-columns:minmax(110px,36%) 1fr;gap:6px 12px;margin:0}
dl.facts dt{color:var(--muted);font-size:13px}dl.facts dd{margin:0;overflow-wrap:anywhere}
ul.plain{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
ul.plain li{overflow-wrap:anywhere}
.tbl{width:100%;border-collapse:collapse;font-size:13.5px}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.src{font-size:12px;color:var(--muted)}
.bars{display:flex;align-items:flex-end;gap:8px;height:64px;margin:6px 0 20px;max-width:320px}
.bars div{flex:1;background:var(--accent);opacity:.75;border-radius:4px 4px 0 0;min-height:2px;position:relative}
.bars div.neg{background:var(--bad)}
.bars span{position:absolute;bottom:-18px;left:0;right:0;text-align:center;font-size:11px;color:var(--muted)}
.drawer{position:fixed;right:0;top:0;bottom:0;width:min(520px,100%);background:var(--panel);border-left:1px solid var(--line);box-shadow:-8px 0 24px rgba(0,0,0,.12);transform:translateX(105%);transition:transform .18s ease;z-index:10;display:flex;flex-direction:column;visibility:hidden}
.drawer.open{transform:none;visibility:visible}
.drawer header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
.drawer .body{padding:14px 16px;overflow:auto}
.ev{border:1px solid var(--line);border-radius:12px;padding:10px;margin:0 0 10px}
.ev q{display:block;background:var(--chip);border-radius:8px;padding:8px;margin:6px 0;font-size:13px;quotes:none;overflow-wrap:anywhere;white-space:pre-wrap}
.ev .k{color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.25);opacity:0;pointer-events:none;transition:opacity .18s;z-index:9}
.scrim.open{opacity:1;pointer-events:auto}
.cmpt{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}
.cmpt th,.cmpt td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;font-size:14px;overflow-wrap:anywhere;min-width:140px}
.cmpt tbody th{color:var(--muted);font-weight:600;min-width:120px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px}
.change{padding-left:8px;border-left:3px solid var(--line)}.change.high{border-left-color:var(--bad)}.change.medium{border-left-color:var(--warn)}
footer.foot{color:var(--muted);font-size:12.5px;padding:24px 0}
@media (prefers-reduced-motion:reduce){.drawer,.scrim{transition:none}}
#view:focus{outline:none}
@media (max-width:640px){header.top{position:static}.bar .meta{display:none}.filters{flex-wrap:nowrap;overflow-x:auto;padding-bottom:12px;scrollbar-width:none}.filters>*{flex:0 0 auto}.hero{padding:14px}.summary{font-size:15.5px}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="bar">
    <a class="brand" href="#/" aria-label="Signalpost home"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>Signalpost</a>
    <form class="search" role="search" onsubmit="return false"><label class="sr" for="q">Search companies</label>
      <input id="q" type="search" placeholder="Name, org. number, brand, place or person" autocomplete="off"></form>
    <span class="meta" id="meta"></span>
    <button class="chipbtn" id="theme" type="button" aria-label="Toggle dark mode">◐</button>
  </div>
  <div class="filters" id="filters" role="group" aria-label="Filters and sorting"></div>
</div></header>
<main><div class="wrap" id="view" tabindex="-1"></div></main>
<div class="tray" id="tray" role="region" aria-label="Compare tray"><div class="wrap"><span id="traytext"></span><a class="btn" href="#/compare">Compare</a><button class="btn ghost" id="cmpclear" type="button">Clear</button></div></div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawertitle"><header><strong id="drawertitle">Evidence</strong><button class="btn ghost" id="drawerclose" type="button">Close</button></header><div class="body" id="drawerbody"></div></aside>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("data").textContent);
const C=DATA.companies;const byOrg=Object.fromEntries(C.map(c=>[c.o,c]));
const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const SECTIONS=[["identity","Identity"],["accounts","Accounts"],["people","People & places"],["website","Website"],["hiring","Hiring"],["activity","Activity"]];
const STATE_LABEL={available:"found",not_available:"not found",blocked:"blocked",ambiguous:"ambiguous",failed:"failed",not_applicable:"n/a"};
function nok(v){if(v==null)return"—";const a=Math.abs(v),s=v<0?"-":"";if(a>=1e9)return`NOK ${s}${(a/1e9).toFixed(1)} bn`;if(a>=1e6)return`NOK ${s}${(a/1e6).toFixed(1)} m`;if(a>=1e3)return`NOK ${s}${(a/1e3).toFixed(0)} k`;return`NOK ${s}${a.toFixed(0)}`}
const claims=(c,f)=>c.cl.filter(x=>x.f===f);const first=(c,f)=>c.cl.find(x=>x.f===f);
const safeUrl=u=>/^https?:\/\//i.test(String(u||""))?String(u):"#";
const host=u=>String(u||"").replace(/^https?:\/\/(www\.)?/,"").replace(/\/$/,"");
function latestAcc(c){const rows=c.cl.filter(x=>x.f==="revenue");if(!rows.length)return null;const grp=rows.filter(r=>r.account_type==="KONSERN");const use=(grp.length?grp:rows).slice();use.sort((a,b)=>String(b.year).localeCompare(String(a.year)));return use[0]}
function emp(c){const e=first(c,"employees_registered");return e?e.v:null}
function hay(c){if(!c._s)c._s=[c.o,c.n,c.b,(first(c,"municipality")||{}).d,(first(c,"industry")||{}).d,...claims(c,"role").map(r=>r.d),(first(c,"official_website")||{}).v].join(" ").toLowerCase();return c._s}
const FILTERS=[["website","Verified website",c=>(c.sec.website||{}).s==="available"],["hiring","Hiring now",c=>claims(c,"job_posting").length>0||claims(c,"careers_page").length>0],["profiles","Social profiles",c=>claims(c,"social_profile").length>0],["accounts","Filed accounts",c=>(c.sec.accounts||{}).s==="available"],["changes","Changed since last run",c=>c.ch.some(x=>x.m!=="low")]];
let active=new Set();let sortKey="evidence";let cmp=new Set();
try{cmp=new Set(JSON.parse(sessionStorage.getItem("signalpost-cmp")||"[]").filter(o=>byOrg[o]))}catch(e){}
function saveCmp(){try{sessionStorage.setItem("signalpost-cmp",JSON.stringify([...cmp]))}catch(e){}updTray()}
function updTray(){const t=$("#tray");if(cmp.size){t.style.display="block";$("#traytext").textContent=`${cmp.size} selected to compare (max 4)`}else t.style.display="none"}
function toggleCmp(o,on){if(on){if(cmp.size>=4&&!cmp.has(o)){alert("You can compare up to 4 companies.");return false}cmp.add(o)}else cmp.delete(o);saveCmp();return true}
function renderFilters(){const f=$("#filters");f.innerHTML=FILTERS.map(([k,l])=>`<button type="button" class="chipbtn" data-f="${k}" aria-pressed="${active.has(k)}">${esc(l)}</button>`).join("")+`<label class="sr" for="sort">Sort by</label><select id="sort" class="sort"><option value="evidence">Most evidence</option><option value="name">Name A–Z</option><option value="revenue">Revenue</option><option value="employees">Employees</option></select>`;
  f.querySelectorAll("[data-f]").forEach(b=>b.onclick=()=>{const k=b.dataset.f;active.has(k)?active.delete(k):active.add(k);renderFilters();if(location.hash.length>2)location.hash="#/";else route()});
  const s=$("#sort");s.value=sortKey;s.onchange=()=>{sortKey=s.value;route()}}
function list(){const q=$("#q").value.trim().toLowerCase();let rows=C.filter(c=>(!q||q.split(/\s+/).every(t=>hay(c).includes(t)))&&FILTERS.every(([k,,fn])=>!active.has(k)||fn(c)));
  const val={evidence:c=>-c.cl.length,name:c=>c.n,revenue:c=>-((latestAcc(c)||{}).v??-1e18),employees:c=>-(emp(c)??-1)}[sortKey];
  rows.sort((a,b)=>{const x=val(a),y=val(b);return x<y?-1:x>y?1:0});
  const v=$("#view");if(!rows.length){v.innerHTML=`<div class="empty"><p><strong>No companies match.</strong></p><p>Try another name or organisation number, or clear the filters.</p></div>`;return}
  const shown=rows.slice(0,240);
  v.innerHTML=`<p class="meta">${rows.length} of ${C.length} companies${rows.length>240?" — first 240 shown, refine the search":""}</p><div class="grid">`+shown.map(card).join("")+`</div>`;
  v.querySelectorAll("input[data-cmp]").forEach(i=>i.onchange=()=>{if(!toggleCmp(i.dataset.cmp,i.checked))i.checked=false})}
function card(c){const acc=latestAcc(c),e=emp(c),site=first(c,"official_website"),jobs=claims(c,"job_posting").length;
  return `<article class="card"><h3><a href="#/c/${c.o}">${esc(c.n)}</a></h3>${c.b?`<div class="sub">trading as ${esc(c.b)}</div>`:""}<div class="sub">${c.o} · ${esc((first(c,"municipality")||{}).d||"")}</div>
  <div class="kpis"><span><b>${acc?esc(nok(acc.v)):"—"}</b>revenue ${acc?esc(acc.year)+(acc.account_type==="KONSERN"?" group":""):""}</span><span><b>${e??"—"}</b>employees</span><span><b>${jobs||"—"}</b>job ads</span></div>
  ${site?`<div class="sub">Website: <a href="${esc(safeUrl(site.v))}" rel="noopener noreferrer nofollow" target="_blank">${esc(host(site.v))}</a></div>`:""}
  <div class="dots">${SECTIONS.map(([k,l])=>{const s=(c.sec[k]||{}).s||"not_available";return`<span class="dot ${esc(s)}" title="${esc(l)}: ${esc(STATE_LABEL[s]||s)}">${esc(l)}</span>`}).join("")}</div>
  <div class="cardfoot"><a href="#/c/${c.o}" class="btn ghost">Open profile</a><label class="cmp"><input type="checkbox" data-cmp="${c.o}" ${cmp.has(c.o)?"checked":""}> Compare</label></div></article>`}
let citeIndex={};
function cite(c,ids){ids=(ids||[]).filter(Boolean);if(!ids.length)return"";const n=ids.map(id=>{if(!(id in citeIndex))citeIndex[id]=Object.keys(citeIndex).length+1;return citeIndex[id]});const uniq=[...new Set(n)].sort((a,b)=>a-b);const label=uniq.length>4?`${uniq[0]}–${uniq[uniq.length-1]}`:uniq.join(",");
  return `<sup class="cite"><button type="button" data-ev="${esc(ids.join(","))}" aria-label="Show ${ids.length} source${ids.length>1?"s":""}">${label}</button></sup>`}
function showEvidence(c,ids){const cl=c.cl.filter(x=>ids.includes(x.i));
  $("#drawerbody").innerHTML=cl.map(x=>{const evs=x.e.map(id=>c.ev[id]).filter(Boolean);return `<div class="ev"><div><strong>${esc(x.d)}</strong></div>${x.p?`<div class="k">Reporting period ${esc(x.p)}</div>`:""}${x.t?`<div class="k">Effective ${esc(x.t)}</div>`:""}${x.carried_forward_from?`<div class="k">Carried forward from run ${esc(x.carried_forward_from)}: this run could not re-check the source</div>`:""}
  ${evs.map(ev=>`<q>${esc(ev.x)}</q><div class="k">Source: <a href="${esc(safeUrl(ev.u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(ev.u)}</a></div><div class="k">${esc(ev.c)} · retrieved ${esc(ev.r)} · sha256 ${esc(ev.h)}… · ${esc(ev.l)} · ${esc(ev.m)}${ev.tf?" · "+esc(ev.tf):""}</div>`).join("")}</div>`}).join("")||"<p>No evidence.</p>";
  $("#drawertitle").textContent=`Evidence for ${cl.length} claim${cl.length===1?"":"s"}`;$("#drawer").classList.add("open");$("#scrim").classList.add("open");$("#drawerclose").focus()}
function closeDrawer(){$("#drawer").classList.remove("open");$("#scrim").classList.remove("open")}
$("#drawerclose").onclick=closeDrawer;$("#scrim").onclick=closeDrawer;document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDrawer()});
function wireCites(find){document.querySelectorAll("[data-ev]").forEach(b=>b.onclick=()=>{const ids=b.dataset.ev.split(",");const c=find(ids);if(c)showEvidence(c,ids)})}
const badge=(c,k)=>{const s=(c.sec[k]||{}).s||"not_available";return `<span class="dot ${esc(s)}">${esc(STATE_LABEL[s]||s)}</span>`};
const note=(c,k)=>{const n=(c.sec[k]||{}).n;return n?`<p class="note">${esc(n)}</p>`:""};
function fact(c,f,label){const xs=claims(c,f);if(!xs.length)return"";return `<dt>${esc(label)}</dt><dd>${xs.map(x=>esc(x.d)+cite(c,[x.i])).join("<br>")}</dd>`}
const link=(u,t)=>`<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener noreferrer nofollow">${esc(t||u)}</a>`;
function profile(o){const c=byOrg[o];citeIndex={};if(!c){$("#view").innerHTML=`<div class="empty">Unknown organisation number ${esc(o)}. <a href="#/">Back to the list</a></div>`;return}
  const site=first(c,"official_website");
  const ident=[["legal_name","Legal name"],["organisation_number","Org. number"],["public_brand","Public brand"],["legal_form","Legal form"],["business_address","Business address"],["postal_address","Postal address"],["industry","Industry"],["secondary_industry","Other industries"],["founded","Founded"],["registered_date","Registered"],["employees_registered","Employees (register)"],["share_capital","Share capital"],["vat_registered","VAT"],["business_register","Business register"],["part_of_group","Group"],["group_parent","Parent"],["group_ultimate_parent","Ultimate parent"],["group_subsidiary","Subsidiaries"],["former_name","Former names"],["registered_email","Registered e-mail"],["registered_phone","Registered phone"],["registered_website","Registered website"],["statutory_purpose","Statutory purpose"],["bankrupt","Bankruptcy"],["under_liquidation","Liquidation"]].map(([f,l])=>fact(c,f,l)).join("");
  const years=[...new Set(c.cl.filter(x=>x.f==="accounting_period").map(x=>x.year+"|"+x.account_type))].sort().reverse();
  const accFields=[["revenue","Revenue"],["operating_result","Operating result"],["profit_before_tax","Profit before tax"],["net_result","Net result"],["total_assets","Total assets"],["equity","Equity"],["debt","Debt"],["cash","Cash"],["salary_costs","Salary costs"]];
  let acc="";if(years.length){const cols=years.map(y=>y.split("|"));acc=`<div class="tblwrap"><table class="tbl"><caption class="sr">Filed annual accounts</caption><thead><tr><th scope="col">NOK</th>${cols.map(([y,t])=>`<th scope="col">${esc(y)}${t==="KONSERN"?" group":""}</th>`).join("")}</tr></thead><tbody>`+accFields.map(([f,l])=>`<tr><th scope="row">${esc(l)}</th>${cols.map(([y,t])=>{const x=c.cl.find(z=>z.f===f&&z.year===y&&z.account_type===t);return `<td>${x?esc(nok(x.v))+cite(c,[x.i]):"—"}</td>`}).join("")}</tr>`).join("")+`</tbody></table></div>`;
    const rev=cols.filter(([y,t])=>t!=="KONSERN").map(([y,t])=>c.cl.find(z=>z.f==="revenue"&&z.year===y&&z.account_type===t)).filter(Boolean).reverse();const mx=Math.max(...rev.map(r=>Math.abs(r.v)),1);
    if(rev.length>1)acc=`<div class="bars" role="img" aria-label="Revenue by year: ${esc(rev.map(r=>r.year+" "+nok(r.v)).join(", "))}">${rev.map(r=>`<div class="${r.v<0?"neg":""}" style="height:${Math.max(3,Math.abs(r.v)/mx*100)}%" title="${esc(r.year)}: ${esc(nok(r.v))}"><span>${esc(r.year)}</span></div>`).join("")}</div>`+acc}
  const li=(xs,fn)=>xs.map(x=>`<li>${fn(x)}${cite(c,[x.i])}</li>`).join("");
  const roles=li(claims(c,"role"),x=>esc(x.d));
  const places=li(claims(c,"workplace"),x=>esc(x.d)+(x.employees!=null?` <span class="pill">${esc(x.employees)} employees</span>`:""));
  const profiles=li(claims(c,"social_profile"),x=>`<span class="pill">${esc(x.platform)}</span> `+link(x.v,host(x.v)));
  const proofs=li(claims(c,"website_identity_proof"),x=>esc(x.d));
  const extra=li(claims(c,"additional_website"),x=>"Also verified: "+link(x.v))+li(claims(c,"website_description"),x=>"“"+esc(x.d)+"”")+li(claims(c,"website_email"),x=>esc(x.d));
  const jobs=claims(c,"job_posting").sort((a,b)=>String(b.t||"").localeCompare(String(a.t||""))).map(x=>`<li>${link(x.url,x.d)}${cite(c,[x.i])}<div class="src">published ${esc(x.t||"?")}${x.expires?` · apply by ${esc(x.expires)}`:""}</div></li>`).join("");
  const careers=li(claims(c,"careers_page"),x=>link(x.v));
  const acts=[...claims(c,"website_post"),...claims(c,"registry_role_change"),...claims(c,"job_posting")].filter(x=>x.t).sort((a,b)=>String(b.t).localeCompare(String(a.t))).slice(0,12).map(x=>`<li><span class="pill">${esc(x.t)}</span> ${esc(x.f==="job_posting"?"Job ad: "+x.d:x.d.replace(/^\d{4}-\d\d-\d\d — /,""))}${cite(c,[x.i])}</li>`).join("");
  const changes=c.ch.map(x=>`<li class="change ${esc(x.m)}">${esc(x.d)} <span class="pill">${esc(x.m)}</span>${cite(c,x.c.filter(id=>c.cl.some(z=>z.i===id)))}</li>`).join("");
  const unk=SECTIONS.filter(([k])=>(c.sec[k]||{}).s!=="available").map(([k,l])=>`<li><strong>${esc(l)}</strong>: ${esc(STATE_LABEL[(c.sec[k]||{}).s]||"not found")}${(c.sec[k]||{}).n?` — ${esc(c.sec[k].n)}`:""}</li>`).join("");
  const sum=c.sum.map(s=>`<p class="s">${esc(s.t)}${cite(c,s.c)}</p>`).join("");
  $("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / ${esc(c.n)}</nav>
  <div class="hero"><h1>${esc(c.n)}</h1><div class="sub">Org. ${c.o}${c.b?` · trading as ${esc(c.b)}`:""}${site?" · "+link(site.v,host(site.v)):""}</div>
  <div class="dots" style="margin-top:8px">${SECTIONS.map(([k,l])=>`<span class="dot ${esc((c.sec[k]||{}).s)}">${esc(l)}: ${esc(STATE_LABEL[(c.sec[k]||{}).s]||"")}</span>`).join("")}</div>
  <div class="summary" aria-label="Summary">${sum||"<p>No supported summary.</p>"}</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center"><label class="cmp"><input type="checkbox" id="pcmp" ${cmp.has(c.o)?"checked":""}> Add to compare</label>${link("https://data.brreg.no/enhetsregisteret/api/enheter/"+c.o,"Official register record")}</div></div>
  <div class="cols">
   <section class="box" aria-labelledby="h-acc"><h2 id="h-acc">Annual accounts ${badge(c,"accounts")}</h2>${acc||"<p class='note'>No filed accounts returned by Regnskapsregisteret.</p>"}${note(c,"accounts")}</section>
   <section class="box" aria-labelledby="h-id"><h2 id="h-id">Legal identity ${badge(c,"identity")}</h2><dl class="facts">${ident}</dl>${note(c,"identity")}</section>
   <section class="box" aria-labelledby="h-people"><h2 id="h-people">Leadership ${badge(c,"people")}</h2>${roles?`<ul class="plain">${roles}</ul>`:"<p class='note'>No active roles registered.</p>"}${places?`<h2 style="margin-top:12px">Registered workplaces</h2><ul class="plain">${places}</ul>`:""}</section>
   <section class="box" aria-labelledby="h-web"><h2 id="h-web">Website & company profiles ${badge(c,"website")}</h2>${site?`<p>${link(site.v)}${cite(c,[site.i])}</p>`:""}${proofs?`<ul class="plain">${proofs}</ul>`:""}${extra?`<ul class="plain" style="margin-top:6px">${extra}</ul>`:""}${profiles?`<h2 style="margin-top:12px">Profiles linked from the verified site</h2><ul class="plain">${profiles}</ul>`:""}${note(c,"website")}</section>
   <section class="box" aria-labelledby="h-hire"><h2 id="h-hire">Hiring ${badge(c,"hiring")}</h2>${jobs?`<ul class="plain">${jobs}</ul>`:""}${careers?`<p class="note">Careers pages</p><ul class="plain">${careers}</ul>`:""}${!jobs&&!careers?"<p class='note'>No active job ad found.</p>":""}${note(c,"hiring")}</section>
   <section class="box" aria-labelledby="h-act"><h2 id="h-act">Dated activity ${badge(c,"activity")}</h2>${acts?`<ul class="plain">${acts}</ul>`:"<p class='note'>No dated activity found.</p>"}</section>
   <section class="box" aria-labelledby="h-chg"><h2 id="h-chg">Changes since the previous run</h2>${c.run.prev?(changes?`<ul class="plain">${changes}</ul>`:"<p class='note'>No changes since run "+esc(c.run.prev)+".</p>"):"<p class='note'>First observation: no previous run to compare.</p>"}</section>
   <section class="box" aria-labelledby="h-unk"><h2 id="h-unk">What could not be found</h2>${unk?`<ul class="plain">${unk}</ul>`:"<p class='note'>Every section has supported data.</p>"}${c.err.length?`<p class="note">Errors: ${esc(c.err.join("; "))}</p>`:""}</section>
  </div>
  <section class="box" style="margin-top:12px" aria-labelledby="h-ev"><h2 id="h-ev">All evidence: ${c.cl.length} claims from ${Object.keys(c.ev).length} source excerpts</h2><details><summary>Show every claim with its source</summary><div class="tblwrap"><table class="tbl"><thead><tr><th scope="col">Claim</th><th scope="col">Source</th><th scope="col">Retrieved</th></tr></thead><tbody>${c.cl.map(x=>{const ev=c.ev[x.e[0]]||{};return `<tr><td style="white-space:normal;text-align:left">${esc(x.d)}${cite(c,[x.i])}</td><td style="text-align:left">${link(ev.u,String(ev.u||"").replace(/^https?:\/\//,"").slice(0,48))}</td><td>${esc(String(ev.r||"").slice(0,10))}</td></tr>`}).join("")}</tbody></table></div></details></section>
  <footer class="foot">Run ${esc(c.run.id)} · completed ${esc(c.run.at)}${c.run.prev?` · compared with ${esc(c.run.prev)}`:""}. Every number and name is copied from the cited source; nothing is estimated. Superscripts open the exact excerpt, URL, retrieval time and content hash.</footer>`;
  wireCites(()=>c);const pc=$("#pcmp");pc.onchange=()=>{if(!toggleCmp(c.o,pc.checked))pc.checked=false};
  $("#view").focus({preventScroll:true});window.scrollTo(0,0)}
function compare(){const cs=[...cmp].map(o=>byOrg[o]).filter(Boolean);citeIndex={};if(!cs.length){$("#view").innerHTML=`<div class="empty"><p><strong>Nothing to compare yet.</strong></p><p>Tick “Compare” on up to four companies.</p><a class="btn" href="#/">Browse companies</a></div>`;return}
  const row=(label,fn)=>`<tr><th scope="row">${esc(label)}</th>${cs.map(c=>`<td>${fn(c)}</td>`).join("")}</tr>`;
  const accv=(c,f)=>{const a=latestAcc(c);if(!a)return null;return f==="revenue"?a:c.cl.find(z=>z.f===f&&z.year===a.year&&z.account_type===a.account_type)};
  const show=(c,x,fmt)=>x?(fmt?fmt(x):esc(x.d))+cite(c,[x.i]):"—";
  const role=(c,code)=>{const x=claims(c,"role").find(r=>r.role_code===code);return x?esc(x.d.split(": ").pop())+cite(c,[x.i]):"—"};
  $("#view").innerHTML=`<nav class="crumbs" aria-label="Breadcrumb"><a href="#/">All companies</a> / Compare</nav><div class="tblwrap"><table class="cmpt"><caption class="sr">Side-by-side comparison</caption><thead><tr><th scope="col">Company</th>${cs.map(c=>`<th scope="col"><a href="#/c/${c.o}">${esc(c.n)}</a><div class="sub">${c.o}</div><button type="button" class="chipbtn" data-rm="${c.o}">Remove</button></th>`).join("")}</tr></thead><tbody>
  ${row("Location",c=>show(c,first(c,"municipality")))}${row("Industry",c=>show(c,first(c,"industry")))}${row("Founded",c=>show(c,first(c,"founded")))}${row("Employees",c=>show(c,first(c,"employees_registered"),x=>esc(x.v)))}
  ${row("Revenue (latest)",c=>show(c,accv(c,"revenue"),x=>esc(nok(x.v))+" "+esc(x.year)+(x.account_type==="KONSERN"?" group":"")))}${row("Operating result",c=>show(c,accv(c,"operating_result"),x=>esc(nok(x.v))))}${row("Net result",c=>show(c,accv(c,"net_result"),x=>esc(nok(x.v))))}${row("Equity",c=>show(c,accv(c,"equity"),x=>esc(nok(x.v))))}
  ${row("Chief executive",c=>role(c,"DAGL"))}${row("Chair",c=>role(c,"LEDE"))}${row("Workplaces",c=>claims(c,"workplace").length||"—")}
  ${row("Website",c=>show(c,first(c,"official_website"),x=>link(x.v,host(x.v))))}${row("Profiles",c=>claims(c,"social_profile").map(x=>esc(x.platform)+cite(c,[x.i])).join(", ")||"—")}
  ${row("Open job ads",c=>claims(c,"job_posting").length||"—")}${row("Changes",c=>c.run.prev?(c.ch.filter(x=>x.m!=="low").length||"none"):"first run")}
  </tbody></table></div><p class="meta">Superscript numbers open the exact source excerpt, URL, retrieval time and content hash.</p>`;
  wireCites(ids=>cs.find(c=>c.cl.some(x=>ids.includes(x.i))));
  document.querySelectorAll("[data-rm]").forEach(b=>b.onclick=()=>{toggleCmp(b.dataset.rm,false);compare()})}
function route(){closeDrawer();const h=location.hash||"#/";if(h.startsWith("#/c/"))return profile(decodeURIComponent(h.slice(4)));if(h==="#/compare")return compare();list()}
window.addEventListener("hashchange",route);let tmr;$("#q").addEventListener("input",()=>{clearTimeout(tmr);tmr=setTimeout(()=>{if(location.hash.length>2)location.hash="#/";else route()},120)});
$("#cmpclear").onclick=()=>{cmp.clear();saveCmp();route()};
$("#theme").onclick=()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;r.dataset.theme=dark?"light":"dark"};
const m=DATA.meta;$("#meta").textContent=`${m.count} companies${m.run?" · run "+m.run:""}${m.completed?" · "+String(m.completed).slice(0,10):""}`;
renderFilters();updTray();route();
</script>
</body>
</html>
"""
