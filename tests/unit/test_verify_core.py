"""AC-07 and the core verifier (V1–V9) on an in-memory log."""

from dataclasses import replace

from cryptography import x509

from provenance_core import records as R
from provenance_core.proofs import verify_btc_proof
from provenance_core.providers.mock import MockProvider
from provenance_core.replay import milestone_view, replay
from provenance_core.signing import public_key_from_hex, verify_record_signature
from provenance_core.verify import STATUS_FAIL, STATUS_PASS, STATUS_PASS_BTC_PENDING, STATUS_WARNING
from tests.helpers import MemoryLog

FREETSA_ROOT = x509.load_pem_x509_certificate(
    open("core/provenance_core/certs/freetsa-cacert.pem", "rb").read()
)


def _log():
    log = MemoryLog()
    a = log.entry("first formula", "idea", body="E = mc^2\n")
    b = log.entry("experiment 1", "experiment", body="ran it\r\n", relations=[{"to": a.id, "rel": "uses"}])
    log.append("link", R.link_payload(b.id, a.id, "derived_from", statement="noticed later"))
    log.append("statement", R.statement_payload(b.id, "parameters from the literature"))
    return log, a, b


def test_every_signature_verifies_with_genesis_key():  # AC-07
    log, _, _ = _log()
    pub = public_key_from_hex(log.records[0].payload["public_key"])
    for r in log.records:
        assert verify_record_signature(pub, r.id, r.signature)
    report = log.verify()
    assert report.ok, report.failure_codes()


def test_one_flipped_signature_byte_is_signature_invalid():  # AC-07
    log, _, b = _log()
    mats = log.materials()
    sig = bytearray(mats[b.id].signature)
    sig[5] ^= 0x01
    mats[b.id] = replace(mats[b.id], signature=bytes(sig))
    report = log.verify(mats)
    assert not report.ok
    assert report.by_id()[b.id].failure_codes == ["SIGNATURE_INVALID"]
    assert report.by_id()[b.id].status == STATUS_FAIL


def test_untampered_log_passes_with_btc_pending():
    log, _, _ = _log()
    report = log.verify()
    assert report.ok
    assert all(r.status == STATUS_PASS_BTC_PENDING for r in report.records)
    for r in report.records:
        assert r.tsa.verified and r.btc.state == "pending"
        time, label = r.earliest_verified()
        assert label == "Third-party timestamp" and time == r.tsa.time


def test_disclosure_levels_still_verify():
    log, _, _ = _log()
    for level in ("full", "structure", "existence"):
        report = log.verify(log.materials(level))
        assert report.ok, (level, report.failure_codes())


def test_content_payload_manifest_tampering():
    log, a, _ = _log()
    mats = log.materials()
    mats[a.id] = replace(mats[a.id], content={"body": b"E = mc^3\n"})
    assert "CONTENT_MISMATCH" in log.verify(mats).failure_codes()

    mats = log.materials()
    mats[a.id] = replace(mats[a.id], payload_bytes=mats[a.id].payload_bytes.replace(b"first", b"FIRST"))
    assert "PAYLOAD_HASH_MISMATCH" in log.verify(mats).failure_codes()

    mats = log.materials()
    mats[a.id] = replace(mats[a.id], manifest_bytes=mats[a.id].manifest_bytes.replace(b'"seq":1', b'"seq":7'))
    assert "MANIFEST_HASH_MISMATCH" in log.verify(mats).failure_codes()

    mats = log.materials()
    mats[a.id] = replace(mats[a.id], manifest_bytes=mats[a.id].manifest_bytes.replace(b",", b", ", 1))
    codes = log.verify(mats).failure_codes()
    assert "NON_CANONICAL" in codes


def test_chain_gap_and_reorder():
    log, a, b = _log()
    ids = [r.id for r in log.records]
    mats = log.materials()
    mats[a.id] = replace(mats[a.id], manifest_bytes=None)
    assert "LOG_GAP" in log.verify(mats).failure_codes()

    from provenance_core.providers.mock import mock_tsa_root
    from provenance_core.verify import verify_log

    swapped = list(ids)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    report = verify_log(swapped, log.materials(), tsa_roots=[mock_tsa_root()])
    assert "LOG_PREV_MISMATCH" in report.failure_codes()


