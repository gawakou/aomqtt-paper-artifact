# AOMQTT v0.8.0: MQTT Control Topic Policy Distribution

v0.8.0 extends the v0.7 external policy model from static YAML loading to
runtime policy distribution over MQTT control topics.

## Scope

v0.8.0 implements:

- Policy Controller publishes a policy message to an MQTT control topic.
- Publisher and Subscriber can subscribe to that control topic.
- Received policies are scheduled by `valid_from` and applied at the same time.
- `policy_id` and `policy_name` continue to be recorded in metrics CSV.

v0.8.0 does **not** implement policy ACK, rollback, or automatic selection.
Those are reserved for v0.8.1 and v0.8.2.

## Topics

Default policy topic:

```text
aomqtt/control/<group_id>/policy
```

Example:

```text
aomqtt/control/shelter-siteA/policy
```

## Control message

The controller publishes JSON:

```json
{
  "schema_version": "aomqtt-policy-v1",
  "group_id": "shelter-siteA",
  "issued_at": 1780360000.0,
  "valid_from": 1780360010.0,
  "grace_period_sec": 5.0,
  "policy": {
    "id": "p_whole_bucket_rotation",
    "name": "whole_bucket_rotation",
    "token_mode": "whole",
    "qos": 1,
    "retain": false,
    "rotation": {
      "enabled": true,
      "interval_sec": 30,
      "overlap_sec": 5
    },
    "padding": {
      "enabled": true,
      "mode": "bucket",
      "bucket_size": 256
    }
  }
}
```

## Publisher/Subscriber usage

Subscriber:

```bash
python examples/subscriber_example.py \
  --broker localhost \
  --config examples/config.example.yaml \
  --policy examples/policy.example.yaml \
  --enable-control-topic \
  --control-group-id shelter-siteA \
  --topic shelter/siteA/starlink/rtt \
  --delivery-csv results/subscriber_metrics.csv
```

Publisher:

```bash
python examples/publisher_example.py \
  --broker localhost \
  --config examples/config.example.yaml \
  --policy examples/policy.example.yaml \
  --enable-control-topic \
  --control-group-id shelter-siteA \
  --topic shelter/siteA/starlink/rtt \
  --count 60 \
  --interval 1 \
  --metrics-csv results/publisher_metrics.csv
```

Controller:

```bash
python examples/policy_controller_publish.py \
  --broker localhost \
  --group-id shelter-siteA \
  --policy examples/policy.example.yaml \
  --valid-after 10
```

## Design note

The control-plane client is intentionally separated from the data-plane MQTT
client.  This keeps the implementation minimally invasive and preserves the
v0.4 transport-adapter separation.  The receiver applies policy changes by
updating the effective `AOMQTTConfig` and rebuilding tokenizer, crypto, and
rotation components.

For Subscribers, policy updates also trigger subscription refresh.  Existing
subscriptions are kept during transition so that old/new policy windows can
coexist.  v0.8.1 will add ACK and explicit application-state reporting.
