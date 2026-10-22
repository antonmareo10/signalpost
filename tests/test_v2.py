"""Offline tests for the v2 sources (accounts copies, register history, English industry labels), the structured
synthesis and the viewer. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signalpost.ledger import Document, Ledger, canonical_json  # noqa: E402
from signalpost.net import FetchResult  # noqa: E402
from signalpost.refresh import diff  # noqa: E402
from signalpost.registry import IndustryLabels, account_copy_claims, update_claims  # noqa: E402
from signalpost.site import build_site  # noqa: E402
from signalpost.synth import build_summary, check_sentence  # noqa: E402

ORG = "916340257"


def fetched(url: str, payload, status: int = 200) -> FetchResult:
    body = json.dumps(payload).encode("utf-8")
    return FetchResult(url=url, final_url=url, status=status, content_type="application/json", body=body, text=body.decode("utf-8"),
                       sha256=hashlib.sha256(body).hexdigest(), retrieved_at="2026-10-22T09:00:00Z")


def entity_doc(data):
    return Document(url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}", source_class="official_registry_live",
                    retrieved_at="2026-10-22T09:00:00Z", sha256="a" * 64, text=canonical_json(data), data=data)


UPDATES = {"_embedded": {"oppdaterteEnheter": [
    {"dato": "2023-01-12T22:11:28.847Z", "endringstype": "Endring", "oppdateringsid": 1, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/antallAnsatte", "value": 9}]},
    {"dato": "2025-10-15T22:08:31.777Z", "endringstype": "Endring", "oppdateringsid": 2, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/registreringsdatoAntallAnsatteEnhetsregisteret", "value": "2025-10-15"},
                   {"op": "replace", "path": "/antallAnsatte", "value": 6}]},
    {"dato": "2025-11-13T09:29:39.084Z", "endringstype": "Ukjent", "oppdateringsid": 3, "organisasjonsnummer": ORG},
    {"dato": "2026-03-01T10:00:00.000Z", "endringstype": "Endring", "oppdateringsid": 4, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/hjelpeenhetskode", "value": "x"}]},
    {"dato": "2026-04-24T10:00:00.000Z", "endringstype": "Endring", "oppdateringsid": 5, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/forretningsadresse/adresse/0", "value": "Storgata 1"}]},
    {"dato": "2026-06-23T18:01:33.396Z", "endringstype": "Endring", "oppdateringsid": 6, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/sisteInnsendteAarsregnskap", "value": "2025"}]},
    {"dato": "2026-09-14T22:02:20.453Z", "endringstype": "Endring", "oppdateringsid": 7, "organisasjonsnummer": ORG,
     "endringer": [{"op": "replace", "path": "/antallAnsatte", "value": 5}]},
]}, "page": {"totalElements": 7}}


class AccountCopiesTests(unittest.TestCase):
    def test_years_become_pdf_claims_newest_first(self):
        ledger = Ledger(ORG)
        state, out = account_copy_claims(ledger, fetched("https://data.brreg.no/x/aar", ["2023", "2025", "2024", "n/a"]), ORG)
        self.assertEqual(state, "available")
        self.assertEqual([c["value"] for c in out], ["2025", "2024", "2023"])
        self.assertTrue(out[0]["url"].endswith(f"/kopi/{ORG}/2025"))
        self.assertEqual(out[0]["section"], "accounts")

    def test_empty_list_and_errors_are_explicit_states(self):
        self.assertEqual(account_copy_claims(Ledger(ORG), fetched("u", []), ORG)[0], "not_available")
        self.assertEqual(account_copy_claims(Ledger(ORG), fetched("u", {}, status=429), ORG)[0], "blocked")


class RegisterHistoryTests(unittest.TestCase):
    def test_dated_events_with_details_only_within_window(self):
        ledger = Ledger(ORG)
        state, events = update_claims(ledger, fetched("https://data.brreg.no/u", UPDATES), "2026-10-22")
        self.assertEqual(state, "available")
        days = [e["value"] for e in events]
        self.assertEqual(days, ["2026-09-14", "2026-06-23", "2026-04-24", "2025-10-15"])  # no 2023 event, no detail-less or noise-only event
        self.assertIn("business address", events[2]["display"])
        history = sorted((c["effective_at"], c["value"]) for c in ledger.by_field("employees_history"))
        self.assertEqual(history, [("2025-10-15", 6), ("2026-09-14", 5)])
        filed = ledger.by_field("accounts_filed_event")
        self.assertEqual((filed[0]["value"], filed[0]["effective_at"]), ("2025", "2026-06-23"))
        self.assertFalse(ledger.rejected)

    def test_refresh_never_reports_an_aged_out_event_as_removed(self):
        ledger = Ledger(ORG)
        update_claims(ledger, fetched("u", UPDATES), "2026-10-22")
        previous = {"run": {"run_id": "r1"}, "claims": [dict(c) for c in ledger.claims]}
        later = {"claims": [c for c in ledger.claims if c["value"] != "2025-10-15"]}
        changes, carried = diff(later, previous, set())
        self.assertFalse([c for c in changes if c["field"] == "registry_update"])
        self.assertEqual(diff({"claims": ledger.claims}, previous, set()), ([], []))


class IndustryLabelTests(unittest.TestCase):
    def test_english_label_is_a_cited_claim(self):
        payload = {"codes": [{"code": "71", "name": "Architectural and engineering activities", "level": "2"},
                             {"code": "71.129", "name": "Other technical consultancy", "level": "5"}]}

        class FakeFetcher:
            calls = 0

            def get(self, url, **kwargs):
                FakeFetcher.calls += 1
                return fetched(url, payload)

        labels = IndustryLabels(FakeFetcher(), "2026-10-22")
        ledger = Ledger(ORG)
        claim = labels.claim(ledger, "71.129")
        self.assertEqual(claim["value"], "Other technical consultancy")
        self.assertEqual(claim["code"], "71.129")
        self.assertIsNone(labels.claim(ledger, "00.000"))
        self.assertIsNone(labels.claim(ledger, "99.999"))
        labels.claim(Ledger(ORG), "71.129")
        self.assertEqual(FakeFetcher.calls, 2)  # loaded once per run (SN2025 + SN2007 fallback), then shared


class SummaryV2Tests(unittest.TestCase):
    def build(self):
        ledger = Ledger(ORG)
        doc = entity_doc({"organisasjonsnummer": ORG, "navn": "WYSSEN NORGE AS", "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                          "naeringskode1": {"kode": "71.129", "beskrivelse": "Annen teknisk konsulentvirksomhet"}, "stiftelsesdato": "2015-10-30"})
        ledger.json_claim(doc, "/navn", "identity", "legal_name")
        ledger.json_claim(doc, "/organisasjonsform", "identity", "legal_form", value={"code": "AS", "description": "Aksjeselskap"})
        ledger.json_claim(doc, "/naeringskode1", "identity", "industry", value={"code": "71.129", "description": "Annen teknisk konsulentvirksomhet"},
                          qualifier="71.129")
        ledger.json_claim(doc, "/stiftelsesdato", "identity", "founded")
        klass = Document(url="https://data.ssb.no/k", source_class="official_classification", retrieved_at="t", sha256="b" * 64,
                         data={"codes": [{"code": "71.129", "name": "Other technical consultancy"}]})
        ledger.json_claim(klass, "/codes/0", "identity", "industry_en", value="Other technical consultancy", qualifier="71.129",
                          span_keys=("code", "name"))
        update_claims(ledger, fetched("u", UPDATES), "2026-10-22")
        return ledger

    def test_parts_cover_what_it_does_what_changed_and_unknowns(self):
        ledger = self.build()
        summary = build_summary(ledger, {"accounts": [], "changes": [], "missing": ["website", "hiring"], "today": "2026-10-22",
                                         "states": {"website": "not_available", "hiring": "not_available"},
                                         "notes": {"website": "no website listed in the register and no verifiable candidate"}})
        self.assertEqual(summary["dropped_unsupported_sentences"], 0)
        does = " ".join(summary["parts"]["what_it_does"])
        changed = " ".join(summary["parts"]["what_changed"])
        self.assertIn("other technical consultancy", does)
        self.assertIn("6 on 2025-10-15, then 5 on 2026-09-14", changed)
        self.assertIn("2025 annual accounts were registered as filed on 2026-06-23", changed)
        self.assertIn("business address (2026-04-24)", changed)
        self.assertIn("first run", changed)
        self.assertTrue(summary["parts"]["unknown"])
        self.assertEqual(summary["unknown_detail"][0]["reason"], "no website listed in the register and no verifiable candidate")
        self.assertTrue(any("fell from 6 to 5" in s["text"] for s in summary["signals"]))
        for sentence in summary["sentences"]:
            self.assertIn(sentence["part"], summary["parts"])
            self.assertTrue(check_sentence(sentence, ledger))

    def test_signal_with_unbacked_number_is_dropped(self):
        ledger = self.build()
        self.assertFalse(check_sentence({"text": "Registered employees fell from 60 to 5.", "claim_ids": [], "derived": {}}, ledger))


class NameVariantTests(unittest.TestCase):
    def test_a_slash_s_is_a_legal_form(self):
        from signalpost.web import name_tokens
        self.assertEqual(name_tokens("Rønnings Bilverksted A/S"), ["ronnings", "bilverksted"])
        self.assertEqual(name_tokens("A/S NORSK STAL"), ["norsk", "stal"])
        self.assertEqual(name_tokens("AAS ELEKTRONIKK AS"), ["aas", "elektronikk"])

    def test_connector_variant_is_tried_and_counts_as_named_after_the_company(self):
        from signalpost.web import Candidate, Company, SiteResearcher, candidate_slugs
        company = Company(org="923884149", name="NESSET OG EIDEM AS")
        self.assertEqual(candidate_slugs(company)[:2], ["nessetogeidem", "nesset-og-eidem"])
        proof = {"orgnr": None, "other_orgnrs": [], "phone": {"url": "u"}, "email": None, "address": None, "name_identity": {"url": "u"},
                 "name_anywhere": None, "domain_name": None, "legal_name_exact": None, "norwegian_context": True}
        researcher = SiteResearcher(fetcher=None)  # type: ignore[arg-type]
        researcher._name_unique = lambda c: False  # type: ignore[assignment]
        state, _, _ = researcher._decide(company, Candidate("https://x", "domain_guess_from_legal_name", "weak"), dict(proof), "nessetogeidem.no")
        self.assertEqual(state, "verified")
        state, _, _ = researcher._decide(company, Candidate("https://x", "domain_guess_from_legal_name", "weak"), dict(proof), "eidem.no")
        self.assertEqual(state, "rejected")  # a partial name is still not "named after the company"


class ViewerTests(unittest.TestCase):
    def test_site_embeds_parts_signals_and_documents(self):
        ledger = SummaryV2Tests().build()
        account_copy_claims(ledger, fetched("https://data.brreg.no/x/aar", ["2025"]), ORG)
        summary = build_summary(ledger, {"accounts": [], "changes": [], "missing": [], "today": "2026-10-22"})
        envelope = {"organisation_number": ORG, "legal_name": "WYSSEN NORGE AS", "status": "available",
                    "sections": {"identity": {"state": "available", "claims": 3}}, "summary": summary, "claims": ledger.claims,
                    "evidence": list(ledger.evidence.values()), "changes": [], "run": {"run_id": "r"}, "errors": []}
        with tempfile.TemporaryDirectory() as tmp:
            page = build_site([envelope], Path(tmp)).read_text(encoding="utf-8")
        data = json.loads(page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
        company = data["companies"][0]
        self.assertTrue(all(s["p"] for s in company["sum"]))
        self.assertTrue(company["sig"])
        self.assertTrue(any(c["f"] == "annual_accounts_copy" and c["url"].endswith("/2025") for c in company["cl"]))
        for hook in ('id="q"', 'id="drawer"', "cmpform", "Checked in code", "Download this profile"):
            self.assertIn(hook, page)
        self.assertNotIn("alert(", page)


if __name__ == "__main__":
    unittest.main()
