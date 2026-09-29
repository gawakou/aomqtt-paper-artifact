# AOMQTT v0.5 Evaluation Framework

v0.5 turns AOMQTT from a working SDK into an evaluation-ready research
prototype. The goal is to measure the trade-off among topic-name confidentiality,
MQTT compatibility, delivery reliability, duplicate delivery, and operational
latency.

## Evaluation modes

| Mode | Topic visibility | Payload | Broker modification | Purpose |
|---|---|---|---|---|
| `plain` | plaintext | plaintext | no | minimum baseline |
| `tls` | plaintext to broker | plaintext to broker | no | transport-security baseline when TLS broker is available |
| `payload_only` | plaintext | AES-GCM | no | application payload encryption baseline |
| `aomqtt_whole` | HMAC whole-topic token | AES-GCM | no | stronger structure hiding |
| `aomqtt_hierarchical` | HMAC per-level tokens | AES-GCM | no | MQTT hierarchy and wildcard compatibility |
| `aomqtt_whole_rotation` | rotating whole-topic token | AES-GCM | no | long-term linkability reduction |
| `aomqtt_hierarchical_rotation` | rotating per-level tokens | AES-GCM | no | hierarchy plus rotation |

## Metrics

### Publisher-side CSV

`publisher_metrics.csv` records one row per MQTT PUBLISH packet. During a
rotation overlap window, one logical application message may create two rows.

Important columns:

- `logical_seq`
- `plaintext_topic`
- `token_topic`
- `token_mode`
- `rotation_enabled`
- `rotation_epoch`
- `rotation_in_overlap`
- `overlap_duplicate`
- `payload_plain_bytes`
- `payload_encrypted_bytes`
- `success`
- `publish_complete_ms`
- `reconnect_count`

### Subscriber-side CSV

`subscriber_metrics.csv` records one row per received MQTT message.

Important columns:

- `message_id`
- `logical_seq`
- `token_topic`
- `decrypt_success`
- `duplicate`
- `publisher_timestamp`
- `delivery_latency_ms`
- `payload_bytes`

The subscriber extracts `message_id`, `seq`, and `sent_time` from decrypted JSON
payloads. The provided evaluation runner automatically inserts these fields.

## Run

Start Mosquitto first:

```bash
sudo docker-compose up -d
# or
# docker compose up -d
```

Run the default evaluation:

```bash
python experiments/run_evaluation.py \
  --broker localhost \
  --count 100 \
  --interval 0.1 \
  --qos 1 \
  --output results/eval_v05
```

Run selected modes:

```bash
python experiments/run_evaluation.py \
  --broker localhost \
  --count 1000 \
  --interval 0.05 \
  --qos 1 \
  --modes plain,payload_only,aomqtt_whole,aomqtt_hierarchical,aomqtt_whole_rotation,aomqtt_hierarchical_rotation \
  --output results/eval_$(date +%Y%m%d_%H%M%S)
```

Summarize:

```bash
python experiments/summarize_evaluation.py results/eval_v05
```

## Threat-model note

AOMQTT v0.5 evaluates direct topic-name exposure and operational cost. It does
not claim resistance against traffic analysis. Deterministic tokens remain
linkable within an epoch, and hierarchical mode leaks the number of levels and
parent-child relationships. This limitation should be stated explicitly in
papers and presentations.
