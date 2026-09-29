# AOMQTT v0.6 Payload Padding

## Purpose

v0.6 introduces payload padding to reduce direct leakage of application payload
size. This is a metadata-leakage mitigation, not a complete traffic-analysis
defense.

A broker can still observe:

- publish timing;
- publish frequency;
- tokenized topic equality within an epoch;
- tokenized topic structure in hierarchical mode;
- final MQTT payload size after encryption and padding.

Padding only changes the relationship between the original application payload
size and the MQTT-visible encrypted payload size.

## Design

Padding is applied before AES-256-GCM encryption:

```text
application payload
  -> serialize according to payload_format
  -> optional padding wrapper
  -> AES-256-GCM encryption
  -> JSON ciphertext envelope
  -> MQTT PUBLISH payload
```

The original plaintext length is stored inside the encrypted padding wrapper.
It is not stored as a plaintext field in the outer JSON envelope.

## Modes

| Mode | Behavior |
|---|---|
| `none` | No padding. v0.5-compatible behavior. |
| `fixed` | Pad the AEAD plaintext to at least `padding_fixed_size` bytes. |
| `bucket` | Round the AEAD plaintext size up to multiples of `padding_bucket_size`. |
| `random` | Add a random number of padding bytes between configured min/max. |

## Metrics

Publisher-side CSV includes:

- `payload_plain_bytes`: serialized application payload size;
- `payload_padded_bytes`: bytes encrypted by AEAD after optional padding;
- `payload_encrypted_bytes`: final MQTT payload bytes;
- `padding_added_bytes`: padded plaintext bytes minus original plaintext bytes;
- `padding_overhead_ratio`: `padding_added_bytes / payload_plain_bytes`;
- `payload_total_overhead_bytes`: final MQTT payload bytes minus original plaintext bytes.

## Recommended evaluation

Compare at least these conditions:

```text
payload_only
payload_only_pad_bucket
aomqtt_whole
aomqtt_whole_pad_bucket
aomqtt_hierarchical
aomqtt_hierarchical_pad_bucket
aomqtt_whole_rotation
aomqtt_whole_rotation_pad_bucket
```

The central trade-off is:

```text
size leakage reduction vs bandwidth overhead vs delivery latency
```
