from __future__ import annotations

from uuid import uuid4

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.blocking import Block, build_blocks, dedupe_blocks, lemmatise, type_noun_tokens
from algorithms.profiling import ProfiledAttribute, profile
from config.settings import ClusteringConfig

RUN_ID = uuid4()
_CFG = ClusteringConfig()


def _attr(local_name: str, data_type: str, **overrides: object) -> C5Attributerecord:
    payload: dict[str, object] = {
        "attributeId": f"attr://us/art-1/Claim.{local_name}",
        "runId": str(RUN_ID),
        "region": "us",
        "sourceContract": "art-1",
        "path": f"Claim.{local_name}",
        "localName": local_name,
        "dataType": data_type,
        "cardinality": "1..1",
        "obligation": {"level": "mandatory"},
        "evidenceTier": 1,
        "inferred": False,
        "evidenceRefs": ["evref://us/git/art-1@1234567890abcdef#/x"],
    }
    payload.update(overrides)
    return C5Attributerecord.model_validate(payload)


def _profiled(local_name: str, data_type: str, **overrides: object) -> ProfiledAttribute:
    return profile(_attr(local_name, data_type, **overrides), siblings=[])


class TestLemmatise:
    def test_plural_ies(self) -> None:
        assert lemmatise("policies") == "policy"

    def test_plural_s(self) -> None:
        assert lemmatise("amounts") == "amount"

    def test_plural_ches(self) -> None:
        assert lemmatise("matches") == "match"

    def test_does_not_strip_ss(self) -> None:
        assert lemmatise("address") == "address"

    def test_short_token_untouched(self) -> None:
        assert lemmatise("loss") == "loss"

    def test_gerund(self) -> None:
        assert lemmatise("processing") == "process"


class TestTypeNounTokens:
    def test_includes_abbreviation_values_and_profiling_sets(self) -> None:
        tokens = type_noun_tokens(_CFG)
        assert "date" in tokens  # from abbreviations["dt"]
        assert "amount" in tokens  # from profiling.MONETARY_TOKENS
        assert "code" in tokens  # from abbreviations["cd"]


class TestBuildBlocksByHead:
    def test_synonym_triple_co_blocks_on_head_noun(self) -> None:
        loss_date = _profiled("lossDate", "date", attributeId="attr://us/art-1/Claim.lossDate")
        date_of_loss = _profiled("dateOfLoss", "date", attributeId="attr://uk/art-2/Claim.dateOfLoss", region="uk", sourceContract="art-2")
        date_survenance = _profiled(
            "dateSurvenance", "date", attributeId="attr://eu/art-3/Claim.dateSurvenance", region="eu", sourceContract="art-3"
        )
        blocks = build_blocks([loss_date, date_of_loss, date_survenance], config=_CFG)
        head_block_member_ids = {
            frozenset(m.record.attributeId for m in b.members) for b in blocks
        }
        assert frozenset(
            {loss_date.record.attributeId, date_of_loss.record.attributeId, date_survenance.record.attributeId}
        ) in head_block_member_ids

    def test_singleton_head_group_produces_no_block(self) -> None:
        lone = _profiled("uniqueField", "string")
        blocks = build_blocks([lone], config=_CFG)
        assert blocks == []

    def test_unrelated_attributes_do_not_co_block(self) -> None:
        a = _profiled("claimantName", "string", attributeId="attr://us/art-1/Claim.claimantName")
        b = _profiled("policyNumber", "string", attributeId="attr://us/art-1/Claim.policyNumber")
        blocks = build_blocks([a, b], config=_CFG)
        assert blocks == []


class TestBuildBlocksByType:
    def test_same_type_family_and_head_prefix_co_blocks(self) -> None:
        a = _profiled("reserveAmt", "decimal", attributeId="attr://us/art-1/Claim.reserveAmt")
        b = _profiled("premiumAmount", "decimal", attributeId="attr://us/art-1/Claim.premiumAmount")
        blocks = build_blocks([a, b], config=_CFG)
        member_id_sets = {frozenset(m.record.attributeId for m in blk.members) for blk in blocks}
        assert frozenset({a.record.attributeId, b.record.attributeId}) in member_id_sets


class TestBuildBlocksByEmbedding:
    def test_no_api_degrades_to_no_embedding_block(self) -> None:
        a = _profiled("uniqueOne", "string")
        b = _profiled("uniqueTwo", "integer", attributeId="attr://us/art-1/Claim.uniqueTwo")
        blocks = build_blocks([a, b], api=None, run_id=str(RUN_ID), config=_CFG)
        assert blocks == []  # no shared head/type key, no api -> nothing

    def test_api_supplies_embedding_block_including_anchor(self) -> None:
        anchor = _profiled("weirdOne", "string", attributeId="attr://us/art-1/Claim.weirdOne")
        neighbour_record = _attr("weirdTwo", "boolean", attributeId="attr://us/art-1/Claim.weirdTwo")

        class _FakeApi:
            def neighbours(self, run_id: str, attribute_id: str, *, top_k: int = 25) -> list[C5Attributerecord]:
                if attribute_id == anchor.record.attributeId:
                    return [neighbour_record]
                return []

        neighbour_profiled = profile(neighbour_record, siblings=[])
        blocks = build_blocks([anchor, neighbour_profiled], api=_FakeApi(), run_id=str(RUN_ID), config=_CFG)
        member_id_sets = {frozenset(m.record.attributeId for m in blk.members) for blk in blocks}
        assert frozenset({anchor.record.attributeId, neighbour_record.attributeId}) in member_id_sets

    def test_neighbour_not_in_attrs_is_skipped(self) -> None:
        anchor = _profiled("loneOne", "string", attributeId="attr://us/art-1/Claim.loneOne")

        class _FakeApi:
            def neighbours(self, run_id: str, attribute_id: str, *, top_k: int = 25) -> list[C5Attributerecord]:
                return [_attr("elsewhere", "string", attributeId="attr://us/art-9/Claim.elsewhere")]

        blocks = build_blocks([anchor], api=_FakeApi(), run_id=str(RUN_ID), config=_CFG)
        assert blocks == []


class TestDedupeBlocks:
    def test_exact_duplicate_blocks_collapse(self) -> None:
        a = _profiled("x", "string", attributeId="attr://us/art-1/Claim.x")
        b = _profiled("y", "string", attributeId="attr://us/art-1/Claim.y")
        blocks = [Block(members=(a, b)), Block(members=(b, a))]
        result = dedupe_blocks(blocks, max_size=40)
        assert len(result) == 1

    def test_singleton_block_dropped(self) -> None:
        a = _profiled("x", "string")
        result = dedupe_blocks([Block(members=(a,))], max_size=40)
        assert result == []

    def test_oversized_block_truncated_deterministically(self) -> None:
        members = tuple(
            _profiled(f"f{i}", "string", attributeId=f"attr://us/art-1/Claim.f{i}") for i in range(5)
        )
        result = dedupe_blocks([Block(members=members)], max_size=3)
        assert len(result) == 1
        assert len(result[0].members) == 3
        ids = [m.record.attributeId for m in result[0].members]
        assert ids == sorted(ids)

    def test_truncation_is_reproducible_across_calls(self) -> None:
        members = tuple(
            _profiled(f"g{i}", "string", attributeId=f"attr://us/art-1/Claim.g{i}") for i in range(5)
        )
        first = dedupe_blocks([Block(members=members)], max_size=3)
        second = dedupe_blocks([Block(members=members)], max_size=3)
        assert [m.record.attributeId for m in first[0].members] == [m.record.attributeId for m in second[0].members]
