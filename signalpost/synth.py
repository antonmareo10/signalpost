"""Decision-useful synthesis built only from verified claims.

Every sentence carries the claim ids it rests on and the numbered sources behind them. Numbers in a sentence must come
from a cited claim value or from a declared computation on cited values (percentages, ratios, counts); ``check_sentence``
enforces this and drops any sentence that fails.

The summary answers the brief directly: an overview in three to five sentences, then what the company does, its money,
its people and presence, what changed (since our previous run and in the registers' own dated records) and what remains
unknown, with the state and the reason for each gap.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any

from .ledger import SOURCE_LABELS, Ledger


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


def nok_pair(a: float, b: float) -> tuple[str, str]:
    """Two amounts written with just enough precision to show that they differ ("NOK 4.68 m" and "NOK 4.70 m")."""
    for extra in range(0, 3):
        x, y = _nok_precise(a, extra), _nok_precise(b, extra)
        if x != y:
            return x, y
    return _nok_precise(a, 2), _nok_precise(b, 2)


def _nok_precise(value: float, extra: int) -> str:
    if extra == 0:
        return nok(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    for limit, unit, base in ((1_000_000_000, "bn", 1), (1_000_000, "m", 1), (1_000, "k", 0)):
        if value >= limit:
            return f"NOK {sign}{value / limit:.{base + extra}f} {unit}"
    return f"NOK {sign}{value:.0f}"


def _sentence(text: str, claim_ids: list[str | None], derived: dict[str, float] | None = None, tone: str | None = None) -> dict[str, Any]:
    out = {"text": text, "claim_ids": list(dict.fromkeys(c for c in claim_ids if c)), "derived": derived or {}}
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


FORMS_EN = {"AS": "private limited company", "ASA": "public limited company", "ENK": "sole proprietorship", "ANS": "general partnership",
            "DA": "general partnership with shared liability", "SA": "cooperative", "STI": "foundation", "NUF": "Norwegian branch of a foreign company",
            "FLI": "association", "BRL": "housing cooperative", "ESEK": "condominium", "KS": "limited partnership",
            "IKS": "inter-municipal company", "KF": "municipal enterprise", "SPA": "savings bank", "SF": "state enterprise",
            "BBL": "housing building cooperative", "SAM": "joint ownership", "VPFO": "securities fund", "PK": "pension fund",
            "GFS": "mutual insurance company", "KTRF": "trustee-registered association", "BA": "company with limited liability",
            "PRE": "shipping partnership", "OPMV": "special-purpose entity", "ADOS": "administrative unit", "ORGL": "organisational unit",
            "UTLA": "foreign entity", "TVAM": "jointly owned entity"}


def article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


PART_ORDER = ("overview", "what_it_does", "money", "people_and_presence", "what_changed", "unknown")
PART_LABELS = {"overview": "In brief", "what_it_does": "What it does", "money": "Money", "people_and_presence": "People and presence",
               "what_changed": "What changed", "unknown": "Not found"}
UNKNOWN_LABELS = (("website", "a verified website"), ("profiles", "company-owned social profiles"), ("hiring", "active job ads"),
                  ("activity", "dated posts or news on its own channels"), ("accounts", "filed annual accounts"))
SECTION_FOR_UNKNOWN = {"website": "website", "profiles": "website", "hiring": "hiring", "activity": "activity", "accounts": "accounts"}
STATE_HEADS = {"not_available": "Not found", "blocked": "Blocked", "ambiguous": "Ambiguous", "failed": "Could not be checked in this run",
               "not_applicable": "Not applicable"}
DISCOVERY_WORDS = {"registry_website": "the website listed in the register", "registry_snapshot_website": "the website in the registry snapshot",
                   "registry_email_domain": "the domain of the registered e-mail address",
                   "nav_job_ad_employer_homepage": "the employer homepage in a NAV job ad",
                   "registry_subunit_website": "a workplace's registered website",
                   "registry_subunit_email_domain": "the e-mail domain of a workplace",
                   "domain_guess_from_legal_name": "domains named after the company", "search": "search results"}
FLAG_WORDS = {"bankrupt": "bankrupt", "under_liquidation": "under liquidation", "forced_dissolution": "under forced dissolution"}
NOTABLE_UPDATE_FIELDS = {"navn", "forretningsadresse", "naeringskode1", "organisasjonsform", "konkurs", "underAvvikling", "kapital"}
NOTABLE_UPDATE_LABELS = ("name", "business address", "industry code", "legal form", "bankruptcy status", "liquidation status", "share capital")
LEADERSHIP_GROUPS = {"DAGL", "STYR", "INNH", "DTPR", "DTSO", "KOMP", "FFØR", "BEST", "EIKM"}


def build_summary(ledger: Ledger, ctx: dict[str, Any]) -> dict[str, Any]:
    """Explain what the company does, its money, people and presence, what changed and what is unknown, sentence by sentence."""
    parts: dict[str, list[dict[str, Any]]] = {p: [] for p in PART_ORDER}
    signals: list[dict[str, Any]] = []
    first = ledger.first
    today = ctx.get("today") or ""
    cutoff = _months_before(today, 12) if today else ""

    # -- what it does -----------------------------------------------------------------------------------------
    does = parts["what_it_does"]
    name = first("legal_name")
    brand = first("public_brand")
    form = first("legal_form")
    municipality = first("municipality")
    industry = first("industry")
    industry_en = first("industry_en")
    founded = first("founded")
    form_en = (FORMS_EN.get(form["value"]["code"], (form["value"].get("description") or "registered entity").lower())
               if form and isinstance(form.get("value"), dict) else "registered entity")
    if name:
        label = name["value"] + (f" (trading as {brand['value']})" if brand else "")
        desc = f"{label} is {article(form_en)} {form_en}" + (f" ({form['value']['code']})" if form else "")
        ids = [name["id"], brand["id"] if brand else None, form["id"] if form else None]
        if municipality:
            desc += f" registered in {municipality['value'].title()}"
            ids.append(municipality["id"])
        if founded:
            desc += f", founded {founded['value'][:4]}"
            ids.append(founded["id"])
        does.append(_sentence(desc + ".", ids))
    if industry and _unspecified(industry):
        does.append(_sentence(f"The register gives no industry for it (NACE {industry['value']['code']}, “{industry['value']['description']}”).",
                              [industry["id"]]))
    elif industry_en and industry:
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
    main_rows: list[dict[str, Any]] = []
    for account_type in ("KONSERN", "SELSKAP"):
        rows = [y for y in years if y.get("account_type") == account_type]
        if not rows:
            continue
        if not main_rows:
            main_rows = rows
        latest = rows[0]
        sentence_parts, ids, derived = [], [], {}
        if "revenue" in latest:
            sentence_parts.append(f"revenue of {nok(latest['revenue']['value'])}")
            ids.append(latest["revenue"]["claim_id"])
            previous = rows[1] if len(rows) > 1 else None
            change = _pct_change(latest, previous, "revenue")
            if change is not None and previous:
                derived["revenue_change_pct"] = change
                sentence_parts[-1] += f" ({'up' if change >= 0 else 'down'} {abs(change)}% from {previous['year']})"
                ids.append(previous["revenue"]["claim_id"])
                if not (has_group and account_type == "SELSKAP") and abs(change) >= 25:
                    signals.append(_sentence(f"Revenue {'grew' if change > 0 else 'fell'} {abs(change)}% in {latest['year']}.",
                                             [latest["revenue"]["claim_id"], previous["revenue"]["claim_id"]],
                                             {"revenue_change_pct": change}, tone="up" if change > 0 else "down"))
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
        # Ratios are only stated where they mean something: a margin beyond +/-300% (tiny revenue) or an equity ratio
        # beyond +/-100% (negative equity larger than all assets) is left out rather than printed as a huge number.
        if revenue and operating is not None and revenue > 0 and abs(operating / revenue) <= 3:
            margin = round(operating / revenue * 100, 1)
            ratio_parts.append(f"an operating margin of {margin}%")
            ratio_derived["margin"] = margin
            ratio_ids += [latest["revenue"]["claim_id"], latest["operating_result"]["claim_id"]]
        if assets and equity is not None and assets > 0 and abs(equity) <= assets:
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
    if ceo and chair and _who(ceo) == _who(chair):
        lead.append(f"{_who(ceo)} is both chief executive and chair of the board")
        ids += [ceo["id"], chair["id"]]
    else:
        if ceo:
            lead.append(f"the chief executive is {_who(ceo)}")
            ids.append(ceo["id"])
        if chair:
            lead.append(f"the board is chaired by {_who(chair)}")
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
    if site and site.get("basis") == "registry_listing":
        people.append(_sentence(f"Its website, as listed in the Brønnøysund register, is {site['value']}; the site refuses automated "
                                f"access, so its pages were not read.", [site["id"]]))
    elif site and site.get("site_scope") == "shared_site":
        people.append(_sentence(f"Its page {site['value']} names the company with a registered contact detail, but the site belongs to a "
                                f"group, chain or manager, so nothing else is taken from it.", [site["id"]]))
    elif site:
        proof = first("website_identity_proof")
        text = f"Its verified website is {site['value']}"
        ids = [site["id"]]
        if proof:
            text += " (the site shows the company's registered " + ("organisation number" if proof.get("key", "").endswith("orgnr") else "contact details") + ")"
            ids.append(proof["id"])
        if profiles:
            text += "; it links to company profiles on " + _join(sorted({_platform(p) for p in profiles}))
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
    material = [c for c in (ctx.get("changes") or []) if c.get("materiality") in ("high", "medium")]
    previous_run = ctx.get("previous_run_id")
    previous_day = str(ctx.get("previous_completed_at") or "")[:10]
    since = f"Since our previous run{' on ' + previous_day if previous_day else ''}"
    day_numbers = {f"d{i}": n for i, n in enumerate(_all_numbers([previous_day]))}
    current_ids = {c["id"] for c in ledger.claims}
    if previous_run:
        if material:
            descriptions = [c["description"] for c in material[:4]]
            more = len(material) - len(descriptions)
            changed.append(_sentence(f"{since}: " + "; ".join(descriptions) + (f"; and {more} more" if more > 0 else "") + ".",
                                     [cid for c in material[:4] for cid in c.get("claim_ids", []) if cid in current_ids][:12],
                                     {**{f"c{i}": n for i, n in enumerate(_all_numbers(descriptions))}, **day_numbers, "more": float(more)}))
        else:
            changed.append(_sentence(f"{since}, nothing material has changed.", [], day_numbers))
    else:
        changed.append(_sentence("This is our first run for this company, so the changes below come from the registers' own dated records.", []))
    yoy = _accounts_change(main_rows)
    if yoy:
        changed.append(yoy)
    history = sorted(ledger.by_field("employees_history"), key=lambda c: c.get("effective_at") or "")
    if len(history) >= 2:
        steps = ", then ".join(f"{h['value']} on {h['effective_at']}" for h in history[-4:])
        changed.append(_sentence(f"The register's employee count was set to {steps}.", [h["id"] for h in history[-4:]]))
        if history[-1]["value"] != history[-2]["value"]:
            rose = history[-1]["value"] > history[-2]["value"]
            signals.append(_sentence(f"Registered employees {'rose' if rose else 'fell'} from "
                                     f"{history[-2]['value']} to {history[-1]['value']} ({history[-1]['effective_at']}).",
                                     [history[-2]["id"], history[-1]["id"]], tone="up" if rose else "down"))
            signals[-1]["phrase"] = (f"registered employees {'rose' if rose else 'fell'} from {history[-2]['value']} to "
                                     f"{history[-1]['value']} on {history[-1]['effective_at']}")
    filed = sorted(ledger.by_field("accounts_filed_event"), key=lambda c: c.get("effective_at") or "", reverse=True)
    if filed:
        f0 = filed[0]
        changed.append(_sentence(f"Its {f0['value']} annual accounts were registered as filed on {f0['effective_at']}.", [f0["id"]]))
    updates = sorted(ledger.by_field("registry_update"), key=lambda c: c.get("effective_at") or "", reverse=True)
    other = [u for u in updates if (u.get("effective_at") or "") >= cutoff
             and set(u.get("changed_fields") or []) - {"sisteInnsendteAarsregnskap", "antallAnsatte"}]
    if other:
        items = [f"the {_join_list([l for l in u.get('changed_labels', []) if l not in ('latest filed annual accounts', 'employee count')])} "
                 f"({u['effective_at']})" for u in other[:4]]
        changed.append(_sentence("In the last 12 months the register also recorded changes to " + _join(items) + ".", [u["id"] for u in other[:4]],
                                 {"months": 12.0}))
        notable = [u for u in other if set(u.get("changed_fields") or []) & NOTABLE_UPDATE_FIELDS]
        for u in notable[:2]:
            labels = [l for l in u.get("changed_labels", []) if l in NOTABLE_UPDATE_LABELS]
            if labels:
                signals.append(_sentence(f"Register change on {u['effective_at']}: {_join_list(labels)}.", [u["id"]], tone="info"))
                signals[-1]["phrase"] = f"its {_join_list(labels)} changed in the register on {u['effective_at']}"
    elif updates and not filed:
        u = updates[0]
        changed.append(_sentence(f"The most recent register update on record was on {u['effective_at']}.", [u["id"]]))
    role_change = sorted(ledger.by_field("registry_role_change"), key=lambda c: c.get("effective_at") or "", reverse=True)
    if role_change:
        c = role_change[0]
        group = _role_group(c)
        changed.append(_sentence(f"The most recent registered change to its roles was on {c['effective_at']}"
                                 + (f" ({group} entry)." if group else "."), [c["id"]]))
        # Only a change to who leads or owns the company is a signal; a new accountant or auditor entry is not.
        leading = [r for r in role_change if str(r.get("key") or "").split("|", 1)[-1] in LEADERSHIP_GROUPS]
        if leading and cutoff and (leading[0].get("effective_at") or "") >= cutoff:
            c = leading[0]
            signals.append(_sentence(f"Leadership or board entry changed on {c['effective_at']}.", [c["id"]], tone="info"))
            signals[-1]["phrase"] = f"its {_role_group(c) or 'leadership or board'} entry changed in the roles register on {c['effective_at']}"
    former = sorted(ledger.by_field("former_name"), key=lambda c: c.get("valid_to") or "", reverse=True)
    if former and former[0].get("valid_to"):
        changed.append(_sentence(f"It was previously registered as {former[0]['value']} (until {former[0]['valid_to']}).", [former[0]["id"]]))
    if founded and today and founded["value"][:10] >= _months_before(today, 24):
        signals.append(_sentence(f"Young company: founded {founded['value'][:10]}.", [founded["id"]], tone="info"))
    flags = [c for c in ledger.claims if c["field"] in FLAG_WORDS and c["value"] is True]
    for flag in flags:
        changed.append(_sentence(f"Warning: the register shows it is {FLAG_WORDS[flag['field']]}.", [flag["id"]]))
        signals.append(_sentence(f"Register flag: {flag['field'].replace('_', ' ')}.", [flag["id"]], tone="risk"))

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
    discovery = ctx.get("discovery") or []
    for detail in unknown_detail:
        parts["unknown"].append(_unknown_sentence(detail, discovery))

    # -- overview: the profile in a few sentences, drawn from the parts above -------------------------------------------
    parts["overview"] = _overview(ledger, main_rows, form_en, unknowns, material if previous_run else [], signals, flags)

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
    kept_signals = kept_signals[:6]
    sources = _attach_sources(accepted + kept_signals, ledger)
    labelled = [f"{PART_LABELS[p]}: " + " ".join(out_parts[p]) for p in PART_ORDER if out_parts[p]]
    return {"overview": " ".join(out_parts["overview"]),
            "text": " ".join(labelled), "sentences": accepted, "parts": out_parts, "part_labels": dict(PART_LABELS),
            "signals": kept_signals, "sources": sources, "markdown": _markdown(accepted, sources),
            "unknowns": unknowns, "unknown_detail": unknown_detail, "dropped_unsupported_sentences": dropped,
            "method": "deterministic_template_from_verified_claims_v3"}


# -- overview ---------------------------------------------------------------------------------------------------------------
def _overview(ledger: Ledger, rows: list[dict[str, Any]], form_en: str, unknowns: list[str], material: list[dict[str, Any]],
              signals: list[dict[str, Any]], flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first = ledger.first
    out: list[dict[str, Any]] = []
    name, brand = first("legal_name"), first("public_brand")
    municipality, industry, industry_en = first("municipality"), first("industry"), first("industry_en")
    founded, employees, form = first("founded"), first("employees_registered"), first("legal_form")
    if name:
        ids = [name["id"], brand["id"] if brand else None, form["id"] if form else None]
        place = municipality["value"].title() if municipality else ""
        text = name["value"] + (f" (trading as {brand['value']})" if brand else "") + " is "
        text += f"{article(place or form_en)} {place + '-based ' if place else ''}{form_en}"
        if municipality:
            ids.append(municipality["id"])
        if industry and _unspecified(industry):
            pass  # "Uoppgitt" (00.000): the register gives no industry, so the overview names none
        elif industry_en:
            text += f" in {_lower_first(industry_en['value'])}"
            ids.append(industry_en["id"])
        elif industry:
            text += f" registered under “{industry['value']['description']}”"
            ids.append(industry["id"])
        extras = []
        if founded:
            extras.append(f"founded in {founded['value'][:4]}")
            ids.append(founded["id"])
        if employees:
            extras.append(f"with {employees['value']} registered employee{'s' if employees['value'] != 1 else ''}")
            ids.append(employees["id"])
        text += (", " + ", ".join(extras) if extras else "") + "."
        out.append(_sentence(text, ids))
    description = first("website_description")
    if description and _informative(description["value"]):
        out.append(_sentence(f"Its own website says: “{_trim(description['value'], 140)}”", [description["id"]]))
    for flag in flags[:1]:
        out.append(_sentence(f"The register shows it is {FLAG_WORDS[flag['field']]}.", [flag["id"]]))
    money = _overview_money(rows)
    if money:
        out.append(money)
    presence = _overview_presence(ledger)
    if presence:
        out.append(presence)
    elif "filed annual accounts" in unknowns:
        out.append(_sentence("No filed annual accounts were found in the Register of Company Accounts.", []))
    change = _overview_change(material, signals)
    if change:
        out.append(change)
    gaps = [u for u in unknowns if u != "filed annual accounts"]
    if gaps:
        out.append(_sentence(f"Not found: {_join(gaps)}.", []))
    return out


def _overview_money(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    year = latest["year"]
    group = " group" if latest.get("account_type") == "KONSERN" else ""
    bits: list[str] = []
    ids: list[str] = []
    derived: dict[str, float] = {"year": float(year)} if str(year).isdigit() else {}
    revenue = latest.get("revenue")
    if revenue:
        ids.append(revenue["claim_id"])
        if revenue["value"] == 0:
            bits.append("reported no revenue")
        else:
            text = f"had{group} revenue of {nok(revenue['value'])}"
            change = _pct_change(latest, previous, "revenue")
            if change is not None and previous and abs(change) < 0.05:
                text += f", unchanged on {previous['year']}"
                ids.append(previous["revenue"]["claim_id"])
            elif change is not None and previous:
                text += f", {'up' if change >= 0 else 'down'} {abs(change)}% on {previous['year']}"
                derived["revenue_change_pct"] = change
                ids.append(previous["revenue"]["claim_id"])
                streak = _streak(rows, "revenue")
                if streak >= 2:
                    text += f" and {'higher' if change >= 0 else 'lower'} for the {_ordinal(streak)} year running"
            bits.append(text)
    operating = latest.get("operating_result")
    if operating:
        ids.append(operating["claim_id"])
        value = operating["value"]
        bits.append("broke even at operating level" if value == 0 else
                    f"made an operating {'profit' if value > 0 else 'loss'} of {nok(abs(value))}")
    equity = latest.get("equity")
    if equity:
        ids.append(equity["claim_id"])
        bits.append(f"had negative equity ({nok(equity['value'])})" if equity["value"] < 0 else f"had equity of {nok(equity['value'])}")
    net = latest.get("net_result")
    if net and not revenue and not operating:
        ids.append(net["claim_id"])
        bits.append("broke even" if net["value"] == 0 else f"made a net {'profit' if net['value'] > 0 else 'loss'} of {nok(abs(net['value']))}")
    if not bits:
        return None
    return _sentence(f"In {year} it " + _join(bits) + ".", ids, derived)


def _overview_presence(ledger: Ledger) -> dict[str, Any] | None:
    site = ledger.first("official_website")
    profiles = ledger.by_field("social_profile")
    jobs = ledger.by_field("job_posting")
    posts = sorted(ledger.by_field("website_post"), key=lambda p: p.get("event_date") or "", reverse=True)
    bits: list[str] = []
    ids: list[str] = []
    derived: dict[str, float] = {}
    if site and site.get("basis") == "registry_listing":
        bits.append(f"its registered website is {_host(site['value'])} (the site refuses automated access, so it was not read)")
        ids.append(site["id"])
    elif site and site.get("site_scope") != "shared_site":
        text = f"it has a verified website, {_host(site['value'])}"
        ids.append(site["id"])
        if profiles:
            text += ", with company profiles on " + _join(sorted({_platform(p) for p in profiles}))
            ids.extend(p["id"] for p in profiles)
        bits.append(text)
    if jobs:
        bits.append(f"it is hiring, with {len(jobs)} active job ad{'s' if len(jobs) != 1 else ''} on NAV")
        ids.extend(j["id"] for j in jobs)
        derived["jobs"] = float(len(jobs))
    if posts and posts[0].get("event_date"):
        bits.append(f"its latest post on its own channels is dated {posts[0]['event_date']}")
        ids.append(posts[0]["id"])
    if not bits:
        return None
    text = "; ".join(bits)
    return _sentence(text[0].upper() + text[1:] + ".", ids, derived)


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", str(url)).rstrip("/")


def _overview_change(material: list[dict[str, Any]], signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    if material:
        first_change = material[0]
        more = len(material) - 1
        derived = {f"c{i}": n for i, n in enumerate(_all_numbers([first_change["description"]]))}
        derived["more"] = float(more)
        return _sentence(f"Since our previous run: {first_change['description']}"
                         + (f" (and {more} more change{'s' if more != 1 else ''})" if more else "") + ".",
                         list(first_change.get("claim_ids", []))[:4], derived)
    recent = [s for s in signals if s.get("phrase")]
    if recent:
        return _sentence("Recent changes: " + _join([s["phrase"] for s in recent[:2]]) + ".", [cid for s in recent[:2] for cid in s["claim_ids"]])
    return None


# -- what changed: the accounts year on year ----------------------------------------------------------------------------------
def _accounts_change(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    latest, previous = rows[0], rows[1]
    bits: list[str] = []
    ids: list[str] = []
    derived: dict[str, float] = {}
    change = _pct_change(latest, previous, "revenue")
    if change is not None and abs(change) < 0.05:
        bits.append(f"revenue was unchanged at {nok(latest['revenue']['value'])}")
        ids += [latest["revenue"]["claim_id"], previous["revenue"]["claim_id"]]
    elif change is not None:
        before, after = nok_pair(previous["revenue"]["value"], latest["revenue"]["value"])
        text = f"revenue {'rose' if change >= 0 else 'fell'} {abs(change)}% (from {before} to {after})"
        streak = _streak(rows, "revenue")
        if streak >= 2:
            text += f", the {_ordinal(streak)} {'rise' if change >= 0 else 'fall'} in a row"
        bits.append(text)
        derived["revenue_change_pct"] = change
        ids += [latest["revenue"]["claim_id"], previous["revenue"]["claim_id"]]
    if "operating_result" in latest and "operating_result" in previous:
        a, b = previous["operating_result"]["value"], latest["operating_result"]["value"]
        if a == b:
            bits.append(f"the operating result was unchanged at {nok(b)}")
        elif (a >= 0) != (b >= 0):
            before, after = nok_pair(abs(a), abs(b))
            bits.append(f"the operating result turned from a {'profit' if a >= 0 else 'loss'} of {before} "
                        f"to a {'profit' if b >= 0 else 'loss'} of {after}")
        else:
            before, after = nok_pair(a, b)
            bits.append(f"the operating result went from {before} to {after}")
        ids += [previous["operating_result"]["claim_id"], latest["operating_result"]["claim_id"]]
    if "equity" in latest and "equity" in previous:
        a, b = previous["equity"]["value"], latest["equity"]["value"]
        if (a >= 0) != (b >= 0):
            bits.append(f"equity turned {'negative' if b < 0 else 'positive'} ({nok(a)} to {nok(b)})")
            ids += [previous["equity"]["claim_id"], latest["equity"]["claim_id"]]
    if not bits:
        return None
    group = " group" if latest.get("account_type") == "KONSERN" else ""
    return _sentence(f"Between the {previous['year']} and {latest['year']}{group} accounts, " + "; ".join(bits) + ".", ids, derived)


def _pct_change(latest: dict[str, Any], previous: dict[str, Any] | None, field: str) -> float | None:
    if not previous or field not in latest or field not in previous or not previous[field]["value"]:
        return None
    return round((latest[field]["value"] - previous[field]["value"]) / abs(previous[field]["value"]) * 100, 1)


def _streak(rows: list[dict[str, Any]], field: str) -> int:
    """How many consecutive filed years (no gaps) moved in the same direction as the latest one."""
    values: list[float] = []
    for row in rows:
        if field not in row:
            break
        values.append(row[field]["value"])
    if len(values) < 2 or values[0] == values[1]:
        return 0
    up = values[0] > values[1]
    streak = 0
    for newer, older in zip(values, values[1:]):
        if newer == older or (newer > older) != up:
            break
        streak += 1
    return streak


def _ordinal(n: int) -> str:
    return {2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, "latest")


# -- what remains unknown ---------------------------------------------------------------------------------------------------------
def _unknown_sentence(detail: dict[str, Any], discovery: list[dict[str, Any]]) -> dict[str, Any]:
    item, state = detail["item"], detail["state"]
    reason = detail.get("reason") or ""
    tried: list[dict[str, Any]] = []
    if item == "a verified website":
        if state == "ambiguous":
            reason = "a candidate site prints another organisation number, so it may belong to a related company and nothing was published from it"
        tried = [d for d in discovery if d.get("outcome") != "verified"]
        if tried:
            kinds = list(dict.fromkeys(DISCOVERY_WORDS.get(d.get("source"), "other candidates") for d in tried))
            reason += ("; " if reason else "") + f"{len(tried)} candidate site{'s' if len(tried) != 1 else ''} checked: {_join(kinds)}"
    head = STATE_HEADS.get(state, state.replace("_", " ").capitalize())
    derived = {f"r{i}": n for i, n in enumerate(_all_numbers([reason]))}
    derived["tried"] = float(len(tried))
    return _sentence(f"{head}: {item}" + (f" ({reason})" if reason else "") + ".", [], derived)


# -- sources -------------------------------------------------------------------------------------------------------------------
def _attach_sources(sentences: list[dict[str, Any]], ledger: Ledger) -> list[dict[str, Any]]:
    """Number every distinct source URL behind the summary and give each sentence the numbers it rests on."""
    by_id = {c["id"]: c for c in ledger.claims}
    sources: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for sentence in sentences:
        numbers: list[int] = []
        for claim_id in sentence.get("claim_ids", []):
            claim = by_id.get(claim_id)
            if not claim:
                continue
            for ev_id in claim.get("evidence_ids", []):
                ev = ledger.evidence.get(ev_id)
                if not ev or not ev.get("source_url"):
                    continue
                url = ev["source_url"]
                if url not in index:
                    index[url] = len(sources) + 1
                    sources.append({"n": index[url], "url": url, "source_class": ev.get("source_class"),
                                    "source": SOURCE_LABELS.get(ev.get("source_class"), ev.get("source_class") or "source"),
                                    "retrieved_at": ev.get("retrieved_at")})
                if index[url] not in numbers:
                    numbers.append(index[url])
        sentence["sources"] = sorted(numbers)
    return sources


def _markdown(sentences: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for part in PART_ORDER:
        rows = [s for s in sentences if s.get("part") == part]
        if not rows:
            continue
        lines.append(f"### {PART_LABELS[part]}")
        lines.append(" ".join(s["text"] + "".join(f" [{n}]" for n in s.get("sources", [])) for s in rows))
        lines.append("")
    if sources:
        lines.append("### Sources")
        for src in sources:
            lines.append(f"[{src['n']}] {src['source']}, retrieved {str(src.get('retrieved_at') or '')[:10]}: {src['url']}")
    return "\n".join(lines).strip()


# -- helpers -------------------------------------------------------------------------------------------------------------------
def _who(claim: dict[str, Any]) -> str:
    return claim["value"] if isinstance(claim["value"], str) else claim["value"]["name"]


def _platform(profile: dict[str, Any]) -> str:
    names = {"x": "X", "linkedin": "LinkedIn", "youtube": "YouTube", "tiktok": "TikTok"}
    return names.get(profile["platform"], profile["platform"].title())


def _role_group(claim: dict[str, Any]) -> str:
    match = re.match(r"(.+?) entry last changed", str(claim.get("display") or ""))
    return match.group(1).lower() if match else ""


def _months_before(day: str, months: int) -> str:
    from datetime import date, timedelta
    try:
        return (date.fromisoformat(day[:10]) - timedelta(days=int(months * 30.5))).isoformat()
    except ValueError:
        return ""


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def _unspecified(industry: dict[str, Any]) -> bool:
    value = industry.get("value") if isinstance(industry.get("value"), dict) else {}
    return str(value.get("code") or "").startswith("00") or str(value.get("description") or "").strip().lower() == "uoppgitt"


def _informative(text: str) -> bool:
    """A site description worth quoting in the overview: a few words of prose, not a greeting with a phone number."""
    words = re.findall(r"[^\W\d_]{2,}", str(text))
    return len(words) >= 6 and not re.search(r"\d{2}[ .]?\d{2}[ .]?\d{2}[ .]?\d{2}", str(text))


def _join_list(items: list[str]) -> str:
    return _join(list(dict.fromkeys(i for i in items if i)))


def _all_numbers(texts: list[str]) -> list[float]:
    out = []
    for text in texts:
        for match in re.findall(r"-?\d[\d,.]*", text or ""):
            try:
                out.append(float(match.replace(",", "").rstrip(".")))
            except ValueError:
                pass
            for part in re.split(r"[-.:/]", match):
                if part.isdigit():
                    out.append(float(part))
    return out


def _join(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"
