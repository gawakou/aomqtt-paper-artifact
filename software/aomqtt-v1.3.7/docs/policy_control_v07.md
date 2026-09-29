# AOMQTT v0.7 Policy Controller

v0.7 introduces an external policy layer for switching runtime/privacy
parameters without editing the base key configuration.

## Design goal

The base `AOMQTTConfig` continues to hold shared secrets and protocol defaults:

- `topic_key`
- `payload_key`
- `topic_prefix`
- key and payload encoding parameters

The external policy controls only operational choices:

- `token_mode`: `whole` or `hierarchical`
- `qos`: MQTT QoS 0/1/2
- `retain`
- `rotation.enabled`
- `rotation.interval_sec`
- `rotation.overlap_sec`
- `padding.enabled`
- `padding.mode`: `none`, `fixed`, `bucket`, `random`
- padding sizes and random padding range

This separation allows operators to evaluate privacy/overhead policies without
moving or duplicating cryptographic keys.

## Single policy file

```yaml
policy:
  name: whole_bucket_rotation
  token_mode: whole
  qos: 1
  retain: false
  rotation:
    enabled: true
    interval_sec: 30
    overlap_sec: 5
  padding:
    enabled: true
    mode: bucket
    bucket_size: 256
```

Apply the policy to both publisher and subscriber:

```bash
python examples/subscriber_example.py \
  --broker localhost \
  --config examples/config.example.yaml \
  --policy examples/policy.example.yaml \
  --topic shelter/siteA/starlink/rtt \
  --delivery-csv results/subscriber_metrics.csv
```

```bash
python examples/publisher_example.py \
  --broker localhost \
  --config examples/config.example.yaml \
  --policy examples/policy.example.yaml \
  --topic shelter/siteA/starlink/rtt \
  --count 20 \
  --interval 1 \
  --metrics-csv results/publisher_metrics.csv
```

## Policy precedence

The precedence is:

```text
base config < external policy < explicit CLI overrides
```

For example, if a policy enables rotation but the publisher is started with
`--no-rotation`, the CLI override wins.

## Policy matrix

`PolicyController.load_policies()` also supports a matrix file:

```yaml
policies:
  - name: whole_no_padding
    token_mode: whole
    qos: 1
    rotation:
      enabled: false
    padding:
      enabled: false
      mode: none

  - name: hierarchical_bucket_rotation
    token_mode: hierarchical
    qos: 1
    rotation:
      enabled: true
      interval_sec: 30
      overlap_sec: 5
    padding:
      enabled: true
      mode: bucket
      bucket_size: 256
```

Run all policies:

```bash
python experiments/run_policy_evaluation.py \
  --broker localhost \
  --config examples/config.example.yaml \
  --policies examples/policies.matrix.yaml \
  --count 100 \
  --interval 0.1 \
  --output results/eval_v07_policy
```

The output uses the same CSV and summary format as v0.6:

```text
results/eval_v07_policy/
  whole_no_padding/
    publisher_metrics.csv
    subscriber_metrics.csv
    summary.json
  hierarchical_bucket_rotation/
    publisher_metrics.csv
    subscriber_metrics.csv
    summary.json
  comparison_summary.csv
```

## Research positioning

v0.7 is still operator-driven. It does not automatically choose policies from
observed metrics. That automatic feedback loop is intentionally reserved for
v0.8.

The v0.7 contribution is deployment-oriented: it shows that privacy, MQTT
compatibility, and overhead policies can be changed externally while preserving
an unmodified broker and a single client SDK implementation.
