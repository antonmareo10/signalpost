"""Official Norwegian sources: Brønnøysund Enhetsregisteret and Regnskapsregisteret (NLOD 2.0).

Each response becomes a ``Document`` and every claim is a JSON-pointer into that document,
so the evaluator can re-fetch the URL and check the exact field.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from datetime import date, timedelta
from typing import Any

from .ledger import Document, Ledger, canonical_json
from .net import Fetcher, FetchResult, persist_snapshot

ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller"
SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=200"
GROUP = "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
COPIES = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"
COPY_PDF = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
UPDATES = ("https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter?organisasjonsnummer={org}"
           "&dato={since}T00:00:00.000Z&size=100&includeChanges=true")
KLASS_NACE = "https://data.ssb.no/api/klass/v1/classifications/6/codes?from={day}&language=en"
KLASS_NACE_2007 = "https://data.ssb.no/api/klass/v1/classifications/6/codes?from=2020-01-01&to=2024-12-31&language=en"

ROLE_LABELS = {
    "DAGL": "Chief executive (daglig leder)", "LEDE": "Chair of the board", "NEST": "Deputy chair", "MEDL": "Board member",
    "VARA": "Deputy board member", "OBS": "Board observer", "REVI": "Auditor", "REGN": "Accountant", "KONT": "Contact person",
    "DTPR": "Partner (proportional liability)", "DTSO": "Partner (joint liability)", "INNH": "Owner", "FFØR": "Business manager",
    "BEST": "Managing shipowner", "KOMP": "General partner", "KDEB": "Partner", "SAM": "Co-owner", "HFOR": "Head office",
    "EIKM": "Owner municipality", "BOBE": "Estate administrator", "STIF": "Founder", "PROK": "Procuration",
    "SIGN": "Signature right", "POFE": "Signature/procuration", "ADOS": "Administrative unit", "DIRE": "Director",
}
GROUP_LABELS = {"DAGL": "Chief executive", "STYR": "Board", "REVI": "Auditor", "REGN": "Accountant", "KONT": "Contact person",
                "DTPR": "Partners", "DTSO": "Partners", "INNH": "Owner", "SIGN": "Signature rights", "PROK": "Procuration",
                "FFØR": "Business manager", "KOMP": "General partner", "EIKM": "Owner municipality", "BEST": "Managing shipowner"}
PERSON_FIELDS_TO_DROP = ("fodselsdato",)


def _document(result: FetchResult, source_class: str, data: Any = None, transform: str | None = None) -> Document:
    payload = result.json() if data is None else data
    text = canonical_json(payload)
    sha = result.sha256 if transform is None else hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Document(url=result.url, source_class=source_class, retrieved_at=result.retrieved_at, sha256=sha,
                    text=text, data=payload, final_url=result.final_url, status=result.status, transform=transform)


def _state_for(result: FetchResult) -> str:
    if result.ok:
        return "available"
    if result.status in (404, 410):
        return "not_available"
    if result.blocked or result.status in (401, 403, 429):
        return "blocked"
    return "failed"


def _address(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    street = ", ".join(value.get("adresse") or [])
    place = " ".join(part for part in (value.get("postnummer"), value.get("poststed")) if part)
    country = value.get("land") if value.get("landkode") not in (None, "NO") else None
    parts = [part for part in (street, place, country) if part]
    return ", ".join(parts) or None


def fetch_entity(fetcher: Fetcher, org: str) -> FetchResult:
    return fetcher.get(ENTITY.format(org=org), accept="application/json", retries=2)


def entity_claims(ledger: Ledger, result: FetchResult) -> tuple[str, dict[str, Any]]:
    """Section 1 (legal identity) claims from the live entity record."""
    state = _state_for(result)
    if state != "available":
        return state, {}
    doc = _document(result, "official_registry_live")
    data = doc.data or {}
    s = "identity"
    ledger.json_claim(doc, "/organisasjonsnummer", s, "organisation_number")
    ledger.json_claim(doc, "/navn", s, "legal_name")
    ledger.json_claim(doc, "/organisasjonsform", s, "legal_form",
                      value={"code": data.get("organisasjonsform", {}).get("kode"), "description": data.get("organisasjonsform", {}).get("beskrivelse")},
                      display=f"{data.get('organisasjonsform', {}).get('beskrivelse')} ({data.get('organisasjonsform', {}).get('kode')})")
    for key, field_name in (("forretningsadresse", "business_address"), ("postadresse", "postal_address")):
        if data.get(key):
            ledger.json_claim(doc, f"/{key}", s, field_name, value=_address(data[key]), display=_address(data[key]))
    if data.get("forretningsadresse", {}).get("kommune"):
        ledger.json_claim(doc, "/forretningsadresse/kommune", s, "municipality")
    for index, key in enumerate(("naeringskode1", "naeringskode2", "naeringskode3")):
        code = data.get(key) or {}
        if code.get("kode"):
            ledger.json_claim(doc, f"/{key}", s, "industry" if index == 0 else "secondary_industry",
                              value={"code": code.get("kode"), "description": code.get("beskrivelse")},
                              qualifier=code.get("kode"), display=f"{code.get('beskrivelse')} ({code.get('kode')})")
    ledger.json_claim(doc, "/stiftelsesdato", s, "founded", effective_at=data.get("stiftelsesdato"))
    ledger.json_claim(doc, "/registreringsdatoEnhetsregisteret", s, "registered_date")
    if data.get("antallAnsatte") is not None and data.get("harRegistrertAntallAnsatte"):
        eff = data.get("registreringsdatoAntallAnsatteNAVAaregisteret") or data.get("registreringsdatoAntallAnsatteEnhetsregisteret")
        ledger.json_claim(doc, "/antallAnsatte", s, "employees_registered", effective_at=eff,
                          display=f"{data['antallAnsatte']} registered employees")
    capital = data.get("kapital") or {}
    if capital.get("belop") is not None:
        ledger.json_claim(doc, "/kapital/belop", s, "share_capital", effective_at=capital.get("innfortDato"),
                          display=f"{capital.get('valuta', 'NOK')} {capital['belop']:,.0f}", extra={"unit": capital.get("valuta", "NOK")})
    if data.get("vedtektsfestetFormaal"):
        text = " ".join(data["vedtektsfestetFormaal"])
        ledger.json_claim(doc, "/vedtektsfestetFormaal", s, "statutory_purpose", value=text, display=text)
    if data.get("aktivitet"):
        text = " ".join(data["aktivitet"])
        ledger.json_claim(doc, "/aktivitet", s, "registered_activity", value=text, display=text)
    for key, field_name, label in (("registrertIMvaregisteret", "vat_registered", "Registered in the VAT register"),
                                   ("registrertIForetaksregisteret", "business_register", "Registered in the Register of Business Enterprises"),
                                   ("konkurs", "bankrupt", "Bankruptcy registered"),
                                   ("underAvvikling", "under_liquidation", "Under liquidation"),
                                   ("underTvangsavviklingEllerTvangsopplosning", "forced_dissolution", "Under compulsory dissolution"),
                                   ("erIKonsern", "part_of_group", "Part of a corporate group")):
        if key in data:
            ledger.json_claim(doc, f"/{key}", s, field_name, display=f"{label}: {'yes' if data[key] else 'no'}")
    for index, item in enumerate(data.get("historiskeNavn") or []):
        ledger.json_claim(doc, f"/historiskeNavn/{index}/navn", s, "former_name", qualifier=str(index),
                          effective_at=(item.get("tilDato") or "")[:10] or None,
                          extra={"valid_from": (item.get("fraDato") or "")[:10] or None, "valid_to": (item.get("tilDato") or "")[:10] or None})
    ledger.json_claim(doc, "/sisteInnsendteAarsregnskap", s, "latest_filed_accounts_year")
    for key, field_name in (("registreringsdatoForetaksregisteret", "business_register_date"),
                            ("registreringsdatoMerverdiavgiftsregisteret", "vat_register_date"),
                            ("vedtektsdato", "articles_date")):
        if data.get(key):
            ledger.json_claim(doc, f"/{key}", s, field_name, effective_at=data[key])
    if capital.get("antallAksjer") is not None:
        ledger.json_claim(doc, "/kapital/antallAksjer", s, "number_of_shares", display=f"{capital['antallAksjer']:,} shares")
    if data.get("maalform"):
        ledger.json_claim(doc, "/maalform", s, "official_language_form")
    ledger.json_claim(doc, "/institusjonellSektorkode/beskrivelse", s, "institutional_sector")
    if data.get("epostadresse"):
        ledger.json_claim(doc, "/epostadresse", s, "registered_email")
    for key in ("telefon", "mobil"):
        if data.get(key):
            ledger.json_claim(doc, f"/{key}", s, "registered_phone", qualifier=key)
    if data.get("hjemmeside"):
        ledger.json_claim(doc, "/hjemmeside", s, "registered_website", confidence=0.9)
    if data.get("slettedato"):
        ledger.json_claim(doc, "/slettedato", s, "deleted_date")
    return "available", data


def fetch_accounts(fetcher: Fetcher, org: str) -> FetchResult:
    return fetcher.get(ACCOUNTS.format(org=org), accept="application/json", retries=2)


ACCOUNT_FIELDS = (
    ("revenue", "/resultatregnskapResultat/driftsresultat/driftsinntekter/sumDriftsinntekter", "Revenue"),
    ("operating_result", "/resultatregnskapResultat/driftsresultat/driftsresultat", "Operating result"),
    ("salary_costs", "/resultatregnskapResultat/driftsresultat/driftskostnad/loennskostnad", "Salary costs"),
    ("profit_before_tax", "/resultatregnskapResultat/ordinaertResultatFoerSkattekostnad", "Profit before tax"),
    ("net_result", "/resultatregnskapResultat/aarsresultat", "Annual net result"),
    ("total_assets", "/eiendeler/sumEiendeler", "Total assets"),
    ("cash", "/eiendeler/sumBankinnskuddOgKontanter", "Cash and bank deposits"),
    ("equity", "/egenkapitalGjeld/egenkapital/sumEgenkapital", "Equity"),
    ("debt", "/egenkapitalGjeld/gjeldOversikt/sumGjeld", "Total debt"),
    ("operating_costs", "/resultatregnskapResultat/driftsresultat/driftskostnad/sumDriftskostnad", "Operating costs"),
    ("sales_revenue", "/resultatregnskapResultat/driftsresultat/driftsinntekter/salgsinntekter", "Sales revenue"),
    ("net_financial_items", "/resultatregnskapResultat/finansresultat/nettoFinans", "Net financial items"),
    ("current_assets", "/eiendeler/omloepsmidler/sumOmloepsmidler", "Current assets"),
    ("fixed_assets", "/eiendeler/anleggsmidler/sumAnleggsmidler", "Fixed assets"),
    ("receivables", "/eiendeler/sumFordringer", "Receivables"),
    ("inventory", "/eiendeler/sumVarer", "Inventory"),
    ("short_term_debt", "/egenkapitalGjeld/gjeldOversikt/kortsiktigGjeld/sumKortsiktigGjeld", "Short-term debt"),
    ("long_term_debt", "/egenkapitalGjeld/gjeldOversikt/langsiktigGjeld/sumLangsiktigGjeld", "Long-term debt"),
)


def account_claims(ledger: Ledger, result: FetchResult) -> tuple[str, list[dict[str, Any]]]:
    """Section 2: every filed year the API returns (normally the last three)."""
    state = _state_for(result)
    if state != "available":
        return state, []
    doc = _document(result, "official_annual_accounts")
    records = doc.data if isinstance(doc.data, list) else []
    if not records:
        return "not_available", []
    summary = []
    order = sorted(range(len(records)), key=lambda i: (records[i].get("regnskapsperiode") or {}).get("tilDato") or "", reverse=True)
    for index in order:
        record = records[index]
        period = record.get("regnskapsperiode") or {}
        period_label = f"{period.get('fraDato')}..{period.get('tilDato')}"
        year = (period.get("tilDato") or "")[:4]
        account_type = record.get("regnskapstype") or "SELSKAP"
        qual = f"{year}:{account_type}"
        base = f"/{index}"
        currency = record.get("valuta") or "NOK"
        ledger.json_claim(doc, f"{base}/regnskapsperiode", "accounts", "accounting_period", qualifier=qual,
                          value={"from": period.get("fraDato"), "to": period.get("tilDato")},
                          display=f"{'Group' if account_type == 'KONSERN' else 'Company'} accounts filed for {period_label}",
                          period=period_label, effective_at=period.get("tilDato"),
                          extra={"year": year, "account_type": account_type})
        row = {"year": year, "account_type": account_type, "period": period_label, "currency": currency}
        for field_name, pointer, label in ACCOUNT_FIELDS:
            try:
                value = _pointer(record, pointer)
            except KeyError:
                continue
            if value is None:
                continue
            claim = ledger.json_claim(doc, base + pointer, "accounts", field_name, qualifier=qual, period=period_label,
                                      display=f"{label} {year}: {currency} {value:,.0f}", extra={"unit": currency, "year": year,
                                                                                                  "account_type": account_type})
            if claim:
                row[field_name] = {"value": value, "claim_id": claim["id"]}
        revisjon = record.get("revisjon") or {}
        if "ikkeRevidertAarsregnskap" in revisjon:
            ledger.json_claim(doc, f"{base}/revisjon/ikkeRevidertAarsregnskap", "accounts", "accounts_unaudited", qualifier=qual,
                              period=period_label, display=f"{year} accounts unaudited: {'yes' if revisjon['ikkeRevidertAarsregnskap'] else 'no'}")
        summary.append(row)
    return "available", summary


def _pointer(record: dict[str, Any], pointer: str) -> Any:
    current: Any = record
    for part in pointer.strip("/").split("/"):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(pointer)
        current = current[part]
    return current


def fetch_roles(fetcher: Fetcher, org: str) -> FetchResult:
    return fetcher.get(ROLES.format(org=org), accept="application/json", retries=2, snapshot=False)


def role_claims(ledger: Ledger, result: FetchResult, fetcher: Fetcher) -> tuple[str, list[dict[str, Any]]]:
    """Section 3a: registered roles. Person birth dates are removed before anything is stored or shown."""
    state = _state_for(result)
    if state != "available":
        return state, []
    data = copy.deepcopy(result.json() or {})
    for group in data.get("rollegrupper", []):
        for role in group.get("roller", []):
            person = role.get("person") or {}
            for key in PERSON_FIELDS_TO_DROP:
                person.pop(key, None)
    doc = _document(result, "official_roles", data=data, transform="person birth dates removed before storage")
    if fetcher.snapshot_dir:
        persist_snapshot(fetcher.snapshot_dir, doc.sha256, doc.text.encode("utf-8"))
    people = []
    for gi, group in enumerate(data.get("rollegrupper", [])):
        changed = group.get("sistEndret")
        for ri, role in enumerate(group.get("roller", [])):
            if role.get("avregistrert") or role.get("fratraadt"):
                continue
            code = (role.get("type") or {}).get("kode") or "?"
            label = ROLE_LABELS.get(code, (role.get("type") or {}).get("beskrivelse") or code)
            person = role.get("person") or {}
            entity = role.get("enhet") or {}
            if person.get("navn"):
                name_parts = person["navn"]
                name = " ".join(p for p in (name_parts.get("fornavn"), name_parts.get("mellomnavn"), name_parts.get("etternavn")) if p)
                if person.get("erDoed"):
                    continue
                claim = ledger.json_claim(doc, f"/rollegrupper/{gi}/roller/{ri}/person/navn", "people", "role",
                                          value=name, qualifier=f"{code}:{name}", effective_at=changed,
                                          display=f"{label}: {name}", extra={"role_code": code, "role": label, "holder_type": "person"})
            elif entity.get("organisasjonsnummer"):
                names = entity.get("navn") or []
                name = " ".join(names) if isinstance(names, list) else str(names)
                claim = ledger.json_claim(doc, f"/rollegrupper/{gi}/roller/{ri}/enhet", "people", "role",
                                          value={"name": name, "organisation_number": entity.get("organisasjonsnummer")},
                                          qualifier=f"{code}:{entity.get('organisasjonsnummer')}", effective_at=changed,
                                          display=f"{label}: {name} (org. {entity.get('organisasjonsnummer')})",
                                          extra={"role_code": code, "role": label, "holder_type": "organisation"})
            else:
                continue
            if claim:
                people.append({"role_code": code, "role": label, "name": claim["display"].split(": ", 1)[-1], "claim_id": claim["id"],
                               "last_changed": changed})
        if changed:
            group_code = (group.get("type") or {}).get("kode")
            label = GROUP_LABELS.get(group_code, (group.get("type") or {}).get("beskrivelse") or group_code)
            ledger.json_claim(doc, f"/rollegrupper/{gi}/sistEndret", "activity", "registry_role_change",
                              qualifier=group_code, effective_at=changed,
                              display=f"{label} entry last changed in the register on {changed}",
                              extra={"event_date": changed})
    return ("available" if people else "not_available"), people


def fetch_subunits(fetcher: Fetcher, org: str) -> FetchResult:
    return fetcher.get(SUBUNITS.format(org=org), accept="application/json", retries=2)


def subunit_claims(ledger: Ledger, result: FetchResult) -> tuple[str, list[dict[str, Any]]]:
    """Section 3b: registered workplaces (underenheter)."""
    state = _state_for(result)
    if state != "available":
        return state, []
    doc = _document(result, "official_subunits")
    rows = ((doc.data or {}).get("_embedded") or {}).get("underenheter") or []
    out = []
    for index, unit in enumerate(rows):
        if unit.get("nedleggelsesdato"):
            continue
        address = _address(unit.get("beliggenhetsadresse") or unit.get("postadresse"))
        value = {"name": unit.get("navn"), "organisation_number": unit.get("organisasjonsnummer"), "address": address}
        claim = ledger.json_claim(doc, f"/_embedded/underenheter/{index}", "people", "workplace", value={k: v for k, v in value.items() if v},
                                  qualifier=unit.get("organisasjonsnummer"),
                                  span_keys=("navn", "organisasjonsnummer", "beliggenhetsadresse", "postadresse", "antallAnsatte"),
                                  display=f"{unit.get('navn')} — {address or 'address not registered'}",
                                  extra={"employees": unit.get("antallAnsatte") if unit.get("harRegistrertAntallAnsatte") else None,
                                         "municipality": (unit.get("beliggenhetsadresse") or {}).get("kommune"),
                                         "started": unit.get("oppstartsdato")})
        if claim:
            located = unit.get("beliggenhetsadresse") or {}
            out.append({"organisation_number": unit.get("organisasjonsnummer"), "name": unit.get("navn"), "address": address,
                        "street": " ".join(located.get("adresse") or []), "postcode": located.get("postnummer"),
                        "municipality": (unit.get("beliggenhetsadresse") or {}).get("kommune"),
                        "employees": unit.get("antallAnsatte") if unit.get("harRegistrertAntallAnsatte") else None,
                        "website": unit.get("hjemmeside"), "email": unit.get("epostadresse"),
                        "phones": [p for p in (unit.get("telefon"), unit.get("mobil")) if p], "claim_id": claim["id"]})
    return ("available" if out else "not_available"), out


def fetch_group(fetcher: Fetcher, org: str) -> FetchResult:
    return fetcher.get(GROUP.format(org=org), accept="application/json", retries=1)


def group_claims(ledger: Ledger, result: FetchResult, org: str) -> tuple[str, dict[str, Any]]:
    """Official group relationships (konsernstruktur): parent chain and direct subsidiaries."""
    state = _state_for(result)
    if state != "available":
        return state, {}
    doc = _document(result, "official_group_structure")
    root = doc.data or {}
    found: dict[str, Any] = {"parents": [], "subsidiaries": []}

    def walk(node: dict[str, Any], pointer: str, ancestors: list[tuple[dict[str, Any], str]]) -> bool:
        if node.get("organisasjonsnummer") == org:
            for parent, parent_pointer in ancestors[-1:]:
                claim = ledger.json_claim(doc, parent_pointer, "identity", "group_parent",
                                          value={"name": parent.get("navn"), "organisation_number": parent.get("organisasjonsnummer")},
                                          display=f"Parent company: {parent.get('navn')} (org. {parent.get('organisasjonsnummer')})")
                if claim:
                    found["parents"].append(claim["id"])
            if ancestors and ancestors[0][0] is not (ancestors[-1][0]):
                top, top_pointer = ancestors[0]
                claim = ledger.json_claim(doc, top_pointer, "identity", "group_ultimate_parent",
                                          value={"name": top.get("navn"), "organisation_number": top.get("organisasjonsnummer")},
                                          display=f"Ultimate parent: {top.get('navn')} (org. {top.get('organisasjonsnummer')})")
                if claim:
                    found["parents"].append(claim["id"])
            for ci, child in enumerate((node.get("children") or [])[:25]):
                claim = ledger.json_claim(doc, f"{pointer}/children/{ci}", "identity", "group_subsidiary",
                                          value={"name": child.get("navn"), "organisation_number": child.get("organisasjonsnummer")},
                                          qualifier=child.get("organisasjonsnummer"),
                                          display=f"Subsidiary: {child.get('navn')} (org. {child.get('organisasjonsnummer')})")
                if claim:
                    found["subsidiaries"].append(claim["id"])
            return True
        for ci, child in enumerate(node.get("children") or []):
            if walk(child, f"{pointer}/children/{ci}", ancestors + [(node, pointer or "")]):
                return True
        return False

    walk(root, "", [])
    return ("available" if found["parents"] or found["subsidiaries"] else "not_available"), found


# -- annual-account copies (official PDFs held by Regnskapsregisteret) -------------------------------------------
class _Pacer:
    """Spaces calls to an endpoint that publishes a small per-window request budget (``x-rate-limit-remaining``)."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            slot = max(time.monotonic(), self._next)
            self._next = slot + self.interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def cooldown(self, seconds: float) -> None:
        """Push every caller's next slot back: the endpoint said the budget is spent."""
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


