"""Offline storage semantics; status changes are fixtures, not verification runs."""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from memory.shared_memory import Claim, ClaimVersionRef, Evidence, FiscalPeriod, SharedMemory, SourceDocument


@pytest.fixture
def source_and_claim():
    gold_path = Path(__file__).parent / "fixtures" / "nvidia_2024" / "annotations.json"
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    doc, cell = gold["document"], gold["values"][0]
    identity = dict(source=doc["title"], source_id="sha256:" + doc["sha256"],
                    source_url=doc["source_url"], source_type="annual_report")
    basis = doc["currency_basis"]
    source = SourceDocument(
        title=doc["title"], entity=doc["entity"], source_url=doc["source_url"], sha256=doc["sha256"],
        currency=doc["currency"], currency_evidence=Evidence(
            **identity, page=basis["pdf_page"], printed_page=basis["printed_page"],
            section=basis["section"], locator="currency-context", quote=basis["quote"],
        ),
    )
    claim = Claim(
        claim_id=f"{source.source_id}:{cell['metric']}:{cell['period_end']}",
        agent="DocumentAgent", claim_type="raw_primitive", entity=source.entity,
        metric=cell["metric"], value=Decimal(cell["value"]), unit=gold["unit"],
        currency=gold["currency"], scale=gold["scale"],
        period=FiscalPeriod(kind=cell["period_kind"], end_date=date.fromisoformat(cell["period_end"]),
                            label="Year ended " + cell["column"]),
        claim="Revenue in the cited fiscal-period column", support_level="single_source",
        evidence=(Evidence(
            **identity, page=cell["pdf_page"], printed_page=cell["printed_page"], section=cell["table"],
            locator="income/revenue/" + cell["column"], quote="Revenue $ 60,922 $ 26,974 $ 26,914",
            bbox=tuple(cell["row_bbox"]), row_label=cell["row"], column_header=cell["column"],
            raw_value=cell["raw_value"], scale_header=cell["scale_header"], period_header=cell["column"],
        ),), timestamp=datetime(2024, 2, 21, tzinfo=timezone.utc),
    )
    return source, claim


@pytest.fixture
def memory(source_and_claim):
    store = SharedMemory("run-a")
    store.register_source(source_and_claim[0])
    return store


def revision(claim, **changes):
    data = claim.model_dump(round_trip=True)
    data.update(changes)
    return Claim.model_validate(data)


def test_first_insertion_and_exact_identity(memory, source_and_claim):
    _, claim = source_and_claim
    assert memory.get_claims() == []
    accepted = memory.append(claim)
    assert accepted == claim and accepted is not claim
    assert accepted.verification_status == "pending"
    assert accepted.support_level == "single_source"
    assert memory.get_claim(claim.claim_id) == claim
    assert memory.get_current(claim.claim_id) == claim
    assert memory.get_history(claim.claim_id) == [claim]
    assert memory.reference(claim.claim_id) == ClaimVersionRef(
        run_id="run-a", claim_id=claim.claim_id, version=1,
    )
    assert memory.resolve(memory.reference(claim.claim_id)) == claim


def test_revisions_history_and_iteration_are_separate(memory, source_and_claim):
    claim = source_and_claim[1]
    memory.append(claim)
    checked = revision(claim, version=2, verification_status="verified")
    memory.append(checked)
    # A backdated timestamp does not change the version ordering.
    latest = revision(checked, version=3, verification_status="flagged",
                      timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc))
    memory.append(latest)
    assert memory.get_history(claim.claim_id) == [claim, checked, latest]
    assert memory.get_claim(claim.claim_id, 2) == checked
    assert memory.get_current(claim.claim_id) == latest
    assert [c.version for c in memory.get_claims()] == [3]
    assert [c.version for c in memory.get_claims(min_version_only=False)] == [1, 2, 3]
    assert all(c.run_iteration == 0 for c in memory.get_history(claim.claim_id))


@pytest.mark.parametrize("next_version", [1, 3])
def test_duplicate_and_skipped_versions_are_rejected_atomically(memory, source_and_claim, next_version):
    claim = source_and_claim[1]
    memory.append(claim)
    with pytest.raises(ValueError):
        memory.append(revision(claim, version=next_version))
    assert memory.get_history(claim.claim_id) == [claim]
    assert memory.get_support_references(claim.claim_id) == ()


def test_first_version_must_be_one(memory, source_and_claim):
    with pytest.raises(ValueError, match="start at 1"):
        memory.append(revision(source_and_claim[1], version=2))
    assert memory.get_claims() == []


def test_iteration_cannot_go_backwards(memory, source_and_claim):
    claim = revision(source_and_claim[1], run_iteration=1)
    memory.append(claim)
    with pytest.raises(ValueError, match="cannot decrease"):
        memory.append(revision(claim, version=2, run_iteration=0))
    assert memory.get_current(claim.claim_id) == claim


