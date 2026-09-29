# AOMQTT v0.3 Token Rotation

v0.3 introduces time-window based Token Rotation.

## Goal

In v0.1/v0.2, the same plaintext topic always maps to the same token topic.
A public broker cannot infer the plaintext topic, but it can track the same token topic over time.

Token Rotation reduces this long-term linkability by changing token topics periodically.

## Token derivation

```text
epoch = floor(current_unix_time / rotation_interval_sec)
token = HMAC(topic_key, topic_or_level || epoch)
```

## Overlap Window

At the beginning of a new epoch, publisher and subscriber may not switch at exactly the same time.
Therefore, v0.3 uses an overlap window.

During the overlap window:

- Publisher sends to current and previous epoch token topics.
- Subscriber subscribes to current and previous epoch token filters.

After the overlap window:

- Publisher sends to current epoch only.
- Subscriber eventually follows the current epoch through subscription refresh.

## Trade-off

Longer overlap windows reduce missing messages, but increase duplicate traffic and make linkability slightly easier during the overlap period.

Shorter overlap windows reduce duplicate traffic, but require better clock synchronization and faster subscription refresh.