# The copies endpoint grants a burst of ~30 requests per server and refills slowly; measured on 22 Oct 2026 a 1,000-company
# run at 4/s drew 98 refusals (HTTP 429), so the sustained pace is ~1.4/s from one dedicated thread, with a shared cool-down.
COPY_PACER = _Pacer(0.7)


def fetch_account_copies(fetcher: Fetcher, org: str, attempts: int = 6, deadline: float | None = None) -> FetchResult:
    result = None
    for attempt in range(attempts):
        COPY_PACER.wait()
        result = fetcher.get(COPIES.format(org=org), accept="application/json", retries=0)
        if result.status != 429:
            return result
        if deadline is not None and time.monotonic() > deadline:
            break
        COPY_PACER.cooldown(15 + 5 * attempt)  # budget spent: let it refill before anyone asks again
    return result  # type: ignore[return-value]


def account_copy_claims(ledger: Ledger, result: FetchResult, org: str) -> tuple[str, list[dict[str, Any]]]:
    """Years for which the register holds a copy of the filed annual accounts, each with its official PDF URL."""
    state = _state_for(result)
    if state != "available":
        return state, []
    doc = _document(result, "official_annual_account_copies")
    years = doc.data if isinstance(doc.data, list) else []
    out = []
    order = sorted(range(len(years)), key=lambda i: str(years[i]), reverse=True)
    for index in order[:20]:
        year = str(years[index])
        if not re.fullmatch(r"\d{4}", year):
            continue
        claim = ledger.json_claim(doc, f"/{index}", "accounts", "annual_accounts_copy", value=year, qualifier=year,
                                  display=f"Annual accounts {year}: official copy (PDF) held by the Register of Company Accounts",
                                  extra={"year": year, "url": COPY_PDF.format(org=org, year=year), "document_type": "annual_accounts_pdf"})
        if claim:
            out.append(claim)
    return ("available" if out else "not_available"), out


