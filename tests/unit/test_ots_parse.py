"""AC-11: a completed proof from the official OpenTimestamps client repository
(examples/hello-world.txt.ots) yields its Bitcoin block height."""

import hashlib
from pathlib import Path

import pytest

from provenance_core.ots import OtsError, parse_ots
from provenance_core.proofs import verify_btc_proof

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "ots"


def test_hello_world_block_height():
    proof = parse_ots((FIX / "hello-world.txt.ots").read_bytes())
    assert proof.file_hash_op == "sha256"
    assert proof.file_digest == hashlib.sha256((FIX / "hello-world.txt").read_bytes()).digest()
    assert [a.height for a in proof.bitcoin] == [358391]
    assert proof.pending == []


def test_incomplete_proof_is_pending():
    proof = parse_ots((FIX / "incomplete.txt.ots").read_bytes())
    assert proof.bitcoin == [] and len(proof.pending) == 1
    digest = hashlib.sha256((FIX / "incomplete.txt").read_bytes()).hexdigest()
    check = verify_btc_proof(digest, (FIX / "incomplete.txt.ots").read_bytes())
    assert check.state == "pending" and check.code == "BTC_PENDING"


def test_matches_official_library():
    pytest.importorskip("opentimestamps")
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    from opentimestamps.core.serialize import BytesDeserializationContext
    from opentimestamps.core.timestamp import DetachedTimestampFile

    for name in ("hello-world.txt.ots", "two-calendars.txt.ots", "merkle1.txt.ots", "empty.ots"):
        data = (FIX / name).read_bytes()
        ours = parse_ots(data)
        theirs = DetachedTimestampFile.deserialize(BytesDeserializationContext(data))
        btc = sorted(
            (a.height, m)
            for m, a in theirs.timestamp.all_attestations()
            if isinstance(a, BitcoinBlockHeaderAttestation)
        )
        assert sorted((a.height, a.msg) for a in ours.bitcoin) == btc


def test_wrong_start_digest_and_garbage():
    data = (FIX / "hello-world.txt.ots").read_bytes()
    assert verify_btc_proof("00" * 32, data).code == "BTC_INVALID"
    assert verify_btc_proof("00" * 32, b"not an ots file").code == "BTC_INVALID"
    with pytest.raises(OtsError):
        parse_ots(data[:-3])


def test_bitcoin_attestation_checked_against_header_lookup():
    data = (FIX / "hello-world.txt.ots").read_bytes()
    digest = hashlib.sha256((FIX / "hello-world.txt").read_bytes()).hexdigest()
    att = parse_ots(data).bitcoin[0]
    unchecked = verify_btc_proof(digest, data)
    assert unchecked.state == "unchecked" and not unchecked.verified
    good = verify_btc_proof(digest, data, header_lookup=lambda h: (att.merkle_root_hex, 1432827678))
    assert good.verified and good.time == "2015-05-28T15:41:18Z"
    bad = verify_btc_proof(digest, data, header_lookup=lambda h: ("00" * 32, 1432827678))
    assert bad.code == "BTC_INVALID"
