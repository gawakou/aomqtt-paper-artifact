# AOMQTT v0.2 Tokenization Modes

AOMQTT Client SDK v0.2 supports two topic tokenization modes.

## 1. hierarchical mode

Input topic:

```text
shelter/siteA/starlink/rtt
```

Output topic:

```text
aomqtt/v1/h/HMAC(shelter)/HMAC(siteA)/HMAC(starlink)/HMAC(rtt)
```

### Advantages

- Preserves the MQTT topic hierarchy.
- Supports limited wildcard subscription.
- Useful when applications need topic groups such as `shelter/siteA/starlink/#`.

### Limitations

- The broker can still observe the number of topic levels.
- Repeated plaintext topic levels produce repeated tokens under the same key.

## 2. whole mode

Input topic:

```text
shelter/siteA/starlink/rtt
```

Output topic:

```text
aomqtt/v1/t/HMAC(shelter/siteA/starlink/rtt)
```

### Advantages

- Hides the number of original topic levels.
- Produces a simpler opaque token topic.

### Limitations

- Wildcard subscriptions cannot be represented without an additional topic directory.
- Subscribers must know the exact plaintext topic to derive the same token.

## Research implication

The two modes expose a useful trade-off:

- hierarchical mode prioritizes MQTT compatibility.
- whole mode prioritizes topic structure concealment.

This trade-off can be evaluated in terms of topic length, broker routing behavior, wildcard support, and topic semantic leakage.