# -- dated register history (Enhetsregisteret update feed, filtered to this organisation number) --------------------
UPDATE_LABELS = {
    "navn": "name", "organisasjonsform": "legal form", "forretningsadresse": "business address", "postadresse": "postal address",
    "naeringskode1": "industry code", "naeringskode2": "secondary industry code", "naeringskode3": "secondary industry code",
    "antallAnsatte": "employee count", "hjemmeside": "website", "epostadresse": "e-mail address", "telefon": "phone number",
    "mobil": "mobile number", "sisteInnsendteAarsregnskap": "latest filed annual accounts", "kapital": "share capital",
    "vedtektsfestetFormaal": "statutory purpose", "aktivitet": "registered activity", "vedtektsdato": "articles of association",
    "registrertIMvaregisteret": "VAT registration", "registrertIForetaksregisteret": "business-register entry",
    "konkurs": "bankruptcy status", "underAvvikling": "liquidation status",
    "underTvangsavviklingEllerTvangsopplosning": "compulsory dissolution status", "erIKonsern": "group membership",
    "institusjonellSektorkode": "institutional sector", "stiftelsesdato": "founding date", "slettedato": "deletion",
    "registrertIFrivillighetsregisteret": "voluntary-organisation register entry", "registrertIStiftelsesregisteret": "foundation register entry",
    "overordnetEnhet": "parent unit", "maalform": "official language form", "historiskeNavn": "former names",
    "registreringsdatoForetaksregisteret": "business-register date", "registreringsdatoMerverdiavgiftsregisteret": "VAT-register date",
}
SKIP_UPDATE_FIELDS = {"registreringsdatoAntallAnsatteEnhetsregisteret", "registreringsdatoAntallAnsatteNAVAaregisteret",
                      "harRegistrertAntallAnsatte", "hjelpeenhetskode", "_links", "links", "respons_klasse"}


