# AOMQTT v0.4 Transport Adapter and Client-side Observation

## 1. Purpose

AOMQTT v0.4 separates the privacy layer from the underlying MQTT client
implementation. Topic tokenization, payload encryption, and token rotation are
implemented in `aomqtt.core`, while actual MQTT network operations are delegated
to `aomqtt.transport`.

This means the prototype currently uses Eclipse Paho through
`PahoMQTTAdapter`, but the AOMQTT Core is no longer designed as a Paho-specific
wrapper.

## 2. Architecture

```text
Application
   |
   v
AOMQTT Client API
   |
   +-- aomqtt.core
   |     - TopicTokenizer
   |     - PayloadCrypto
   |     - TokenRotation
   |
   +-- aomqtt.observation
   |     - PublishMetric
   |     - PublishCSVLogger
   |
   v
TransportAdapter interface
   |
   v
PahoMQTTAdapter
   |
   v
MQTT Broker
```

## 3. Publish observation

`publish_observed_rotating()` records one CSV row for each actual MQTT PUBLISH.
During a rotation overlap window, one logical application message may generate
two MQTT PUBLISH packets, and therefore two rows.

Important columns:

- `plaintext_topic`: logical topic before tokenization
- `token_topic`: topic visible to the MQTT broker
- `rotation_epoch`: epoch used for token generation
- `rotation_in_overlap`: true when the message is sent during overlap
- `overlap_duplicate`: true for the duplicate publish to the previous epoch
- `payload_plain_bytes`: serialized payload size before encryption
- `payload_encrypted_bytes`: encrypted envelope size
- `publish_complete_ms`: publish completion time
- `success`: publish result
- `reconnect_count`: number of reconnects observed by the transport adapter

For QoS 1/2, `publish_complete_ms` approximates broker acknowledgement latency.
For QoS 0, it is only the client-side publish completion time.

## 4. Example

```bash
python examples/publisher_example.py \
  --broker localhost \
  --topic shelter/siteA/starlink/rtt \
  --count 20 \
  --interval 1 \
  --qos 1 \
  --token-mode whole \
  --rotation \
  --rotation-interval 30 \
  --rotation-overlap 5 \
  --metrics-csv results/publish_metrics.csv
```

Summarize the CSV:

```bash
python examples/analyze_publish_metrics.py results/publish_metrics.csv
```
