from __future__ import annotations

from uuid import uuid4

from golden_helpers import golden_xsd, make_source_artefact

from generated.C5.AttributeRecord._1_0 import C5Attributerecord

from algorithms.profiling import profile
from parsers.xsd import parse_xsd

RUN_ID = uuid4()


def _parse_claim_notification() -> list[C5Attributerecord]:
    content = golden_xsd("uk/ClaimNotification.xsd")
    source_artefact = make_source_artefact("application/xml", region="uk")
    return parse_xsd(content, source_artefact, RUN_ID)


def _by_path(records: list[C5Attributerecord], path: str) -> C5Attributerecord:
    return next(r for r in records if r.path == path)


def test_xsd_choice_survives_as_variants() -> None:
    """The spec's own worked golden-file test (Section 16.3), reproduced
    as close to verbatim as the real generated model allows."""
    records = _parse_claim_notification()
    branches = [r for r in records if r.typeDetail and r.typeDetail.choiceGroup == "notifier"]
    assert len(branches) == 3
    assert all(r.obligation.level == "conditional" for r in branches)
    assert not any(r.obligation.level == "optional" for r in branches), (
        "choice branches must not be flattened into independent optional fields"
    )


class TestChoiceIdiom:
    def test_branch_names(self) -> None:
        records = _parse_claim_notification()
        branches = {r.localName for r in records if r.typeDetail and r.typeDetail.choiceGroup == "notifier"}
        assert branches == {"brokerNotifier", "policyholderNotifier", "thirdPartyNotifier"}

    def test_descendants_of_a_branch_do_not_inherit_choice_group(self) -> None:
        records = _parse_claim_notification()
        broker_reference = _by_path(records, "ClaimNotification.brokerNotifier.brokerReference")
        assert broker_reference.typeDetail is None or broker_reference.typeDetail.choiceGroup is None
        assert broker_reference.obligation.level == "mandatory"


class TestSubstitutionGroupIdiom:
    def test_head_is_marked(self) -> None:
        records = _parse_claim_notification()
        head = _by_path(records, "BaseNotificationEvent")
        assert head.typeDetail is not None
        assert head.typeDetail.substitutionHead is True

    def test_member_references_the_heads_real_attribute_id(self) -> None:
        records = _parse_claim_notification()
        head = _by_path(records, "BaseNotificationEvent")
        member = _by_path(records, "UrgentNotificationEvent")
        assert member.typeDetail is not None
        assert member.typeDetail.substitutionOf == head.attributeId


class TestAttributeVersusElementNormalisation:
    def test_attribute_and_element_forms_produce_the_same_record_shape(self) -> None:
        records = _parse_claim_notification()
        attribute_form = _by_path(records, "ClaimNotification.claimReference")
        element_form = _by_path(records, "ClaimNotification.claimReferenceCode")
        assert attribute_form.dataType == element_form.dataType == "string"
        assert attribute_form.parentPath == element_form.parentPath == "ClaimNotification"
        # Neither carries any marker distinguishing "came from an XML
        # attribute" from "came from an XML element" - normalised away.
        assert attribute_form.typeDetail is None
        assert element_form.typeDetail is None

    def test_required_attribute_is_mandatory_1_1(self) -> None:
        records = _parse_claim_notification()
        rec = _by_path(records, "ClaimNotification.claimReference")
        assert rec.obligation.level == "mandatory"
        assert rec.cardinality == "1..1"


class TestNillableVersusMinOccurs:
    def test_nillable_sets_explicit_null_but_cardinality_stays_1_1(self) -> None:
        records = _parse_claim_notification()
        rec = _by_path(records, "ClaimNotification.settlementNote")
        assert rec.typeDetail is not None
        assert rec.typeDetail.explicitNull is True
        assert rec.cardinality == "1..1"

    def test_min_occurs_zero_sets_cardinality_but_not_explicit_null(self) -> None:
        records = _parse_claim_notification()
        rec = _by_path(records, "ClaimNotification.priorClaimReference")
        assert rec.cardinality == "0..1"
        assert rec.obligation.level == "optional"
        assert rec.typeDetail is None or rec.typeDetail.explicitNull is None


