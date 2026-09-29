# AOMQTT v0.8.1: Control-topic policy security

v0.8.0 introduced MQTT control-topic policy distribution. v0.8.1 adds security checks for that control plane.

## Threats addressed

- Unauthorized Policy injection on `aomqtt/control/<group_id>/policy`
- Policy tampering in transit
- Replay of older Policies
- Expired Policy reuse
- Unsafe Policy values that can cause denial of service or excessive overhead

## Mechanisms

### Ed25519 signature

The Policy Controller signs the canonical control message. Publisher and Subscriber clients verify the signature before scheduling a runtime Policy update.

Controller holds:

```text
Ed25519 private signing key
```

Clients hold:

```text
Ed25519 public verification key
```

### Replay prevention

Control messages include:

```text
sequence_no
issued_at
valid_from
expires_at
```

Clients reject a signed Policy whose `sequence_no` is not newer than the latest accepted sequence number.

### Safety limits

Clients apply local guardrails even to signed Policies. The default limits reject:

- rotation intervals shorter than 5 seconds
- overlap windows larger than half of the rotation interval
- fixed padding larger than 4096 bytes
- bucket padding sizes outside the approved bucket list
- random padding larger than 4096 bytes

## Non-goals in v0.8.1

v0.8.1 does not yet provide Policy ACK, applied/rejected status, rollback, or automatic Policy selection. These are planned for v0.8.2 and later.
