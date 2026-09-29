import pytest

from aomqtt.control_plane.messages import (
    ACK_ACCEPTED,
    ACK_REJECTED,
    STATUS_APPLIED,
    STATUS_FAILED,
    build_policy_ack,
    build_policy_status,
    from_json_bytes,
    to_json_bytes,
)


def test_build_policy_ack_accepted():
    msg = build_policy_ack(
        client_id="c_sub_001",
        role="subscriber",
        policy_id="p1",
        sequence_no=12,
        status=ACK_ACCEPTED,
        received_at=100.0,
        will_apply_at=110.0,
    )

    assert msg["client_id"] == "c_sub_001"
    assert msg["role"] == "subscriber"
    assert msg["policy_id"] == "p1"
    assert msg["sequence_no"] == 12
    assert msg["status"] == "accepted"
    assert msg["received_at"] == 100.0
    assert msg["will_apply_at"] == 110.0


def test_build_policy_ack_rejected():
    msg = build_policy_ack(
        client_id="c_sub_001",
        role="subscriber",
        policy_id="p1",
        sequence_no=12,
        status=ACK_REJECTED,
        received_at=100.0,
        reason="invalid padding size",
    )

    assert msg["status"] == "rejected"
    assert msg["reason"] == "invalid padding size"
    assert "will_apply_at" not in msg


def test_build_policy_status_applied():
    msg = build_policy_status(
        client_id="c_sub_001",
        role="subscriber",
        policy_id="p1",
        sequence_no=12,
        status=STATUS_APPLIED,
        event_time=120.0,
    )

    assert msg["status"] == "applied"
    assert msg["applied_at"] == 120.0


def test_build_policy_status_failed():
    msg = build_policy_status(
        client_id="c_sub_001",
        role="subscriber",
        policy_id="p1",
        sequence_no=12,
        status=STATUS_FAILED,
        event_time=120.0,
        reason="apply error",
    )

    assert msg["status"] == "failed"
    assert msg["failed_at"] == 120.0
    assert msg["reason"] == "apply error"


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        build_policy_ack(
            client_id="c1",
            role="subscriber",
            policy_id="p1",
            sequence_no=1,
            status="applied",
        )


def test_json_roundtrip():
    msg = build_policy_ack(
        client_id="c1",
        role="publisher",
        policy_id="p1",
        sequence_no=1,
        status=ACK_ACCEPTED,
        received_at=1.0,
    )

    encoded = to_json_bytes(msg)
    decoded = from_json_bytes(encoded)

    assert decoded == msg


def test_build_policy_ack_rejected_with_reason_code():
    msg = build_policy_ack(
        client_id="c1",
        role="subscriber",
        policy_id="p1",
        sequence_no=12,
        status="rejected",
        received_at=100.0,
        reason="control policy has expired",
        reason_code="expired_policy",
    )

    assert msg["status"] == "rejected"
    assert msg["reason"] == "control policy has expired"
    assert msg["reason_code"] == "expired_policy"
