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


def _sentence(text: str, claim_ids: list[str], derived: dict[str, float] | None = None, tone: str | None = None) -> dict[str, Any]:
    out = {"text": text, "claim_ids": [c for c in claim_ids if c], "derived": derived or {}}
    if tone:
        out["tone"] = tone
    return out


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


PART_ORDER = ("what_it_does", "money", "people_and_presence", "what_changed", "unknown")
UNKNOWN_LABELS = (("website", "a verified website"), ("profiles", "company-owned social profiles"), ("hiring", "active job ads"),
                  ("activity", "dated posts or news on its own channels"), ("accounts", "filed annual accounts"))
SECTION_FOR_UNKNOWN = {"website": "website", "profiles": "website", "hiring": "hiring", "activity": "activity", "accounts": "accounts"}


def build_summary(ledger: Ledger, ctx: dict[str, Any]) -> dict[str, Any]:
    """Explain what the company does, its money, people and presence, what changed and what is unknown, sentence by sentence."""
    parts: dict[str, list[dict[str, Any]]] = {p: [] for p in PART_ORDER}
    signals: list[dict[str, Any]] = []
    first = ledger.first
    today = ctx.get("today") or ""

    # -- what it does -----------------------------------------------------------------------------------------
    does = parts["what_it_does"]
    name = first("legal_name")
    brand = first("public_brand")
    form = first("legal_form")
    municipality = first("municipality")
    industry = first("industry")
    industry_en = first("industry_en")
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
        does.append(_sentence(desc + ".", ids))
    if industry_en and industry:
        does.append(_sentence(f"It works in {_lower_first(industry_en['value'])} (NACE {industry['value']['code']}, registered in Norwegian as "
                              f"“{industry['value']['description']}”).", [industry["id"], industry_en["id"]]))
    elif industry:
        does.append(_sentence(f"Its registered industry is “{industry['value']['description']}” (NACE {industry['value']['code']}).",
                              [industry["id"]]))
    website_desc = first("website_description")
    purpose = first("statutory_purpose") or first("registered_activity")
    if website_desc:
        does.append(_sentence(f"Its own website describes it as: “{_trim(website_desc['value'], 220)}”", [website_desc["id"]]))
    elif purpose:
        does.append(_sentence(f"Registered purpose: “{_trim(purpose['value'], 200)}”", [purpose["id"]]))
    employees = first("employees_registered")
    if employees:
        does.append(_sentence(f"The register lists {employees['value']} employees"
                              + (f" (as of {employees['effective_at']})." if employees.get("effective_at") else "."), [employees["id"]]))
    parent = first("group_parent")
    if parent:
        does.append(_sentence(f"It belongs to a corporate group; its registered parent is {parent['value']['name']}.", [parent["id"]]))

    # -- money ------------------------------------------------------------------------------------------------
    money = parts["money"]
    years = ctx.get("accounts") or []
    has_group = any(y.get("account_type") == "KONSERN" for y in years)
    for account_type in ("KONSERN", "SELSKAP"):
        rows = [y for y in years if y.get("account_type") == account_type]
        if not rows:
            continue
        latest = rows[0]
        sentence_parts, ids, derived = [], [], {}
        if "revenue" in latest:
            sentence_parts.append(f"revenue of {nok(latest['revenue']['value'])}")
            ids.append(latest["revenue"]["claim_id"])
            previous = rows[1] if len(rows) > 1 else None
            if previous and "revenue" in previous and previous["revenue"]["value"]:
                change = (latest["revenue"]["value"] - previous["revenue"]["value"]) / abs(previous["revenue"]["value"]) * 100
                derived["revenue_change_pct"] = round(change, 1)
                sentence_parts[-1] += f" ({'up' if change >= 0 else 'down'} {abs(round(change, 1))}% from {previous['year']})"
                ids.append(previous["revenue"]["claim_id"])
                if not (has_group and account_type == "SELSKAP") and abs(change) >= 25:
                    signals.append(_sentence(f"Revenue {'grew' if change > 0 else 'fell'} {abs(round(change, 1))}% in {latest['year']}.",
                                             [latest["revenue"]["claim_id"], previous["revenue"]["claim_id"]],
                                             {"revenue_change_pct": round(change, 1)}, tone="up" if change > 0 else "down"))
        if "operating_result" in latest:
            sentence_parts.append(f"an operating result of {nok(latest['operating_result']['value'])}")
            ids.append(latest["operating_result"]["claim_id"])
        if "net_result" in latest:
            sentence_parts.append(f"a net result of {nok(latest['net_result']['value'])}")
            ids.append(latest["net_result"]["claim_id"])
        if "equity" in latest:
            sentence_parts.append(f"equity of {nok(latest['equity']['value'])}")
            ids.append(latest["equity"]["claim_id"])
        if not sentence_parts:
            continue
        if has_group and account_type == "SELSKAP":
            money.append(_sentence("The parent company on its own reported " + _join(sentence_parts[:2]) + f" for {latest['year']}.", ids, derived))
            continue
        prefix = "The latest filed group accounts" if account_type == "KONSERN" else "The latest filed annual accounts"
        money.append(_sentence(f"{prefix} ({latest['year']}) show " + _join(sentence_parts) + ".", ids, derived))
        ratio_parts, ratio_ids, ratio_derived = [], [], {}
        revenue = (latest.get("revenue") or {}).get("value")
        operating = (latest.get("operating_result") or {}).get("value")
        equity = (latest.get("equity") or {}).get("value")
        assets = (latest.get("total_assets") or {}).get("value")
        if revenue and operating is not None and revenue > 0:
            margin = round(operating / revenue * 100, 1)
            ratio_parts.append(f"an operating margin of {margin}%")
            ratio_derived["margin"] = margin
            ratio_ids += [latest["revenue"]["claim_id"], latest["operating_result"]["claim_id"]]
        if assets and equity is not None and assets > 0:
            eq_ratio = round(equity / assets * 100, 1)
            ratio_parts.append(f"an equity ratio of {eq_ratio}%")
            ratio_derived["equity_ratio"] = eq_ratio
            ratio_ids += [latest["equity"]["claim_id"], latest["total_assets"]["claim_id"]]
        if ratio_parts:
            ratio_derived["year"] = float(latest["year"])
            money.append(_sentence(f"That gives {_join(ratio_parts)} for {latest['year']} (computed from the cited figures).",
                                   ratio_ids, ratio_derived))
        trend = [r for r in reversed(rows) if "revenue" in r]
        if len(trend) >= 3:
            money.append(_sentence("Revenue by filed year: " + ", ".join(f"{r['year']} {nok(r['revenue']['value'])}" for r in trend) + ".",
                                   [r["revenue"]["claim_id"] for r in trend]))
        if equity is not None and equity < 0:
            money.append(_sentence("Equity is negative in the latest filed accounts, a point to check before extending credit.",
                                   [latest["equity"]["claim_id"]]))
            signals.append(_sentence(f"Negative equity in the {latest['year']} accounts.", [latest["equity"]["claim_id"]], tone="risk"))
    unaudited = [c for c in ledger.by_field("accounts_unaudited") if c["value"] is True]
    if unaudited:
        latest_unaudited = max(unaudited, key=lambda c: c.get("year") or "")
        money.append(_sentence(f"The {latest_unaudited.get('year')} accounts were filed without an audit (allowed for small companies).",
                               [latest_unaudited["id"]]))
    copies = sorted(ledger.by_field("annual_accounts_copy"), key=lambda c: c["value"])
    if copies:
        span = f"{copies[0]['value']}" if len(copies) == 1 else f"{copies[0]['value']} to {copies[-1]['value']}"
        money.append(_sentence(f"The Register of Company Accounts holds official copies of its filed accounts for {len(copies)} "
                               f"year{'s' if len(copies) != 1 else ''} ({span}), each linked as a PDF.",
                               [c["id"] for c in copies], {"n": float(len(copies))}))

    # -- people and presence ------------------------------------------------------------------------------------
    people = parts["people_and_presence"]
    roles = ledger.by_field("role")
    ceo = next((r for r in roles if r.get("role_code") == "DAGL"), None)
    chair = next((r for r in roles if r.get("role_code") == "LEDE"), None)
    members = [r for r in roles if r.get("role_code") == "MEDL"]
    lead, ids = [], []

    def who(claim: dict[str, Any]) -> str:
        return claim["value"] if isinstance(claim["value"], str) else claim["value"]["name"]

    if ceo and chair and who(ceo) == who(chair):
        lead.append(f"{who(ceo)} is both chief executive and chair of the board")
        ids += [ceo["id"], chair["id"]]
    else:
        if ceo:
            lead.append(f"the chief executive is {who(ceo)}")
            ids.append(ceo["id"])
        if chair:
            lead.append(f"the board is chaired by {who(chair)}")
            ids.append(chair["id"])
    if members:
        lead.append(f"{len(members)} further board member{'s' if len(members) != 1 else ''} {'are' if len(members) != 1 else 'is'} registered")
        ids.extend(m["id"] for m in members)
    if lead:
        text = _join(lead)
        people.append(_sentence(text[0].upper() + text[1:] + ".", ids, {"members": float(len(members))}))
    workplaces = ledger.by_field("workplace")
    if workplaces:
        places = sorted({(w.get("municipality") or "").title() for w in workplaces if w.get("municipality")})
        people.append(_sentence(f"It has {len(workplaces)} registered workplace{'s' if len(workplaces) != 1 else ''}"
                                + (f" in {_join(places[:6])}" + (" and more" if len(places) > 6 else "") if places else "") + ".",
                                [w["id"] for w in workplaces], {"n": float(len(workplaces))}))
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
        people.append(_sentence(text + ".", ids))
    jobs = ledger.by_field("job_posting")
    careers = ledger.by_field("careers_page")
    if jobs:
        latest_job = max(jobs, key=lambda j: j.get("event_date") or "")
        people.append(_sentence(f"It is hiring: {len(jobs)} active job ad{'s' if len(jobs) != 1 else ''} on NAV's arbeidsplassen.no, most recently "
                                f"“{latest_job['value']['title']}” published {latest_job.get('event_date')}.",
                                [j["id"] for j in jobs], {"n": float(len(jobs))}))
        signals.append(_sentence(f"Hiring now: {len(jobs)} active job ad{'s' if len(jobs) != 1 else ''}.", [j["id"] for j in jobs],
                                 {"n": float(len(jobs))}, tone="up"))
    elif careers:
        people.append(_sentence("No active ad was found on NAV's job feed, but its website links to a careers page.", [c["id"] for c in careers]))
    posts = sorted(ledger.by_field("website_post"), key=lambda p: p.get("event_date") or "", reverse=True)
    if posts:
        p = posts[0]
        title = p["value"].get("title") if isinstance(p["value"], dict) else p["value"]
        people.append(_sentence(f"Latest dated activity on its own channels: “{_trim(title, 120)}” ({p.get('event_date')}).", [p["id"]]))

    # -- what changed ----------------------------------------------------------------------------------------------
    changed = parts["what_changed"]
    history = sorted(ledger.by_field("employees_history"), key=lambda c: c.get("effective_at") or "")
    if len(history) >= 2:
        steps = ", then ".join(f"{h['value']} on {h['effective_at']}" for h in history[-4:])
        changed.append(_sentence(f"The register's employee count was set to {steps}.", [h["id"] for h in history[-4:]]))
        if history[-1]["value"] != history[-2]["value"]:
            signals.append(_sentence(f"Registered employees {'rose' if history[-1]['value'] > history[-2]['value'] else 'fell'} from "
                                     f"{history[-2]['value']} to {history[-1]['value']} ({history[-1]['effective_at']}).",
                                     [history[-2]["id"], history[-1]["id"]],
                                     tone="up" if history[-1]["value"] > history[-2]["value"] else "down"))
    filed = sorted(ledger.by_field("accounts_filed_event"), key=lambda c: c.get("effective_at") or "", reverse=True)
    if filed:
        f0 = filed[0]
        changed.append(_sentence(f"Its {f0['value']} annual accounts were registered as filed on {f0['effective_at']}.", [f0["id"]]))
    updates = sorted(ledger.by_field("registry_update"), key=lambda c: c.get("effective_at") or "", reverse=True)
    cutoff = _months_before(today, 12) if today else ""
    other = [u for u in updates if (u.get("effective_at") or "") >= cutoff
             and set(u.get("changed_fields") or []) - {"sisteInnsendteAarsregnskap", "antallAnsatte"}]
    if other:
        items = [f"the {_join_list([l for l in u.get('changed_labels', []) if l not in ('latest filed annual accounts', 'employee count')])} "
                 f"({u['effective_at']})" for u in other[:4]]
        changed.append(_sentence("In the last 12 months the register also recorded changes to " + _join(items) + ".", [u["id"] for u in other[:4]],
                                 {"months": 12.0}))
        notable = [u for u in other if set(u.get("changed_fields") or []) & {"navn", "forretningsadresse", "naeringskode1", "organisasjonsform",
                                                                            "konkurs", "underAvvikling", "kapital"}]
        for u in notable[:2]:
            labels = [l for l in u.get("changed_labels", []) if l in ("name", "business address", "industry code", "legal form",
                                                                      "bankruptcy status", "liquidation status", "share capital")]
            if labels:
                signals.append(_sentence(f"Register change on {u['effective_at']}: {_join_list(labels)}.", [u["id"]], tone="info"))
    elif updates and not filed:
        u = updates[0]
        changed.append(_sentence(f"The most recent register update on record was on {u['effective_at']}.", [u["id"]]))
    role_change = sorted(ledger.by_field("registry_role_change"), key=lambda c: c.get("effective_at") or "", reverse=True)
    if role_change:
        c = role_change[0]
        changed.append(_sentence(f"The most recent registered change to its roles was on {c['effective_at']}.", [c["id"]]))
        if cutoff and (c.get("effective_at") or "") >= cutoff:
            signals.append(_sentence(f"Leadership or board entry changed on {c['effective_at']}.", [c["id"]], tone="info"))
    former = sorted(ledger.by_field("former_name"), key=lambda c: c.get("valid_to") or "", reverse=True)
    if former and former[0].get("valid_to"):
        changed.append(_sentence(f"It was previously registered as {former[0]['value']} (until {former[0]['valid_to']}).", [former[0]["id"]]))
    if founded and today and founded["value"][:10] >= _months_before(today, 24):
        signals.append(_sentence(f"Young company: founded {founded['value'][:10]}.", [founded["id"]], tone="info"))
    for flag in [c for c in ledger.claims if c["field"] in {"bankrupt", "under_liquidation", "forced_dissolution"} and c["value"] is True]:
        changed.append(_sentence(f"Warning: the register shows {flag['field'].replace('_', ' ')}.", [flag["id"]]))
        signals.append(_sentence(f"Register flag: {flag['field'].replace('_', ' ')}.", [flag["id"]], tone="risk"))
    material = [c for c in (ctx.get("changes") or []) if c.get("materiality") in ("high", "medium")]
    if ctx.get("previous_run_id"):
        if material:
            current_ids = {c["id"] for c in ledger.claims}
            changed.append(_sentence("Since the previous run: " + "; ".join(c["description"] for c in material[:4]) + ".",
                                     [cid for c in material[:4] for cid in c.get("claim_ids", []) if cid in current_ids][:12],
                                     {f"c{i}": float(n) for i, n in enumerate(_all_numbers([c["description"] for c in material[:4]]))}))
        else:
            changed.append(_sentence("No material changes since the previous run.", []))
    else:
        changed.append(_sentence("This is the first run for this company, so there is no earlier snapshot of ours to compare against.", []))

    # -- unknown -----------------------------------------------------------------------------------------------------
    missing = ctx.get("missing", [])
    unknowns = [label for key, label in UNKNOWN_LABELS if key in missing]
    states, notes = ctx.get("states") or {}, ctx.get("notes") or {}
    unknown_detail = []
    for key, label in UNKNOWN_LABELS:
        if key not in missing:
            continue
        section = SECTION_FOR_UNKNOWN[key]
        state = states.get(section, "not_available")
        if key in ("profiles", "activity") and state == "available":
            state = "not_available"
        reason = notes.get(section) if key not in ("profiles", "activity") else None
        if key == "profiles":
            reason = "no company-owned profile linked from a verified website" if states.get("website") == "available" else "no verified website to take profiles from"
        if key == "activity":
            reason = "no dated post, news item or feed on a verified website"
        unknown_detail.append({"item": label, "state": state, "reason": reason})
    if unknowns:
        parts["unknown"].append(_sentence("Not found in permitted sources at run time: " + _join(unknowns) + ".", []))

    # -- verify every sentence, keep the order of the parts -----------------------------------------------------------
    accepted: list[dict[str, Any]] = []
    dropped = 0
    out_parts: dict[str, list[str]] = {}
    for part in PART_ORDER:
        kept = []
        for sentence in parts[part]:
            if check_sentence(sentence, ledger):
                sentence["part"] = part
                accepted.append(sentence)
                kept.append(sentence["text"])
            else:
                dropped += 1
                if os.environ.get("SIGNALPOST_DEBUG"):
                    print("[synth] dropped unsupported sentence:", sentence["text"], file=sys.stderr)
        out_parts[part] = kept
    kept_signals = [{"text": x["text"], "claim_ids": x["claim_ids"], "tone": x.get("tone", "info")} for x in signals if check_sentence(x, ledger)]
    return {"text": " ".join(x["text"] for x in accepted), "sentences": accepted, "parts": out_parts, "signals": kept_signals[:6],
            "unknowns": unknowns, "unknown_detail": unknown_detail, "dropped_unsupported_sentences": dropped,
            "method": "deterministic_template_from_verified_claims_v2"}


def _months_before(day: str, months: int) -> str:
    from datetime import date, timedelta
    try:
        return (date.fromisoformat(day[:10]) - timedelta(days=int(months * 30.5))).isoformat()
    except ValueError:
        return ""


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def _join_list(items: list[str]) -> str:
    return _join(list(dict.fromkeys(i for i in items if i)))


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
