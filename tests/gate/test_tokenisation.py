from __future__ import annotations

from generated.C2.SanitisationRecord._1_0 import Rung
from generated.common.defs import SanitisationLabel

from gate.detectors import Span
from gate.structure import ParsedDocument
from gate.tokenisation import redact, region_key_bytes, tokenise

KEY_A = bytes.fromhex("a" * 64)
KEY_B = bytes.fromhex("b" * 64)


class TestTokenise:
    def test_deterministic_for_same_inputs(self) -> None:
        assert tokenise("A. Smith", "PERSON", KEY_A) == tokenise("A. Smith", "PERSON", KEY_A)

    def test_label_prefix_visible_in_output(self) -> None:
        assert tokenise("A. Smith", "PERSON", KEY_A).startswith("<PERSON:")

    def test_different_region_keys_produce_different_tokens(self) -> None:
        # "The central platform can tell that two occurrences are the
        # same entity... but cannot recover the value" - reproducing the
        # spec's own two worked outputs at different region keys.
        assert tokenise("A. Smith", "PERSON", KEY_A) != tokenise("A. Smith", "PERSON", KEY_B)

    def test_different_labels_produce_different_tokens_for_the_same_value(self) -> None:
        assert tokenise("X", "PERSON", KEY_A) != tokenise("X", "POSTCODE", KEY_A)

    def test_value_is_not_recoverable_from_the_token(self) -> None:
        token = tokenise("A. Smith", "PERSON", KEY_A)
        assert "A. Smith" not in token

    def test_sixteen_hex_char_digest(self) -> None:
        token = tokenise("A. Smith", "PERSON", KEY_A)
        digest = token.split(":")[1].rstrip(">")
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)


class TestRegionKeyBytes:
    def test_decodes_configured_hex_key(self) -> None:
        from config.settings import EgressConfig

        cfg = EgressConfig.model_validate({
            "policy_version": 3, "fail_mode": "closed",
            "ledger_signing_key": "a" * 64,
            "tokenisation_keys": {"us": "b" * 64, "uk": "c" * 64, "eu": "d" * 64},
        })
        assert region_key_bytes("uk", cfg) == bytes.fromhex("c" * 64)


class TestRedact:
    def test_no_op_when_no_mask_spans(self) -> None:
        content = b"clean content, nothing to redact"
        assert redact(content, [], KEY_A, None) == content

    def test_l0_and_l3_alone_are_not_masked_l3_is(self) -> None:
        # L0 (STRUCTURAL) never triggers masking on its own - only
        # L1/L2/L3 do.
        content = b"claimId"
        l0_only = [Span(Rung.L0, SanitisationLabel.STRUCTURAL, "claimId", "structural-allow-list")]
        assert redact(content, l0_only, KEY_A, None) == content

    def test_masks_a_single_detected_value(self) -> None:
        content = b"reference: A. Smith on file"
        spans = [Span(Rung.L2, SanitisationLabel.IDENTIFYING, "A. Smith", "title-case-sequence")]
        redacted = redact(content, spans, KEY_A, None)
        assert b"A. Smith" not in redacted
        assert tokenise("A. Smith", "IDENTIFYING", KEY_A).encode() in redacted

    def test_longest_span_wins_when_spans_overlap(self) -> None:
        # The real planted-fixture shape: the whole example value (L3)
        # contains an independently-detected postcode substring (L1).
        content = b"example: A. Smith, SW1A 1AA"
        spans = [
            Span(Rung.L3, SanitisationLabel.SAMPLE_VALUE, "A. Smith, SW1A 1AA", "example-value-rule"),
            Span(Rung.L1, SanitisationLabel.IDENTIFYING, "SW1A 1AA", "uk-postcode"),
        ]
        redacted = redact(content, spans, KEY_A, None)
        assert b"A. Smith" not in redacted
        assert b"SW1A 1AA" not in redacted
        assert tokenise("A. Smith, SW1A 1AA", "SAMPLE_VALUE", KEY_A).encode() in redacted

    def test_repeated_occurrences_of_the_same_value_all_replaced(self) -> None:
        content = b"jane.doe@example.com appears twice: jane.doe@example.com"
        spans = [Span(Rung.L1, SanitisationLabel.IDENTIFYING, "jane.doe@example.com", "email")]
        redacted = redact(content, spans, KEY_A, None)
        assert b"jane.doe@example.com" not in redacted
        assert redacted.count(tokenise("jane.doe@example.com", "IDENTIFYING", KEY_A).encode()) == 2

    def test_structured_argument_is_accepted_but_does_not_change_output(self) -> None:
        content = b"A. Smith"
        spans = [Span(Rung.L2, SanitisationLabel.IDENTIFYING, "A. Smith", "title-case-sequence")]
        doc = ParsedDocument(kind="json_like")
        assert redact(content, spans, KEY_A, doc) == redact(content, spans, KEY_A, None)
