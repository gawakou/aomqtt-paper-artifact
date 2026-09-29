from aomqtt.control_plane.tracker import PolicyDeploymentTracker


def test_tracker_initial_pending():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
        expected_clients=["c_pub_001", "c_sub_001"],
        started_at=100.0,
    )

    rows = tracker.rows()
    assert len(rows) == 2
    assert rows[0]["ack_status"] == "pending"


def test_tracker_handle_ack_and_status():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
        expected_clients=["c_sub_001"],
        started_at=100.0,
    )

    tracker.handle_ack(
        {
            "client_id": "c_sub_001",
            "role": "subscriber",
            "policy_id": "p1",
            "sequence_no": 1,
            "status": "accepted",
            "received_at": 101.0,
            "will_apply_at": 110.0,
        }
    )

    tracker.handle_status(
        {
            "client_id": "c_sub_001",
            "role": "subscriber",
            "policy_id": "p1",
            "sequence_no": 1,
            "status": "applied",
            "applied_at": 110.1,
        }
    )

    row = tracker.rows()[0]
    assert row["ack_status"] == "accepted"
    assert row["apply_status"] == "applied"
    assert row["applied_at"] == 110.1
    assert tracker.is_complete()


def test_tracker_ack_timeout():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
        expected_clients=["c_sub_001"],
        ack_timeout_sec=5.0,
        started_at=100.0,
    )

    tracker.update_timeouts(now=106.0)

    row = tracker.rows()[0]
    assert row["ack_status"] == "timeout"
    assert row["apply_status"] == "-"
    assert row["reason"] == "no ACK"


def test_tracker_apply_timeout():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
        expected_clients=["c_sub_001"],
        apply_timeout_sec=10.0,
        started_at=100.0,
    )

    tracker.handle_ack(
        {
            "client_id": "c_sub_001",
            "role": "subscriber",
            "policy_id": "p1",
            "sequence_no": 1,
            "status": "accepted",
            "received_at": 101.0,
            "will_apply_at": 110.0,
        }
    )

    tracker.update_timeouts(now=121.0)

    row = tracker.rows()[0]
    assert row["ack_status"] == "accepted"
    assert row["apply_status"] == "timeout"
    assert row["reason"] == "no applied/failed status"


def test_tracker_preserves_rejected_reason_code():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
    )

    tracker.handle_ack(
        {
            "client_id": "c_sub_001",
            "role": "subscriber",
            "policy_id": "p1",
            "sequence_no": 1,
            "status": "rejected",
            "received_at": 100.0,
            "reason": "control policy has expired",
            "reason_code": "expired_policy",
        }
    )

    row = tracker.rows()[0]

    assert row["ack_status"] == "rejected"
    assert row["apply_status"] == "-"
    assert row["reason"] == "control policy has expired"
    assert row["reason_code"] == "expired_policy"
    assert "expired_policy" in tracker.summary_text()


def test_tracker_timeout_sets_reason_code():
    tracker = PolicyDeploymentTracker(
        policy_id="p1",
        sequence_no=1,
        expected_clients=["c_missing_001"],
        ack_timeout_sec=5.0,
        started_at=100.0,
    )

    tracker.update_timeouts(now=106.0)

    row = tracker.rows()[0]

    assert row["ack_status"] == "timeout"
    assert row["apply_status"] == "-"
    assert row["reason"] == "no ACK"
    assert row["reason_code"] == "timeout"
    assert "timeout" in tracker.summary_text()