def test_reference_checks():
    log, a, _ = _log()
    log.append("statement", R.statement_payload("f" * 64, "points nowhere"))
    assert "REF_MISSING" in log.verify().failure_codes()


def test_tsa_untrusted_root_and_imprint():
    log, a, b = _log()
    report = log.verify(tsa_roots=[FREETSA_ROOT])
    assert report.by_id()[a.id].failure_codes == ["TSA_CHAIN_UNTRUSTED"]
    mats = log.materials()
    mats[a.id] = replace(mats[a.id], tsa_proof=mats[b.id].tsa_proof)
    assert log.verify(mats).by_id()[a.id].failure_codes == ["TSA_IMPRINT_MISMATCH"]
    broken = bytearray(mats[b.id].tsa_proof)
    broken[-20] ^= 0xFF
    mats[b.id] = replace(mats[b.id], tsa_proof=bytes(broken))
    assert log.verify(mats).by_id()[b.id].failure_codes == ["TSA_INVALID"]


def test_no_timestamp_is_a_warning_not_a_time():
    log = MemoryLog(with_tsa=False, with_btc=False)
    log.entry("offline note")
    report = log.verify()
    assert report.ok
    r = report.records[-1]
    assert r.status == STATUS_WARNING and r.warning_codes == ["NO_VERIFIED_TIME"]
    assert r.earliest_verified() is None


def test_btc_mock_states():
    log = MemoryLog()
    rec = log.entry("x")
    btc = MockProvider("btc", clock=log.clock, confirm_on_upgrade=True)
    confirmed = btc.upgrade(rec.btc_proof).proof
    assert verify_btc_proof(rec.id, confirmed, allow_mock=True).verified
    assert verify_btc_proof(rec.id, confirmed, allow_mock=False).code == "BTC_INVALID"
    assert verify_btc_proof(log.records[0].id, confirmed, allow_mock=True).code == "BTC_INVALID"
    mats = log.materials()
    mats[rec.id] = replace(mats[rec.id], btc_proof=confirmed)
    r = log.verify(mats, allow_mock=True).by_id()[rec.id]
    assert r.status == STATUS_PASS


def test_time_skew_over_24h_is_a_warning():
    from datetime import timedelta

    log = MemoryLog()
    rec = log.entry("x")
    late = log.clock.now + timedelta(hours=30)
    confirmed = MockProvider("btc", clock=lambda: late, confirm_on_upgrade=True).upgrade(rec.btc_proof).proof
    mats = log.materials()
    mats[rec.id] = replace(mats[rec.id], btc_proof=confirmed)
    r = log.verify(mats, allow_mock=True).by_id()[rec.id]
    assert r.status == STATUS_WARNING and r.warning_codes == ["TIME_SKEW"]
    # The two times stay separate; the summary names which proof the earliest came from.
    assert r.tsa.time != r.btc.time
    assert r.earliest_verified() == (r.tsa.time, "Third-party timestamp")


def test_replay_applies_later_additions():
    log, a, b = _log()
    log.append("milestone", R.milestone_payload(a.id, "set"))
    log.append("link", R.link_payload(b.id, a.id, "uses", op="withdraw"))
    c = log.entry("experiment 2", "experiment", relations=[{"to": b.id, "rel": "revises"}], milestone=True)
    log.append("retraction", R.retraction_payload(b.id, "setup error"))
    state = replay([(r.id, r.seq, r.kind, r.payload) for r in log.records])
    assert state.entries[a.id].milestone is True
    uses = [e for e in state.edges if e.rel == "uses"]
    assert len(uses) == 1 and uses[0].withdrawn_by is not None
    later = [e for e in state.edges if e.origin == "link"]
    assert later and later[0].rel == "derived_from" and later[0].active
    assert state.entries[b.id].retracted_by is not None
    assert len(state.entries[b.id].statements) == 1
    milestones, connectors = milestone_view(state)
    assert milestones == [a.id, c.id]
    assert connectors == [(a.id, c.id, 1)]  # a -> b (derived_from) -> c, one record in between
