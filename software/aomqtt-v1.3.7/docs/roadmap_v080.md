# Roadmap Note: v0.8.0

v0.8.0 introduces MQTT control-topic based policy distribution.

## Implemented in v0.8.0

- `aomqtt.control` module
  - `ControlPolicyMessage`
  - `ControlTopicPolicyReceiver`
  - `PolicyMessagePublisher`
  - `build_control_policy_message()`
  - `parse_control_policy_message()`
  - `control_policy_topic()`
- `examples/policy_controller_publish.py`
- `examples/publisher_example.py --enable-control-topic`
- `examples/subscriber_example.py --enable-control-topic`
- `valid_from` based synchronized policy application
- Runtime `policy_id` / `policy_name` propagation through existing metrics

## Deferred to v0.8.1

- Policy ACK
- Controller-side application-state collection
- Policy rollback preparation

## Deferred to v0.8.2

- Metrics aggregation
- Threshold-based policy selection
- Observation-driven policy control
