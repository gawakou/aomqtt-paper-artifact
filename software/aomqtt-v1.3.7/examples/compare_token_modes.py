#!/usr/bin/env python3
from __future__ import annotations

import argparse

from aomqtt import AOMQTTConfig, TopicTokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare AOMQTT v0.2 topic tokenization modes")
    parser.add_argument("--config", default="examples/config.example.yaml")
    parser.add_argument("--topic", default="shelter/siteA/starlink/rtt")
    parser.add_argument("--filter", default="shelter/siteA/starlink/#")
    args = parser.parse_args()

    base = AOMQTTConfig.from_yaml(args.config)

    print("Plaintext topic:")
    print(f"  {args.topic}")
    print()

    for mode in ("hierarchical", "whole"):
        cfg = base.with_token_mode(mode)  # type: ignore[arg-type]
        tok = TopicTokenizer(cfg)
        print(f"[{mode}]")
        print(f"  publish topic:   {tok.tokenize(args.topic)}")
        try:
            print(f"  subscribe filter:{tok.tokenize_filter(args.filter)}")
        except Exception as e:
            print(f"  subscribe filter: unsupported ({e})")
        print()


if __name__ == "__main__":
    main()
