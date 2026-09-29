# AOMQTT v0.8.1.1: control-policy rejection logging

v0.8.1.1 changes how expected control-policy security rejections are logged.

In v0.8.1, an unsigned policy, replayed `sequence_no`, expired policy, or unsafe policy value was rejected correctly, but the runtime printed a full Python Traceback. This was confusing because these cases are expected security events rather than program failures.

v0.8.1.1 keeps the same validation behavior but logs expected rejections as a one-line warning:

```text
rejected control policy on aomqtt/control/<group_id>/policy: <reason>
```

Examples include:

```text
rejected control policy on aomqtt/control/shelter-siteA/policy: control policy signature is required
rejected control policy on aomqtt/control/shelter-siteA/policy: control policy sequence_no is not newer than the latest accepted policy
rejected control policy on aomqtt/control/shelter-siteA/policy: policy.padding.fixed_size must be <= 4096
```

Unexpected malformed-message errors still use exception logging so that implementation bugs can be diagnosed.