@pytest.mark.parametrize("status", ["pending", "flagged", "unresolved"])
@pytest.mark.parametrize("support", ["single_source", "unsupported"])
def test_newest_version_is_resolved_before_status_and_support_filters(
    memory, source_and_claim, status, support,
):
    checked = revision(source_and_claim[1], verification_status="verified")
    memory.append(checked)
    latest = revision(checked, version=2, verification_status=status, support_level=support)
    memory.append(latest)
    assert memory.get_claims(verification_status="verified") == []
    assert memory.get_claims(verification_status="verified", support_level="single_source") == []
    assert memory.get_claims(verification_status=status, support_level=support) == [latest]
    if support == "unsupported":
        assert memory.get_claims(support_level="single_source") == []
    assert memory.get_claim(checked.claim_id, 1) == checked  # explicit historical access
    with pytest.raises(ValueError, match="History views cannot be filtered"):
        memory.get_claims(min_version_only=False, verification_status="verified")


def test_runs_do_not_share_claims_sources_or_exact_references(memory, source_and_claim):
    source, claim = source_and_claim
    memory.append(claim)
    other = SharedMemory("run-b")
    assert other.get_claims() == []
    with pytest.raises(KeyError):
        other.get_source(source.source_id)
    with pytest.raises(KeyError):
        other.get_current(claim.claim_id)
    with pytest.raises(ValueError, match="another run"):
        other.resolve(memory.reference(claim.claim_id))
    other.register_source(source)
    other.append(claim)  # same logical claim/version is allowed in another run
    other.append(revision(claim, version=2, verification_status="flagged"))
    assert memory.get_current(claim.claim_id).version == 1
    assert other.get_current(claim.claim_id).version == 2
    assert memory.reference(claim.claim_id).run_id != other.reference(claim.claim_id).run_id
    only_here = revision(claim, claim_id="only-in-run-a")
    memory.append(only_here)
    with pytest.raises(KeyError):
        other.get_history(only_here.claim_id)


def test_automatic_run_ids_are_stable_and_distinct():
    first, second = SharedMemory(), SharedMemory()
    assert first.run_id and first.run_id != second.run_id
    original = first.run_id
    assert first.run_id == original
    with pytest.raises(AttributeError):
        first.run_id = "changed"


@pytest.mark.parametrize("run_id", ["", "   ", " run-a", "run-a "])
def test_invalid_run_identity_is_rejected(run_id):
    with pytest.raises(ValueError):
        SharedMemory(run_id)


def test_input_mutation_cannot_change_history(memory, source_and_claim):
    claim = source_and_claim[1]
    original = claim.model_dump_json(round_trip=True)
    memory.append(claim)
    # Pydantic's normal frozen checks work, but store isolation must also survive
    # a caller deliberately bypassing them through a mutable __dict__.
    with pytest.raises(ValidationError):
        claim.value = Decimal("0")
    claim.evidence[0].__dict__["page"] = 999
    claim.period.__dict__["label"] = "mutated"
    claim.__dict__["value"] = Decimal("0")
    assert memory.get_current(claim.claim_id).model_dump_json(round_trip=True) == original


def test_all_read_paths_return_detached_records(memory, source_and_claim):
    claim = source_and_claim[1]
    returned = memory.append(claim)
    readers = [
        returned, memory.get_claim(claim.claim_id), memory.get_current(claim.claim_id),
        memory.get_history(claim.claim_id)[0], memory.get_claims()[0],
        memory.resolve(memory.reference(claim.claim_id)),
    ]
    for record in readers:
        record.evidence[0].__dict__["locator"] = "mutated"
        record.__dict__["verification_status"] = "verified"
    history = memory.get_history(claim.claim_id)
    history.clear()
    assert memory.get_current(claim.claim_id) == claim
    assert memory.get_history(claim.claim_id) == [claim]


def test_source_metadata_is_detached_and_cannot_be_overwritten(source_and_claim):
    source, _ = source_and_claim
    store = SharedMemory("sources")
    original = source.model_dump_json(round_trip=True)
    accepted = store.register_source(source)
    source.currency_evidence.__dict__["quote"] = "input mutation"
    accepted.currency_evidence.__dict__["quote"] = "output mutation"
    store.get_source(source.source_id).__dict__["title"] = "read mutation"
    assert store.get_source(source.source_id).model_dump_json(round_trip=True) == original
    with pytest.raises(ValueError, match="already registered"):
        store.register_source(accepted)
    assert store.get_source(source.source_id).model_dump_json(round_trip=True) == original


@pytest.mark.parametrize("changes", [
    {"version": 0}, {"claim_id": "   "}, {"support_level": "verified"},
    {"verification_status": "single_source"}, {"evidence": ()},
    {"value": "not a number"},
])
def test_invalid_model_copy_is_revalidated_at_boundary(memory, source_and_claim, changes):
    # model_copy does not validate updates, so append must not trust the instance.
    forged = source_and_claim[1].model_copy(update=changes)
    with pytest.raises(ValueError):
        memory.append(forged)
    assert memory.get_claims() == []


