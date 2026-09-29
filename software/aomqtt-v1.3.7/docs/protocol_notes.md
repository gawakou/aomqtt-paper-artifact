# AOMQTT Protocol Notes

AOMQTT is implemented as a client-side privacy layer over standard MQTT.
It does not modify MQTT packet formats or require broker-side changes.

## Visible to broker

- Tokenized MQTT topic
- Encrypted payload envelope
- Message timing and size
- Client connection metadata

## Hidden from broker

- Plaintext topic name
- Topic semantic labels such as location, device, or metric name
- Plaintext payload content

## v0.4 implementation note

The prototype uses Eclipse Paho through `PahoMQTTAdapter`, but the AOMQTT Core
modules are independent from Paho:

- `aomqtt.core`: tokenization, encryption, rotation
- `aomqtt.transport`: MQTT client adapter interface and Paho adapter
- `aomqtt.observation`: publish-side metrics and CSV logging
