"""Decision-useful synthesis built only from verified claims.

Every sentence carries the claim ids it rests on. Numbers in a sentence must come from a cited
claim value or from a percentage computed from two cited values; ``check_sentence`` enforces this
and drops any sentence that fails.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from .ledger import Ledger

MONTHS = None


def nok(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"NOK {sign}{value / 1_000_000_000:.1f} bn"
    if value >= 1_000_000:
        return f"NOK {sign}{value / 1_000_000:.1f} m"
    if value >= 1_000:
        return f"NOK {sign}{value / 1_000:.0f} k"
    return f"NOK {sign}{value:.0f}"


def _sentence(text: str, claim_ids: list[str], derived: dict[str, float] | None = None) -> dict[str, Any]:
    return {"text": text, "claim_ids": [c for c in claim_ids if c], "derived": derived or {}}


def check_sentence(sentence: dict[str, Any], ledger: Ledger) -> bool:
    """Every number written in the sentence must be backed by a cited claim (or a declared derivation)."""
    cited = [c for c in ledger.claims if c["id"] in set(sentence["claim_ids"])]
    if sentence["claim_ids"] and len(cited) != len(set(sentence["claim_ids"])):
        return False
    allowed: list[float] = []
    for claim in cited:
        allowed.extend(_numbers(claim.get("value")))
        allowed.extend(_numbers(claim.get("display")))
        for key in ("effective_at", "event_date", "year", "reporting_period"):
            allowed.extend(_numbers(claim.get(key)))
    allowed.extend(sentence.get("derived", {}).values())
    for number in re.findall(r"-?\d[\d,.]*", sentence["text"]):
        cleaned = number.replace(",", "").rstrip(".")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
        tolerance = 0.5 * 10 ** (-decimals) + 1e-9
        if not any(abs(value - a) <= tolerance or abs(abs(value) - abs(a)) <= tolerance for a in allowed):
            return False
    return True


def _numbers(value: Any) -> list[float]:
    out: list[float] = []
    if value is None:
        return out
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        v = float(value)
        return [v, v / 1_000, v / 1_000_000, v / 1_000_000_000, abs(v), abs(v) / 1_000, abs(v) / 1_000_000, abs(v) / 1_000_000_000]
    if isinstance(value, dict):
        for item in value.values():
            out.extend(_numbers(item))
        return out
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_numbers(item))
        return out
    for match in re.findall(r"-?\d[\d,.]*", str(value)):
        try:
            out.append(float(match.replace(",", "").rstrip(".")))
        except ValueError:
            pass
        for part in re.split(r"[-.:/]", match):
            if part.isdigit():
                out.append(float(part))
    return out


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    tolerance = max(0.051, abs(b) * 0.0006)
    return abs(a - b) <= tolerance or abs(abs(a) - abs(b)) <= tolerance


FORMS_EN = {"AS": "private limited company", "ASA": "public limited company", "ENK": "sole proprietorship", "ANS": "general partnership",
            "DA": "general partnership with shared liability", "SA": "cooperative", "STI": "foundation", "NUF": "Norwegian branch of a foreign company",
            "FLI": "association", "BRL": "housing cooperative", "ESEK": "condominium (eierseksjonssameie)", "KS": "limited partnership",
            "IKS": "inter-municipal company", "KF": "municipal enterprise", "SPA": "savings bank", "SF": "state enterprise",
            "BBL": "housing building cooperative", "SAM": "joint ownership", "VPFO": "securities fund", "PK": "pension fund",
            "GFS": "mutual insurance company", "KTRF": "trustee-registered association", "BA": "company with limited liability",
            "PRE": "shipping partnership", "OPMV": "special-purpose entity", "ADOS": "administrative unit", "ORGL": "organisational unit",
            "UTLA": "foreign entity", "TVAM": "jointly owned entity"}


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def build_summary(ledger: Ledger, ctx: dict[str, Any]) -> dict[str, Any]:
    s: list[dict[str, Any]] = []
    first = ledger.first
    name = first("legal_name")
    brand = first("public_brand")
    form = first("legal_form")
    municipality = first("municipality")
    industry = first("industry")
    founded = first("founded")
    if name:
        label = name["value"] + (f" (trading as {brand['value']})" if brand else "")
        form_en = FORMS_EN.get(form["value"]["code"], (form["value"]["description"] or "registered entity").lower()) if form else "registered entity"
        desc = f"{label} is {article(form_en)} {form_en}" + (f" ({form['value']['code']})" if form else "")
        ids = [name["id"], brand["id"] if brand else None, form["id"] if form else None]
        if municipality:
            desc += f" registered in {municipality['value'].title()}"
            ids.append(municipality["id"])
        if founded:
            desc += f", founded {founded['value'][:4]}"
            ids.append(founded["id"])
        if industry:
            desc += f", in the industry \u201c{industry['value']['description']}\u201d (NACE {industry['value']['code']})"
            ids.append(industry["id"])
        s.append(_sentence(desc + ".", ids))
    website_desc = first("website_description")
    purpose = first("statutory_purpose") or first("registered_activity")
    if website_desc:
        s.append(_sentence(f"Its own website describes it as: \u201c{_trim(website_desc['value'], 220)}\u201d", [website_desc["id"]]))
    elif purpose:
        s.append(_sentence(f"Registered purpose: \u201c{_trim(purpose['value'], 200)}\u201d", [purpose["id"]]))
    # finances: group accounts first when the company files them, then the legal entity's own accounts
    years = ctx.get("accounts") or []
    has_group = any(y.get("account_type") == "KONSERN" for y in years)
    for account_type in ("KONSERN", "SELSKAP"):
        rows = [y for y in years if y.get("account_type") == account_type]
        if not rows:
            continue
        latest = rows[0]
        parts, ids, derived = [], [], {}
        if "revenue" in latest:
            parts.append(f"revenue of {nok(latest['revenue']['value'])}")
            ids.append(latest["revenue"]["claim_id"])
            previous = rows[1] if len(rows) > 1 else None
            if previous and "revenue" in previous and previous["revenue"]["value"]:
                change = (latest["revenue"]["value"] - previous["revenue"]["value"]) / abs(previous["revenue"]["value"]) * 100
                derived["revenue_change_pct"] = round(change, 1)
                parts[-1] += f" ({'up' if change >= 0 else 'down'} {abs(round(change, 1))}% from {previous['year']})"
                ids.append(previous["revenue"]["claim_id"])
        if "operating_result" in latest:
            parts.append(f"an operating result of {nok(latest['operating_result']['value'])}")
            ids.append(latest["operating_result"]["claim_id"])
        if "net_result" in latest:
            parts.append(f"a net result of {nok(latest['net_result']['value'])}")
            ids.append(latest["net_result"]["claim_id"])
        if "equity" in latest:
            parts.append(f"equity of {nok(latest['equity']['value'])}")
            ids.append(latest["equity"]["claim_id"])
        if not parts:
            continue
        if has_group and account_type == "SELSKAP":
            s.append(_sentence("The parent company on its own reported " + _join(parts[:2]) + f" for {latest['year']}.", ids, derived))
        else:
            prefix = "The latest filed group accounts" if account_type == "KONSERN" else "The latest filed annual accounts"
            s.append(_sentence(f"{prefix} ({latest['year']}) show " + _join(parts) + ".", ids, derived))
        if "equity" in latest and latest["equity"]["value"] < 0 and not (has_group and account_type == "SELSKAP"):
            s.append(_sentence("Equity is negative in the latest filed accounts, a point to check before extending credit.",
                               [latest["equity"]["claim_id"]]))
    employees = first("employees_registered")
    if employees:
        s.append(_sentence(f"The register lists {employees['value']} employees" + (f" (as of {employees['effective_at']})." if employees.get("effective_at") else "."),
                           [employees["id"]]))
    # leadership
    roles = ledger.by_field("role")
    ceo = next((r for r in roles if r.get("role_code") == "DAGL"), None)
    chair = next((r for r in roles if r.get("role_code") == "LEDE"), None)
    members = [r for r in roles if r.get("role_code") == "MEDL"]
    lead = []
    ids = []
    if ceo:
        lead.append(f"the chief executive is {ceo['value'] if isinstance(ceo['value'], str) else ceo['value']['name']}")
        ids.append(ceo["id"])
    if chair:
        lead.append(f"the board is chaired by {chair['value'] if isinstance(chair['value'], str) else chair['value']['name']}")
        ids.append(chair["id"])
    if members:
        lead.append(f"{len(members)} further board member{'s' if len(members) != 1 else ''} {'are' if len(members) != 1 else 'is'} registered")
        ids.extend(m["id"] for m in members)
    if lead:
        text = _join(lead)
        s.append(_sentence(text[0].upper() + text[1:] + ".", ids, {"members": float(len(members))}))
    workplaces = ledger.by_field("workplace")
    if workplaces:
        places = sorted({(w.get("municipality") or "").title() for w in workplaces if w.get("municipality")})
        s.append(_sentence(f"It has {len(workplaces)} registered workplace{'s' if len(workplaces) != 1 else ''}"
                           + (f" in {_join(places[:6])}" + (" and more" if len(places) > 6 else "") if places else "") + ".",
                           [w["id"] for w in workplaces], {"n": float(len(workplaces))}))
    parent = first("group_parent")
    if parent:
        s.append(_sentence(f"It belongs to a corporate group; its registered parent is {parent['value']['name']}.", [parent["id"]]))
    # online footprint
    site = first("official_website")
    profiles = ledger.by_field("social_profile")
    if site:
        proof = first("website_identity_proof")
        text = f"Its verified website is {site['value']}"
        ids = [site["id"]]
        if proof:
            text += " (the site shows the company's registered " + ("organisation number" if proof.get("key", "").endswith("orgnr") else "contact details") + ")"
            ids.append(proof["id"])
        if profiles:
            text += "; it links to company profiles on " + _join(sorted({p['platform'].title() if p['platform'] != 'x' else 'X' for p in profiles}))
            ids.extend(p["id"] for p in profiles)
        s.append(_sentence(text + ".", ids))
    # hiring
    jobs = ledger.by_field("job_posting")
    careers = ledger.by_field("careers_page")
    if jobs:
        latest_job = max(jobs, key=lambda j: j.get("event_date") or "")
        text = (f"It is hiring: {len(jobs)} active job ad{'s' if len(jobs) != 1 else ''} on NAV's arbeidsplassen.no, most recently "
                f"“{latest_job['value']['title']}” published {latest_job.get('event_date')}.")
        s.append(_sentence(text, [j["id"] for j in jobs], {"n": float(len(jobs))}))
    elif careers:
        s.append(_sentence("No active ad was found on NAV's job feed, but its website links to a careers page.", [c["id"] for c in careers]))
    # activity
    posts = sorted(ledger.by_field("website_post"), key=lambda p: p.get("event_date") or "", reverse=True)
    if posts:
        p = posts[0]
        title = p["value"].get("title") if isinstance(p["value"], dict) else p["value"]
        s.append(_sentence(f"Latest dated activity on its own channels: “{_trim(title, 120)}” ({p.get('event_date')}).", [p["id"]]))
    role_change = sorted(ledger.by_field("registry_role_change"), key=lambda c: c.get("effective_at") or "", reverse=True)
    if role_change:
        c = role_change[0]
        s.append(_sentence(f"The most recent registered change to its roles was on {c['effective_at']}.", [c["id"]]))
    flags = [c for c in ledger.claims if c["field"] in {"bankrupt", "under_liquidation", "forced_dissolution"} and c["value"] is True]
    for flag in flags:
        s.append(_sentence(f"Warning: the register shows {flag['field'].replace('_', ' ')}.", [flag["id"]]))
    # changes and unknowns
    changes = ctx.get("changes") or []
    material = [c for c in changes if c.get("materiality") in ("high", "medium")]
    if ctx.get("previous_run_id"):
        if material:
            current_ids = {c["id"] for c in ledger.claims}
            s.append(_sentence("Since the previous run: " + "; ".join(c["description"] for c in material[:4]) + ".",
                               [cid for c in material[:4] for cid in c.get("claim_ids", []) if cid in current_ids][:12],
                               {f"c{i}": float(n) for i, n in enumerate(_all_numbers([c["description"] for c in material[:4]]))}))
        else:
            s.append(_sentence("No material changes since the previous run.", []))
    unknowns = [label for key, label in (("website", "a verified website"), ("profiles", "company-owned social profiles"),
                                         ("hiring", "active job ads"), ("activity", "dated posts or news on its own channels"),
                                         ("accounts", "filed annual accounts"))
                if key in ctx.get("missing", [])]
    if unknowns:
        s.append(_sentence("Not found in permitted sources at run time: " + _join(unknowns) + ".", []))
    accepted = [sentence for sentence in s if check_sentence(sentence, ledger)]
    dropped = len(s) - len(accepted)
    if dropped and os.environ.get("SIGNALPOST_DEBUG"):
        for sentence in s:
            if sentence not in accepted:
                print("[synth] dropped unsupported sentence:", sentence["text"], file=sys.stderr)
    return {"text": " ".join(x["text"] for x in accepted), "sentences": accepted, "unknowns": unknowns,
            "dropped_unsupported_sentences": dropped, "method": "deterministic_template_from_verified_claims_v1"}


def _all_numbers(texts: list[str]) -> list[float]:
    out = []
    for text in texts:
        for match in re.findall(r"-?\d[\d,.]*", text):
            try:
                out.append(float(match.replace(",", "").rstrip(".")))
            except ValueError:
                pass
    return out


def _join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"
