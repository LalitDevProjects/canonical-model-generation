"""
Code contract inference (Section 4.5): deterministic AST analysis of
source repositories where no published contract exists.

Out of scope for Increment 3, and for every other increment in the PoC
Build Guide as currently written - Section 4.5's INFERENCE_ORDER/
confidence-scoring/inference_floor pipeline is never bound to any of the
nine increments' acceptance tests (verified against all of I1-I9). It's
co-located in this directory only because the spec's own repository
layout (Section 17.4) lists parsers/code_inference.py alongside
openapi.py/xsd.py/avro.py. Revisit as its own increment/decision point if
and when code-only, undocumented services become a real target for a
future wave - see docs/increments.md.
"""