def fetch_updates(fetcher: Fetcher, org: str, today: str, months: int = 26) -> FetchResult:
    since = (date.fromisoformat(today) - timedelta(days=int(months * 30.5))).isoformat()
    return fetcher.get(UPDATES.format(org=org, since=since), accept="application/json", retries=1)


def update_claims(ledger: Ledger, result: FetchResult, today: str, months: int = 24, limit: int = 12) -> tuple[str, list[dict[str, Any]]]:
    """Dated changes the register recorded for this entity (what changed, when), newest first."""
    state = _state_for(result)
    if state != "available":
        return state, []
    doc = _document(result, "official_registry_updates")
    items = ((doc.data or {}).get("_embedded") or {}).get("oppdaterteEnheter") or []
    cutoff = (date.fromisoformat(today) - timedelta(days=int(months * 30.5))).isoformat()
    events: list[dict[str, Any]] = []
    order = sorted(range(len(items)), key=lambda i: items[i].get("dato") or "", reverse=True)
    for index in order:
        item = items[index]
        changes = item.get("endringer") or []
        day = (item.get("dato") or "")[:10]
        if not changes or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day < cutoff:
            continue
        fields: list[str] = []
        for change in changes:
            root = (change.get("path") or "").strip("/").split("/")[0]
            if root and root not in SKIP_UPDATE_FIELDS and root not in fields:
                fields.append(root)
        if not fields:
            continue
        labels = list(dict.fromkeys(UPDATE_LABELS.get(f, f) for f in fields))
        base = f"/_embedded/oppdaterteEnheter/{index}"
        for j, change in enumerate(changes):
            path, value = change.get("path") or "", change.get("value")
            if change.get("op") not in ("replace", "add"):
                continue
            if path == "/antallAnsatte" and isinstance(value, int) and not isinstance(value, bool):
                ledger.json_claim(doc, f"{base}/endringer/{j}", "activity", "employees_history", value=value, qualifier=day,
                                  effective_at=day, display=f"Registered employee count set to {value} on {day}",
                                  extra={"event_date": day})
            elif path == "/sisteInnsendteAarsregnskap" and value and re.fullmatch(r"\d{4}", str(value)):
                ledger.json_claim(doc, f"{base}/endringer/{j}", "activity", "accounts_filed_event", value=str(value),
                                  qualifier=str(value), effective_at=day,
                                  display=f"Annual accounts for {value} registered as filed on {day}",
                                  extra={"event_date": day, "year": str(value)})
        claim = ledger.json_claim(doc, base, "activity", "registry_update", value=day, qualifier=f"{day}:{item.get('oppdateringsid')}",
                                  effective_at=day, display=f"{day}: the register updated the {_join_labels(labels)}",
                                  span_keys=("dato", "oppdateringsid", "endringstype", "endringer"),
                                  extra={"event_date": day, "changed_fields": fields, "changed_labels": labels,
                                         "update_id": item.get("oppdateringsid")})
        if claim:
            events.append(claim)
        if len(events) >= limit:
            break
    return ("available" if events else "not_available"), events


