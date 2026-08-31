from __future__ import annotations

from generated.C2.SanitisationRecord._1_0 import Rung
from generated.common.defs import SanitisationLabel

from gate.detectors import (
    _luhn_valid,
    detect_l0_structural,
    detect_l1_patterns,
    detect_l2_entities,
    detect_l3_example_values,
    detect_l4_sensitive_lexicon,
)
from gate.structure import ParsedDocument


class TestL0Structural:
    def test_one_span_per_structural_text(self) -> None:
        doc = ParsedDocument(kind="json_like", structural_texts=["claimId", "type", "properties"])
        spans = detect_l0_structural(doc)
        assert len(spans) == 3
        assert all(s.rung == Rung.L0 and s.label == SanitisationLabel.STRUCTURAL for s in spans)

    def test_empty_when_no_structural_texts(self) -> None:
        assert detect_l0_structural(ParsedDocument(kind="none")) == []


class TestL1Patterns:
    def test_uk_postcode(self) -> None:
        spans = detect_l1_patterns("Sample: SW1A 1AA in London")
        assert any(s.detector == "uk-postcode" and s.value == "SW1A 1AA" for s in spans)

    def test_us_ssn(self) -> None:
        spans = detect_l1_patterns("SSN on file: 123-45-6789")
        assert any(s.detector == "us-ssn" and s.value == "123-45-6789" for s in spans)

    def test_email(self) -> None:
        spans = detect_l1_patterns("Contact jane.doe@example.com for details")
        assert any(s.detector == "email" and s.value == "jane.doe@example.com" for s in spans)

    def test_us_zip4(self) -> None:
        spans = detect_l1_patterns("Mail to 90210-1234")
        assert any(s.detector == "us-zip4" and s.value == "90210-1234" for s in spans)

    def test_e164_phone(self) -> None:
        spans = detect_l1_patterns("Call +14155552671 now")
        assert any(s.detector == "e164-phone" for s in spans)

    def test_ni_number(self) -> None:
        spans = detect_l1_patterns("NI: AB123456C on record")
        assert any(s.detector == "ni-number" and s.value.upper() == "AB123456C" for s in spans)

    def test_iban(self) -> None:
        spans = detect_l1_patterns("Account IBAN GB29NWBK60161331926819 held")
        assert any(s.detector == "iban" for s in spans)

    def test_valid_luhn_card_pan_flagged(self) -> None:
        # 4111111111111111 is a well-known Luhn-valid test Visa number
        spans = detect_l1_patterns("Card on file: 4111111111111111")
        assert any(s.detector == "card-pan" for s in spans)

    def test_luhn_invalid_number_not_flagged_as_card(self) -> None:
        spans = detect_l1_patterns("Reference number: 1234567890123456")
        assert not any(s.detector == "card-pan" for s in spans)

    def test_dob_in_context_flags_the_date_not_the_keyword(self) -> None:
        spans = detect_l1_patterns("Date of birth: 1985-03-14, confirmed")
        hits = [s for s in spans if s.detector == "dob-in-context"]
        assert len(hits) == 1
        assert hits[0].value == "1985-03-14"

    def test_ordinary_date_field_without_dob_context_not_flagged(self) -> None:
        # Guards against false-positiving on ordinary business dates like
        # the golden corpus's own lossDate/notificationDate fields.
        spans = detect_l1_patterns("lossDate: 2026-01-15 was recorded for the claim")
        assert not any(s.detector == "dob-in-context" for s in spans)

    def test_no_hits_on_clean_business_prose(self) -> None:
        spans = detect_l1_patterns("Reserved settlement amount for the claim.")
        assert spans == []


class TestLuhnCheck:
    def test_known_valid_number(self) -> None:
        assert _luhn_valid("4111111111111111") is True

    def test_known_invalid_number(self) -> None:
        assert _luhn_valid("4111111111111112") is False


class TestL2Entities:
    def test_real_name_example_flagged(self) -> None:
        spans = detect_l2_entities("A. Smith")
        assert len(spans) == 1
        assert spans[0].value == "A. Smith"
        assert spans[0].label == SanitisationLabel.IDENTIFYING

    def test_all_uppercase_acronym_pair_not_flagged(self) -> None:
        # "FNOL Glossary" - real text from the golden Confluence fixture.
        # All-uppercase tokens are deliberately excluded from the
        # Title-Case heuristic.
        spans = detect_l2_entities("FNOL Glossary")
        assert spans == []

    def test_documented_false_positive_on_ordinary_business_phrase(self) -> None:
        # "First Notification" - real text from the golden Confluence
        # fixture's own body ("First Notification of Loss"). A known,
        # accepted limitation of the heuristic: both tokens are
        # legitimate Title-Case words, so this reads exactly like a
        # PERSON/ORG/LOC candidate to a naive heuristic. Documented here
        # deliberately, not hidden - the failure direction (over-masking
        # harmless prose) is the safe one for a redactor.
        spans = detect_l2_entities("First Notification of Loss")
        assert any(s.value == "First Notification" for s in spans)

    def test_single_capitalised_word_not_flagged(self) -> None:
        assert detect_l2_entities("Glossary") == []


class TestL3ExampleValues:
    def test_one_span_per_example_text_regardless_of_content(self) -> None:
        doc = ParsedDocument(kind="json_like", example_texts=["A. Smith, SW1A 1AA", "OPEN"])
        spans = detect_l3_example_values(doc)
        assert len(spans) == 2
        assert all(s.rung == Rung.L3 and s.label == SanitisationLabel.SAMPLE_VALUE for s in spans)

    def test_empty_when_no_example_texts(self) -> None:
        assert detect_l3_example_values(ParsedDocument(kind="none")) == []


class TestL4SensitiveLexicon:
    def test_medical_term_flagged(self) -> None:
        spans = detect_l4_sensitive_lexicon("Patient diagnosis on file")
        assert any(s.value.lower() == "diagnosis" for s in spans)

    def test_multi_word_term_flagged(self) -> None:
        spans = detect_l4_sensitive_lexicon("History of substance abuse noted")
        assert any(s.value.lower() == "substance abuse" for s in spans)

    def test_short_term_does_not_false_positive_inside_a_longer_word(self) -> None:
        # "hiv" must not match inside "archive" - word-boundary matching.
        spans = detect_l4_sensitive_lexicon("Documents are stored in the archive")
        assert spans == []

    def test_clean_text_has_no_hits(self) -> None:
        assert detect_l4_sensitive_lexicon("Reserved settlement amount for the claim.") == []
