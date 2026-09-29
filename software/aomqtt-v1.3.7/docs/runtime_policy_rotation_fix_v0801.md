# AOMQTT Client SDK v0.8.0.1: runtime rotation subscription fix

This bugfix release improves MQTT control-topic based runtime Policy updates.

## Issue in v0.8.0

When a Subscriber started with rotation disabled and later received a rotation-enabled Policy through the MQTT control topic, it subscribed to the token filters that were active at the moment of policy application. However, it did not start a periodic subscription refresh loop. After the next epoch boundary, the Publisher continued publishing to the next rotated token topic, while the Subscriber could remain subscribed only to the previous token topic.

This could appear as follows:

- Publisher metrics: all logical messages are published successfully.
- Subscriber metrics: delivery stops after the epoch changes.
- `decrypt_failed` remains zero, because missing messages are not received at all.

## Fix

`AOMQTTSubscriber.apply_policy()` now calls `_ensure_policy_subscription_refresher()` after applying a runtime Policy. If the new Policy enables rotation, the Subscriber starts a lightweight refresh loop that periodically subscribes to the currently valid rotation epochs. This matches the behavior of `subscribe_rotating()` and keeps subscriptions current after dynamic Policy changes.

## Expected behavior

For an experiment that starts with `whole_no_padding_initial` and switches to `whole_bucket_rotation`, the Subscriber should continue receiving messages after the next epoch boundary. The delivery summary should show the logical message count close to the Publisher count, with `decrypt_failed = 0`.
