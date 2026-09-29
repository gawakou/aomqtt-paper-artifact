# AOMQTT roadmap after v0.8.1

## Completed in v0.8.1

- Ed25519 Policy signatures
- Signature verification in Publisher/Subscriber control-topic receivers
- `sequence_no`, `issued_at`, `expires_at`
- Replay and expiration checks
- Client-side Policy safety limits
- Runtime rotation-subscription refresh fix from v0.8.0.1

## Next: v0.8.2

- Policy ACK topic: `aomqtt/control/<group_id>/ack`
- Applied/rejected/failed status messages
- Controller-side ACK collection
- Timeout detection
- Rollback preparation

## Later: v0.8.3

- Metrics aggregation
- Rule-based Policy selection
- Observation-driven Policy control
