"""Offline regression tests for the gates that protect precision. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signalpost import cli  # noqa: E402
from signalpost.html import parse_html  # noqa: E402
from signalpost.ledger import Document, Ledger, canonical_json, supports  # noqa: E402
from signalpost.nav import NavJobs  # noqa: E402
from signalpost.refresh import diff  # noqa: E402
from signalpost.synth import build_summary, check_sentence  # noqa: E402
from signalpost.web import (Candidate, Company, SiteResearcher, acceptable_brand, address_on_page, candidate_slugs,  # noqa: E402
                            foreign_entity_handle, handle_matches, legal_name_hit, name_tokens, normalize_social, opaque_handle,
                            valid_orgnr)


def json_doc(data, url="https://data.brreg.no/enhetsregisteret/api/enheter/810034882"):
    return Document(url=url, source_class="official_registry_live", retrieved_at="2026-10-21T00:00:00Z", sha256="x" * 64,
                    text=canonical_json(data), data=data)


class SupportTests(unittest.TestCase):
    def test_numbers_and_strings(self):
        self.assertTrue(supports(10021242.0, "10021242.0"))
        self.assertTrue(supports(10021242, '{"sumDriftsinntekter":10021242.0}'))
        self.assertFalse(supports(10021243, '{"sumDriftsinntekter":10021242.0}'))
        self.assertTrue(supports("Sandnes Elektriske AS", "© SANDNES ELEKTRISKE AS 2026"))
        self.assertFalse(supports("Sandnes Elektro AS", "© SANDNES ELEKTRISKE AS 2026"))

    def test_urls_and_dates(self):
        self.assertTrue(supports("https://www.facebook.com/afgruppen", "[link] https://facebook.com/afgruppen Facebook"))
        self.assertTrue(supports("2026-08-20", "Tildelt kontrakt 20.08.2026"))
        self.assertFalse(supports("2026-08-21", "Tildelt kontrakt 20.08.2026"))


class LedgerTests(unittest.TestCase):
    def test_json_claim_verifies_pointer_value(self):
        ledger = Ledger("810034882")
        doc = json_doc({"navn": "SANDNES ELEKTRISKE AS", "antallAnsatte": 10})
        self.assertIsNotNone(ledger.json_claim(doc, "/navn", "identity", "legal_name"))
        self.assertIsNone(ledger.json_claim(doc, "/navn", "identity", "legal_name", value="OTHER COMPANY AS"))
        self.assertIsNone(ledger.json_claim(doc, "/missing", "identity", "x"))
        self.assertEqual(len(ledger.claims), 1)
        self.assertTrue(ledger.rejected)

    def test_text_claim_requires_excerpt_in_document(self):
        ledger = Ledger("810034882")
        doc = Document(url="https://example.no", source_class="company_owned_website", retrieved_at="t", sha256="y" * 64,
                       text="Kontakt oss\nOrg.nr 810 034 882\nTelefon 51 68 57 00")
        self.assertIsNotNone(ledger.text_claim(doc, "Org.nr 810 034 882", "website", "website_identity_proof", "810 034 882"))
        self.assertIsNone(ledger.text_claim(doc, "Org.nr 999 999 999", "website", "website_identity_proof", "999 999 999"))

    def test_duplicate_fact_attaches_second_evidence(self):
        ledger = Ledger("1")
        a = json_doc({"navn": "X AS"}, url="https://a")
        b = json_doc({"navn": "X AS"}, url="https://b")
        ledger.json_claim(a, "/navn", "identity", "legal_name")
        ledger.json_claim(b, "/navn", "identity", "legal_name")
        self.assertEqual(len(ledger.claims), 1)
        self.assertEqual(len(ledger.claims[0]["evidence_ids"]), 2)


class IdentityTests(unittest.TestCase):
    def test_orgnr_checksum(self):
        self.assertTrue(valid_orgnr("810034882"))
        self.assertTrue(valid_orgnr("938702675"))
        self.assertFalse(valid_orgnr("810034883"))

    def test_name_tokens_keep_aas(self):
        self.assertEqual(name_tokens("LUND ÅS AS"), ["lund", "aas"])
        self.assertEqual(name_tokens("STIFTELSEN NASJONAL JAZZSCENE"), ["nasjonal", "jazzscene"])
        self.assertIn("lislegard", candidate_slugs(Company(org="1", name="LISLEGÅRD MASKIN AS")))

    def test_exact_legal_name(self):
        self.assertEqual(legal_name_hit("LISLEGÅRD MASKIN AS", "© 2024 Lislegård Maskin AS | Personvern"), "Lislegård Maskin AS")
        self.assertIsNone(legal_name_hit("LISLEGÅRD MASKIN AS", "Nord Lislegård Maskin AS"))
        self.assertIsNone(legal_name_hit("LUND ÅS AS", "L. A. Lund AS"))

    def test_address_variants(self):
        self.assertTrue(address_on_page("Espesetvegen 296", "3540", "Espesetveien 296, 3540 Nesbyen"))
        self.assertIsNone(address_on_page("Strandgata 21", "4307", "Strandgaten 12, 4307 Sandnes"))

    def _decide(self, strength, **proof):
        base = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None, "name_identity": None,
                "name_anywhere": None, "domain_name": None, "legal_name_exact": None, "norwegian_context": True}
        base.update(proof)
        researcher = SiteResearcher(fetcher=None)  # type: ignore[arg-type]
        researcher._name_unique = lambda company: False  # type: ignore[assignment]
        return researcher._decide(Company(org="923884149", name="STORD REINHALD AS"), Candidate("https://x", "t", strength),
                                  base, "omsorgsguiden.no")

    def test_directory_page_is_rejected_even_with_name_and_phone(self):
        state, _, _ = self._decide("weak", name_identity={"url": "u"}, phone={"url": "u"})
        self.assertEqual(state, "rejected")

    def test_foreign_orgnr_blocks_discovered_site(self):
        state, _, _ = self._decide("medium", name_identity={"url": "u"}, other_orgnrs=["984181485"])
        self.assertEqual(state, "rejected")

    def test_registered_site_with_only_shared_contact_is_related(self):
        state, _, _ = self._decide("strong", phone={"url": "u"})
        self.assertEqual(state, "related")


class SocialTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_social("https://m.facebook.com/afgruppen/timeline?ref=x"), ("facebook", "https://www.facebook.com/afgruppen"))
        self.assertIsNone(normalize_social("https://www.facebook.com/sharer/sharer.php?u=x"))
        self.assertIsNone(normalize_social("https://www.linkedin.com/in/some-person"))
        self.assertEqual(normalize_social("https://www.youtube.com/@afgruppen")[0], "youtube")

    def test_handle_rules(self):
        company = Company(org="1", name="NORDIC SUPPLY PARTNER AS")
        self.assertTrue(handle_matches(company, "https://www.instagram.com/nspnorge", None, "www.nsp.no"))
        self.assertFalse(handle_matches(Company(org="1", name="FJELLHEIMEN GALLERI AS"), "https://www.instagram.com/orsolyahaarberg",
                                        None, "fjellheimengalleri.no"))
        self.assertTrue(opaque_handle("https://www.facebook.com/profile.php?id=100057441009551"))

    def test_parent_or_group_handles_are_not_the_company(self):
        self.assertTrue(foreign_entity_handle(Company(org="1", name="LINDBAK IT AS"), "https://www.linkedin.com/company/lindbak-gruppen-as"))
        self.assertTrue(foreign_entity_handle(Company(org="1", name="WYSSEN NORGE AS"),
                                              "https://www.linkedin.com/company/wyssen-avalanche-control-ag"))
        self.assertFalse(foreign_entity_handle(Company(org="1", name="AF GRUPPEN ASA"), "https://www.linkedin.com/company/af-gruppen"))
        self.assertFalse(foreign_entity_handle(Company(org="1", name="ENTRA ASA", aliases=["ENTRA EIENDOM AS"]),
                                               "https://www.linkedin.com/company/entra-eiendom-as"))

    def test_brand_rules(self):
        self.assertFalse(acceptable_brand("Knut Hovet AS", Company(org="1", name="KNUT HOVET INSTALLASJONAR AS"), "hovet.com"))
        self.assertFalse(acceptable_brand("Mats Carlin", Company(org="1", name="CARLIN INVEST AS", people=["Mats Carlin"]), "carlin.no"))
        self.assertTrue(acceptable_brand("AF Gruppen", Company(org="1", name="AF GRUPPEN ASA"), "afgruppen.no"))


class HtmlTests(unittest.TestCase):
    def test_parse(self):
        page = parse_html('<html lang="nb"><head><title>Acme AS</title><meta name="description" content="Vi lager ting">'
                          '<script type="application/ld+json">{"@type":"Organization","name":"Acme AS"}</script></head>'
                          '<body><nav><a href="/kontakt">Kontakt</a></nav><footer>Org.nr 810 034 882 '
                          '<a href="https://facebook.com/acme">Facebook</a></footer></body></html>', "https://acme.no/")
        self.assertEqual(page.title, "Acme AS")
        self.assertEqual(page.meta["description"], "Vi lager ting")
        self.assertIn("810 034 882", page.footer_text)
        self.assertTrue(any(l.url == "https://acme.no/kontakt" for l in page.links))
        self.assertEqual(page.jsonld_flat()[0]["name"], "Acme AS")


class RefreshTests(unittest.TestCase):
    def envelope(self, claims, run="r1"):
        return {"claims": claims, "evidence": [], "run": {"run_id": run, "completed_at": "2026-10-20T00:00:00Z"}}

    def claim(self, field, value, qualifier="", section="people", cid=None):
        return {"id": cid or f"c-{field}-{value}", "section": section, "field": field, "key": f"{field}|{qualifier}", "value": value,
                "display": str(value), "evidence_ids": ["ev-1"], "role_code": qualifier.split(":")[0] if qualifier else None}

    def test_same_snapshot_is_idempotent(self):
        claims = [self.claim("role", "Kari", "DAGL:Kari"), self.claim("legal_name", "X AS", section="identity")]
        changes, carried = diff({"claims": claims}, self.envelope(claims), set())
        self.assertEqual(changes, [])
        self.assertEqual(carried, [])

    def test_changes_and_carry_forward(self):
        old = [self.claim("role", "Kari", "DAGL:Kari"), self.claim("job_posting", "Ad", "uuid1", section="hiring")]
        new = [self.claim("role", "Ola", "DAGL:Ola")]
        changes, carried = diff({"claims": new}, self.envelope(old), failed_sections={"hiring"})
        kinds = sorted(c["type"] for c in changes)
        self.assertEqual(kinds, ["new_role", "removed_role"])
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["carried_forward_from"], "r1")


class SynthTests(unittest.TestCase):
    def test_unsupported_number_is_dropped(self):
        ledger = Ledger("1")
        ledger.json_claim(json_doc({"x": 10021242.0}), "/x", "accounts", "revenue")
        cid = ledger.claims[0]["id"]
        self.assertTrue(check_sentence({"text": "Revenue was NOK 10.0 m.", "claim_ids": [cid], "derived": {}}, ledger))
        self.assertFalse(check_sentence({"text": "Revenue was NOK 12.0 m.", "claim_ids": [cid], "derived": {}}, ledger))

    def test_summary_from_registry_claims(self):
        ledger = Ledger("810034882")
        doc = json_doc({"navn": "SANDNES ELEKTRISKE AS", "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
                        "forretningsadresse": {"kommune": "SANDNES"}, "stiftelsesdato": "1977-06-15"})
        ledger.json_claim(doc, "/navn", "identity", "legal_name")
        ledger.json_claim(doc, "/organisasjonsform", "identity", "legal_form", value={"code": "AS", "description": "Aksjeselskap"})
        ledger.json_claim(doc, "/forretningsadresse/kommune", "identity", "municipality")
        ledger.json_claim(doc, "/stiftelsesdato", "identity", "founded")
        summary = build_summary(ledger, {"accounts": [], "changes": [], "missing": ["website"]})
        self.assertIn("private limited company", summary["text"])
        self.assertIn("1977", summary["text"])
        self.assertEqual(summary["dropped_unsupported_sentences"], 0)


class NavTests(unittest.TestCase):
    def test_candidate_matching_by_name(self):
        nav = NavJobs(fetcher=None)  # type: ignore[arg-type]
        nav.active = {"a": {"businessName": "Sandnes Elektriske AS avd Service"}, "b": {"businessName": "Annen Bedrift AS"}}
        self.assertEqual(nav.candidate_ads(["SANDNES ELEKTRISKE AS"]), ["a"])


class CliTests(unittest.TestCase):
    def test_read_inputs_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "in.jsonl"
            p.write_text('{"organisation_number":"810034882"}\n{"organisation_number":"938 702 675"}\n{"organisation_number":"810034882"}\n')
            self.assertEqual(cli.read_inputs(str(p)), ["810034882", "938702675"])
            t = Path(tmp) / "in.txt"
            t.write_text("organisation_number\n810034882\n12345\n")
            self.assertEqual(cli.read_inputs(str(t)), ["810034882", "12345"])

    def test_every_input_gets_an_envelope_even_if_the_agent_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.txt"
            inp.write_text("810034882\n938702675\n12345\n")
            out = Path(tmp) / "out" / "envelopes.jsonl"
            with mock.patch("signalpost.agent.Agent.run", side_effect=RuntimeError("boom")):
                code = cli.main(["run", "--organisations", str(inp), "--output", str(out), "--no-site", "--cache-dir", str(Path(tmp) / "c")])
            rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["organisation_number"] for r in rows], ["810034882", "938702675", "12345"])
            self.assertTrue(all(r["status"] == "failed" for r in rows))
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