def _join_labels(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


# -- English industry labels (Statistics Norway classification API, one request per run) ------------------------------
class IndustryLabels:
    """Official English names for the SN/NACE codes the register uses, so a reader knows what the company does."""

    def __init__(self, fetcher: Fetcher, today: str) -> None:
        self.fetcher = fetcher
        self.today = today
        self._lock = threading.Lock()
        self._docs: list[tuple[Document, dict[str, int], str]] | None = None
        self.error: str | None = None

    def _load(self) -> list[tuple[Document, dict[str, int], str]]:
        with self._lock:
            if self._docs is not None:
                return self._docs
            docs = []
            for url, version in ((KLASS_NACE.format(day=self.today), "SN2025"), (KLASS_NACE_2007, "SN2007")):
                result = self.fetcher.get(url, accept="application/json", retries=2, max_bytes=8_000_000)
                if not result.ok:
                    self.error = result.error or f"HTTP {result.status}"
                    continue
                try:
                    doc = _document(result, "official_classification")
                except ValueError as exc:
                    self.error = f"invalid JSON: {exc}"
                    continue
                codes = (doc.data or {}).get("codes") or []
                docs.append((doc, {str(c.get("code")): n for n, c in enumerate(codes) if c.get("name")}, version))
            self._docs = docs
            return docs

    def claim(self, ledger: Ledger, code: str | None, field_name: str = "industry_en") -> dict[str, Any] | None:
        if not code or code.startswith("00."):
            return None
        for doc, index, version in self._load():
            n = index.get(code)
            if n is None:
                continue
            name = doc.data["codes"][n]["name"]
            return ledger.json_claim(doc, f"/codes/{n}", "identity", field_name, value=name, qualifier=code,
                                     display=f"{name} (NACE {code}, English label from Statistics Norway)",
                                     span_keys=("code", "name", "level", "validFrom", "validTo"),
                                     extra={"code": code, "classification": version})
        return None
