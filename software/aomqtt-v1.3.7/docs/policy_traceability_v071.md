# AOMQTT v0.7.1 Policy Traceability

v0.7.1 is a small compatibility and evaluation release between v0.7 and v0.8.
It improves policy traceability and makes rotation experiments easier to reproduce.

## Changes

### 1. policy_id / policy_name

Each external policy may now define both `id` and `name`.

```yaml
policy:
  id: p_whole_bucket_rotation
  name: whole_bucket_rotation
```

When a policy is applied, the effective `AOMQTTConfig` stores:

- `policy_id`
- `policy_name`

Publisher and Subscriber metrics CSVs also include these two columns. This is important for v0.8, where a single long-running experiment may contain multiple policies.

### 2. Masked effective policy display

`examples/show_effective_policy.py` masks `topic_key` and `payload_key` by default.
Use `--show-keys` only for local debugging.

```bash
python examples/show_effective_policy.py \
  --config examples/config.example.yaml \
  --policy examples/policy.example.yaml
```

### 3. Rotation override in policy evaluation

`experiments/run_policy_evaluation.py` accepts experiment-level rotation overrides:

```bash
python experiments/run_policy_evaluation.py \
  --broker localhost \
  --rotation-interval 10 \
  --rotation-overlap 3 \
  --output results/eval_v071_policy
```

These overrides do not modify the YAML files. They only affect the effective configuration used in that evaluation run.

## Scope

v0.7.1 is still operator-driven and file-based. MQTT control-topic policy delivery is planned for v0.8.0.
