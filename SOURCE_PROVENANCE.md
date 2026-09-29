# Source Provenance

## Evaluated software baseline

AOMQTT v1.3.7

Commit:

`6dc0b2c497098aca569a636d1f8f8bb2adc4253a`

Development repository:

https://github.com/gawakou/aomqtt-client-sdk

This is the fixed AOMQTT software revision used for the journal-level E1
replication and the E2 multi-client evaluation.

## E1 journal replication

Topology:

- 1 publisher
- 1 subscriber
- 1 MQTT broker

Conditions:

- A1: Plain MQTT
- A2: topic protection and payload encryption
- A3: A2 + fixed 512-byte padding
- A4: A3 + 30-s token rotation with 5-s overlap

Runs:

- 5 accepted runs per condition
- 6,000 logical messages per run
- QoS 1

The journal E1 experiment was re-run with AOMQTT v1.3.7 so that
the feature-level evaluation and E2 use the same AOMQTT software revision.

## E2 multi-client evaluation

Topology:

- 5 publishers
- 5 subscribers
- 1 MQTT broker

Conditions:

- Plain MQTT
- Full AOMQTT

Runs:

- 10 accepted runs per condition

The Full configuration uses topic protection, payload encryption, fixed
512-byte padding, and 30-s token rotation with a 5-s overlap.

## Public-artifact sanitization

The public E1 archive was sanitized only to remove an e-mail address contained
in environment metadata. The experiment measurement data were not modified.

Private RFC1918 addresses, laboratory VM hostnames, and local filesystem paths
may remain where they serve as experimental provenance.

## Exclusions

This repository is intended to contain the public, paper-relevant artifact.
It does not intentionally include authentication credentials, private keys,
API tokens, unrestricted packet captures, or unrelated development material.