def test_nested_forged_evidence_is_revalidated(memory, source_and_claim):
    claim = source_and_claim[1]
    forged = claim.model_copy(update={"evidence": (claim.evidence[0].model_copy(update={"page": 0}),)})
    with pytest.raises(ValidationError):
        memory.append(forged)
    assert memory.get_claims() == []


def test_unknown_and_inconsistent_source_references_are_rejected(memory, source_and_claim):
    source, claim = source_and_claim
    empty = SharedMemory("empty")
    with pytest.raises(ValueError, match="Unregistered"):
        empty.append(claim)
    bad_data = claim.evidence[0].model_dump(round_trip=True)
    bad_data["source_url"] = "https://example.org/other.pdf"
    bad_evidence = Evidence.model_validate(bad_data)
    with pytest.raises(ValueError, match="identity"):
        memory.append(claim.model_copy(update={"evidence": (bad_evidence,)}))
    assert empty.get_claims() == memory.get_claims() == []
    forged_basis = source.currency_evidence.model_copy(update={"source_id": "sha256:" + "0" * 64})
    with pytest.raises(ValidationError):
        empty.register_source(source.model_copy(update={"currency_evidence": forged_basis}))


def interpretation(claim):
    return Claim(
        claim_id="source-context", agent="DocumentAgent", claim_type="qualitative",
        claim="Source-linked context used only to test reference storage",
        supports_claim_ids=(claim.claim_id,), support_level="single_source", timestamp=claim.timestamp,
    )


def test_support_references_are_exact_and_do_not_silently_follow_latest(memory, source_and_claim):
    checked = revision(source_and_claim[1], verification_status="verified")
    memory.append(checked)
    context = interpretation(checked)
    memory.append(context)
    pinned = memory.get_support_references(context.claim_id)
    assert pinned == (memory.reference(checked.claim_id, 1),)
    memory.append(revision(checked, version=2, verification_status="pending"))
    assert memory.resolve(pinned[0]) == checked
    assert memory.get_support_references(context.claim_id) == pinned
    with pytest.raises(ValueError, match="not currently verified"):
        memory.append(revision(context, version=2))
    assert memory.get_history(context.claim_id) == [context]
    pinned[0].__dict__["version"] = 999
    assert memory.get_support_references(context.claim_id)[0].version == 1


@pytest.mark.parametrize("kind", ["missing", "pending", "self", "duplicate", "calculation"])
def test_invalid_support_and_calculation_references_are_rejected(memory, source_and_claim, kind):
    claim = source_and_claim[1]
    memory.append(claim)
    context = interpretation(claim)
    changes = {
        "missing": {"supports_claim_ids": ("missing",)},
        "pending": {},
        "self": {"supports_claim_ids": (context.claim_id,)},
        "duplicate": {"supports_claim_ids": (claim.claim_id, claim.claim_id)},
        "calculation": {"calculation_ref": "missing-calculation"},
    }
    with pytest.raises(ValueError):
        memory.append(revision(context, **changes[kind]))
    assert memory.get_claims() == [claim]


def test_unknown_and_invalid_lookups(memory, source_and_claim):
    claim = source_and_claim[1]
    memory.append(claim)
    for lookup in (lambda: memory.get_claim("missing"), lambda: memory.get_history("missing"),
                   lambda: memory.get_claim(claim.claim_id, 2)):
        with pytest.raises(KeyError):
            lookup()
    for version in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            memory.get_claim(claim.claim_id, version)
    with pytest.raises(ValidationError):
        ClaimVersionRef(run_id=memory.run_id, claim_id=claim.claim_id, version=0)
    with pytest.raises(ValueError):
        memory.get_claims(support_level="verified")
    with pytest.raises(TypeError):
        memory.append({"claim_id": "not-a-Claim"})


def test_listing_order_and_agent_filter(memory, source_and_claim):
    first = source_and_claim[1]
    second = revision(first, claim_id="second-claim", agent="MarketAgent")
    memory.append(first)
    memory.append(second)
    latest = revision(first, version=2)
    memory.append(latest)
    assert memory.get_claims() == [latest, second]
    assert memory.get_claims(agent="DocumentAgent") == [latest]


@pytest.mark.parametrize("value", [Decimal("1.25"), "1.25"])
def test_snapshot_preserves_numeric_and_text_value_types(memory, source_and_claim, value):
    # A storage-only fixture: do not conflate a Decimal with literal source text.
    sample = revision(source_and_claim[1], claim_id="value-type-fixture", value=value,
                      unit="count", currency=None, scale=1)
    memory.append(sample)
    restored = memory.get_current(sample.claim_id)
    assert restored == sample
    assert type(restored.value) is type(value)
