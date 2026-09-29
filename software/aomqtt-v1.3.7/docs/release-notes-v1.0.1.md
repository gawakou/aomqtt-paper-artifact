# AOMQTT Client SDK v1.0.1 Release Notes

v1.0.1 is a hardening release based on an external strict review of v1.0.0.
The release keeps the project positioned as a research prototype, but fixes
several implementation bugs and reduces insecure defaults that could otherwise
lead to accidental misuse outside an isolated laboratory environment.

## Fixed bugs

1. **Subscriber re-subscription after reconnect**

   `AOMQTTSubscriber` now remembers token filters and QoS values and re-sends
   SUBSCRIBE after MQTT reconnects.  This addresses the case where Paho MQTT
   v3.1.1 clean sessions lose broker-side subscriptions after disconnects.

2. **Key exposure through repr/to_dict**

   `AOMQTTConfig` now disables the dataclass default `repr` and implements a
   redacted representation.  `to_dict()` redacts `topic_key` and `payload_key`
   by default.  Internal code that needs full reconstruction calls
   `to_dict(redact=False)` explicitly.

3. **Random padding range bug**

   Random padding now uses `secrets.randbelow(span)` and covers the configured
   range beyond 255 bytes without modulo bias.

4. **Unbounded duplicate-detection state**

   Subscriber-side duplicate detection now uses a bounded LRU-style message-id
   window.  The default window is 10,000 message IDs and can be changed with
   `seen_message_ids_max` when constructing `AOMQTTSubscriber`.

## Safer defaults

1. **Signed control policies by default**

   `ControlTopicPolicyReceiver` and `start_policy_control()` now require signed
   policies by default.  Code that intentionally performs an isolated unsigned
   local experiment must pass `require_signature=False`.  The example CLIs use
   signed control by default and provide `--allow-unsigned-control-policy` as an
   explicit unsafe opt-out.

2. **Local-only Mosquitto example**

   `mosquitto/config/mosquitto.conf` now binds to `127.0.0.1` for native local
   experiments and clearly states that it is only for local experiments.
   Docker uses `mosquitto/config/mosquitto.docker.conf` inside the container,
   while `docker-compose.yml` maps the host-side broker port to
   `127.0.0.1:1883:1883`.

## Still documented as prototype limitations

- Payload AEAD key derivation remains `SHA-256(payload_key)` for protocol
  compatibility with previous experiments.  Use high-entropy keys; do not use
  human-memorable passwords.
- Token rotation does not rotate `payload_key`.  Long-running deployment needs
  a key-management and payload-key rotation design.
- MQTT QoS 0 remains the simple default for baseline evaluation.  Use QoS 1/2
  explicitly when experiments require broker acknowledgements.

## Validation

The v1.0.1 test suite adds hardening tests for redaction, random padding span,
subscriber reconnect re-subscription, bounded duplicate tracking, and signed
control-topic default behavior.
