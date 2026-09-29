# AOMQTT v0.6 Evaluation Guide

v0.6 extends v0.5 evaluation by adding payload padding overhead measurement.

## Basic command

```bash
python experiments/run_evaluation.py \
  --broker localhost \
  --count 100 \
  --interval 0.1 \
  --qos 1 \
  --padding-modes none,bucket,fixed,random \
  --output results/eval_v06
```

## Practical shorter command

```bash
python experiments/run_evaluation.py \
  --broker localhost \
  --count 100 \
  --interval 0.1 \
  --qos 1 \
  --modes payload_only,aomqtt_whole,aomqtt_hierarchical,aomqtt_whole_rotation \
  --padding-modes none,bucket \
  --padding-bucket-size 256 \
  --output results/eval_v06_bucket
```

## Output files

Each mode directory contains:

- `publisher_metrics.csv`
- `subscriber_metrics.csv`
- `summary.json`

The top-level directory contains:

- `comparison_summary.csv`

## Key columns in comparison_summary.csv

| Column | Meaning |
|---|---|
| `avg_payload_plain_bytes` | original serialized payload size |
| `avg_payload_padded_bytes` | AEAD plaintext size after padding |
| `avg_payload_encrypted_bytes` | final MQTT payload size |
| `avg_padding_added_bytes` | padding overhead inside AEAD plaintext |
| `avg_payload_total_overhead_bytes` | final payload overhead relative to original plaintext |
| `avg_publish_complete_ms` | publisher-side completion latency |
| `avg_delivery_latency_ms` | subscriber-side delivery latency |
| `loss_rate` | application-level loss rate based on message IDs |
| `duplicate_rate_per_unique_received` | duplicate delivery ratio by unique received IDs |

## Interpretation

- `bucket` padding is expected to provide a practical trade-off for research
  evaluation.
- `fixed` padding may create larger overhead, especially for small payloads.
- `random` padding introduces variability but should not be described as a full
  traffic-analysis defense.
- Padding protects payload size less strongly than topic tokenization protects
  direct topic-name exposure; it is a partial metadata mitigation.
