from aomqtt.policy_trace import extract_policy_trace_fields


def test_extract_policy_trace_fields_from_nested_policy():
    raw = b'''
    {
      "sequence_no": 42,
      "key_id": "policy-signing-key-1",
      "controller_id": "controller-A",
      "policy": {
        "id": "policy-dangerous-padding-001"
      }
    }
    '''

    trace = extract_policy_trace_fields(raw)

    assert trace.policy_id == "policy-dangerous-padding-001"
    assert trace.sequence_no == 42
    assert trace.key_id == "policy-signing-key-1"
    assert trace.controller_id == "controller-A"


def test_extract_policy_trace_fields_from_top_level_fields():
    raw = {
        "policy_id": "policy-top-level-001",
        "sequence_no": "7",
        "key_id": "key-A",
    }

    trace = extract_policy_trace_fields(raw)

    assert trace.policy_id == "policy-top-level-001"
    assert trace.sequence_no == 7
    assert trace.key_id == "key-A"


def test_extract_policy_trace_fields_returns_unknown_for_malformed_json():
    trace = extract_policy_trace_fields(b'{"policy":')

    assert trace.policy_id == "unknown"
    assert trace.sequence_no == 0
    assert trace.key_id == "unknown"


def test_extract_policy_trace_fields_returns_unknown_for_non_object_json():
    trace = extract_policy_trace_fields(b'["not", "a", "policy"]')

    assert trace.policy_id == "unknown"
    assert trace.sequence_no == 0
    assert trace.key_id == "unknown"
