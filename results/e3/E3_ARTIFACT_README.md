# E3 broker-visible privacy-leakage artifact

This archive supports the E3 evaluation in the AOMQTT manuscript.

It contains:

- deterministic E3-A and E3-B event plans for formal runs r01-r05;
- accepted E3-A formal run data for A0-A2;
- accepted E3-B formal run data for B0-B3;
- per-run gate reports and freeze/checksum records;
- the final privacy-analysis outputs;
- the frozen E3 experiment and analysis scripts and unit tests.

E3-A evaluates broker-visible payload-length inference.

E3-B evaluates cross-epoch topic-token linkability, including the effect of
fixed padding and a 5-s token-rotation overlap.

The archive is tied to AOMQTT v1.3.7 and to the frozen harness revisions listed
in `provenance/e3-provenance.md`.
