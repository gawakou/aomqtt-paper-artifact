# AOMQTT Roadmap after v0.7.1

## v0.7.1

- Add `policy_id` and `policy_name` to effective config and metrics CSV.
- Mask keys in `show_effective_policy.py` by default.
- Add rotation interval/overlap CLI overrides to policy evaluation.

## v0.8.0

- Add MQTT control-topic based policy delivery.
- Add `examples/policy_controller_publish.py`.
- Allow Publisher/Subscriber to subscribe to a control topic.
- Apply policies at `valid_from`.
- Keep `policy_id` in metrics for dynamic-policy experiments.

## v0.8.1

- Add Policy ACK from Publisher/Subscriber.
- Record policy acceptance and application state.
- Prepare rollback logic.

## v0.8.2

- Aggregate metrics.
- Add threshold-based policy selection.
- Implement observation-driven policy control.
