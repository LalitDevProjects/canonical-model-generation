"""
The L0-L4 classification ladder (Section 5.2). L5 (licence/IP register)
is NOT here - it's a direct licenceDisposition lookup, not a content
detector, living in connectors/manifest.py alongside the existing
_DEFAULT_EVIDENCE_TIER_BY_SYSTEM pattern.

Rung -> label mapping (the spec never states this explicitly - see
gate/gate.py's module docstring for the full reasoning): L0->STRUCTURAL,
L1->IDENTIFYING, L2->IDENTIFYING, L3->SAMPLE_VALUE, L4->SENSITIVE_DOMAIN.
PERSONAL_DATA is not produced by any detector here (a genuine spec gap,
not an oversight - see gate/gate.py).

"The ladder runs to completion - it does not short-circuit on the first
hit." Every detector below is applied independently and unconditionally;
overlapping/duplicate hits across detectors and rungs are expected and
recorded, not deduplicated away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from generated.C2.SanitisationRecord._1_0 import Rung
from generated.common.defs import SanitisationLabel

from gate.structure import ParsedDocument


@dataclass(frozen=True)
class Span:
    rung: Rung
    label: SanitisationLabel
    value: str
    detector: str


def detect_l0_structural(doc: ParsedDocument) -> list[Span]:
    """"Grammar-position match: element and attribute names, type
    declarations, cardinality and constraint keywords." - every text
    gate/structure.py classified as structural (dict keys, XSD
    element/attribute/type names) is one L0 hit."""
    return [
        Span(Rung.L0, SanitisationLabel.STRUCTURAL, text, "structural-allow-list")
        for text in doc.structural_texts
    ]


def detect_l3_example_values(doc: ParsedDocument) -> list[Span]:
    """"Any literal appearing in example, examples, default, const, enum
    description text or a test fixture." - positional, not pattern-based:
    every literal gate/structure.py found at an example-position is
    flagged unconditionally, regardless of its content."""
    return [
        Span(Rung.L3, SanitisationLabel.SAMPLE_VALUE, text, "example-value-rule")
        for text in doc.example_texts
    ]


# --- L1: pattern detectors --------------------------------------------
# "Compiled regex set: NI number, SSN, IBAN, card PAN with Luhn check, UK
# postcode, US ZIP+4, e-mail, E.164 phone, date of birth in context."
# Every pattern below is a documented simplification of the real-world
# format (e.g. the NI number pattern doesn't exclude the handful of
# officially-invalid prefix pairs) - sufficient to catch realistic
# examples, not a compliance-grade validator.

_NI_NUMBER = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b", re.IGNORECASE)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z0-9]?\s?\d[A-Z]{2}\b", re.IGNORECASE)
_US_ZIP4 = re.compile(r"\b\d{5}-\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_E164_PHONE = re.compile(r"\+[1-9]\d{6,14}\b")
_DOB_CONTEXT_KEYWORD = re.compile(r"\b(date of birth|dob|born|birthdate)\b", re.IGNORECASE)
_DATE_LITERAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_DOB_CONTEXT_WINDOW = 40


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def detect_l1_patterns(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in _NI_NUMBER.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "ni-number"))
    for match in _SSN.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "us-ssn"))
    for match in _IBAN.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "iban"))
    for match in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if _luhn_valid(digits):
            spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "card-pan"))
    for match in _UK_POSTCODE.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "uk-postcode"))
    for match in _US_ZIP4.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "us-zip4"))
    for match in _EMAIL.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "email"))
    for match in _E164_PHONE.finditer(text):
        spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, match.group(), "e164-phone"))
    for context_match in _DOB_CONTEXT_KEYWORD.finditer(text):
        window_start = max(0, context_match.start() - _DOB_CONTEXT_WINDOW)
        window_end = min(len(text), context_match.end() + _DOB_CONTEXT_WINDOW)
        date_match = _DATE_LITERAL.search(text[window_start:window_end])
        if date_match:
            spans.append(Span(Rung.L1, SanitisationLabel.IDENTIFYING, date_match.group(), "dob-in-context"))
    return spans


# --- L2: entity recognition --------------------------------------------
# "Local NER model for PERSON, ORG, LOC over free-text spans." Confirmed
# decision: a lightweight, stdlib-only heuristic (consecutive Title-Case
# tokens), not a real NER model - see docs/increments.md for the full
# reasoning. Deliberately excludes all-uppercase tokens (e.g. "FNOL"),
# which would otherwise false-positive on acronyms; this does NOT exclude
# ordinary two-word Title-Case business phrases (e.g. "First Notification"
# inside "First Notification of Loss") - a documented, accepted false
# positive, since L2 only ever produces `mask`, never `block`: the safe
# failure direction is over-masking harmless prose, not under-masking
# real PII.
_TITLE_CASE_TOKEN = r"(?:[A-Z][a-z]+|[A-Z]\.)"
_TITLE_CASE_SEQUENCE = re.compile(rf"{_TITLE_CASE_TOKEN}(?:\s+{_TITLE_CASE_TOKEN})+")


def detect_l2_entities(text: str) -> list[Span]:
    return [
        Span(Rung.L2, SanitisationLabel.IDENTIFYING, match.group(), "title-case-sequence")
        for match in _TITLE_CASE_SEQUENCE.finditer(text)
    ]


# --- L4: sensitive-domain lexicon ---------------------------------------
# "Curated term list: medical, injury, criminal, financial-hardship
# vocabulary, reviewed quarterly by the DPO." A starter list, not the
# real DPO-reviewed quarterly list (no DPO exists in this PoC) - a
# builder placeholder, same honesty standard as everything else flagged
# in this repo.
_SENSITIVE_LEXICON: tuple[str, ...] = (
    "diagnosis", "psychiatric", "hiv", "substance abuse", "criminal conviction",
    "bankruptcy", "county court judgment", "domestic violence",
)
_SENSITIVE_LEXICON_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in _SENSITIVE_LEXICON) + r")\b",
    re.IGNORECASE,
)


def detect_l4_sensitive_lexicon(text: str) -> list[Span]:
    return [
        Span(Rung.L4, SanitisationLabel.SENSITIVE_DOMAIN, match.group(), "sensitive-domain-lexicon")
        for match in _SENSITIVE_LEXICON_PATTERN.finditer(text)
    ]
