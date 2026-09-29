import pytest

from aomqtt.control_plane.topics import (
    control_ack_topic,
    control_all_topic,
    control_policy_topic,
    control_status_topic,
)


def test_control_topics():
    group_id = "shelter-siteA"

    assert control_policy_topic(group_id) == "aomqtt/control/shelter-siteA/policy"
    assert control_ack_topic(group_id) == "aomqtt/control/shelter-siteA/ack"
    assert control_status_topic(group_id) == "aomqtt/control/shelter-siteA/status"
    assert control_all_topic(group_id) == "aomqtt/control/shelter-siteA/#"


def test_group_id_must_not_be_empty():
    with pytest.raises(ValueError):
        control_policy_topic("")


def test_group_id_must_not_contain_wildcards():
    with pytest.raises(ValueError):
        control_ack_topic("site+")
    with pytest.raises(ValueError):
        control_status_topic("site#")