class TestExtensionFlattening:
    def test_inherited_member_is_marked(self) -> None:
        records = _parse_claim_notification()
        inherited = _by_path(records, "UrgentNotificationEvent.eventId")
        assert inherited.typeDetail is not None
        assert inherited.typeDetail.inheritedFrom == "BaseNotificationEventType"

    def test_own_new_members_are_not_marked_inherited(self) -> None:
        records = _parse_claim_notification()
        own = _by_path(records, "UrgentNotificationEvent.receivedAt")
        assert own.typeDetail is None or own.typeDetail.inheritedFrom is None
        assert own.dataType == "dateTime"
        assert own.typeDetail is not None and own.typeDetail.offsetRequired is False


class TestUntypedDatePlantedCase:
    def test_notification_date_stays_string_at_parser_level(self) -> None:
        """Parser fidelity half of the third acceptance clause."""
        records = _parse_claim_notification()
        rec = _by_path(records, "ClaimNotification.notificationDate")
        assert rec.dataType == "string"
        assert rec.semantics is not None
        assert rec.semantics.description == "Date the notification was received."

    def test_untyped_date_raises_type_suspicion(self) -> None:
        """The literal, direct realisation of Increment 3's third
        acceptance clause: "the untyped date raises type-suspicion." The
        parser (parsers/xsd.py, tested above) records dataType=string,
        faithful to the contract; profile() (algorithms/profiling.py),
        run as a wholly separate, later pass, independently raises the
        finding - proving the two-pass separation the spec insists on
        ("the parser records what the contract says, the profiler
        records what it suspects, and the two are never conflated")
        structurally, against the real planted golden fixture, not a
        hand-built record."""
        records = _parse_claim_notification()
        notification_date = _by_path(records, "ClaimNotification.notificationDate")
        assert notification_date.dataType == "string"

        profiled = profile(notification_date, siblings=records)
        assert any(finding.kind == "type-suspicion" for finding in profiled.findings)


def _parse_inline_xsd(xml: str) -> list[C5Attributerecord]:
    from parsers.xsd import parse_xsd as _parse

    source_artefact = make_source_artefact("application/xml", region="uk")
    return _parse(xml.encode(), source_artefact, uuid4())


class TestMaxOccursArrayCardinality:
    def test_max_occurs_unbounded_gives_1_n_when_required(self) -> None:
        records = _parse_inline_xsd("""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="ClaimList">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="claimId" type="xs:string" maxOccurs="unbounded"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>""")
        rec = next(r for r in records if r.path == "ClaimList.claimId")
        assert rec.cardinality == "1..n"

    def test_max_occurs_unbounded_with_min_occurs_zero_gives_0_n(self) -> None:
        records = _parse_inline_xsd("""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="ClaimList">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="claimId" type="xs:string" minOccurs="0" maxOccurs="unbounded"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>""")
        rec = next(r for r in records if r.path == "ClaimList.claimId")
        assert rec.cardinality == "0..n"


class TestInheritedAttribute:
    def test_attribute_on_base_type_is_marked_inherited(self) -> None:
        records = _parse_inline_xsd("""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:t" xmlns:tns="urn:t">
  <xs:element name="Derived" type="tns:DerivedType"/>
  <xs:complexType name="BaseType">
    <xs:attribute name="baseAttr" type="xs:string"/>
  </xs:complexType>
  <xs:complexType name="DerivedType">
    <xs:complexContent>
      <xs:extension base="tns:BaseType">
        <xs:sequence>
          <xs:element name="ownField" type="xs:string"/>
        </xs:sequence>
      </xs:extension>
    </xs:complexContent>
  </xs:complexType>
</xs:schema>""")
        base_attr = next(r for r in records if r.path == "Derived.baseAttr")
        assert base_attr.typeDetail is not None
        assert base_attr.typeDetail.inheritedFrom == "BaseType"


class TestChoiceWithNonElementChild:
    def test_annotation_inside_choice_is_ignored(self) -> None:
        records = _parse_inline_xsd("""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Root">
    <xs:complexType>
      <xs:choice id="grp">
        <xs:annotation><xs:documentation>a note, not a branch</xs:documentation></xs:annotation>
        <xs:element name="branchA" type="xs:string"/>
      </xs:choice>
    </xs:complexType>
  </xs:element>
</xs:schema>""")
        branches = [r for r in records if r.typeDetail and r.typeDetail.choiceGroup == "grp"]
        assert len(branches) == 1
        assert branches[0].localName == "branchA"
