#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from aomqtt.control_security import generate_keypair


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ed25519 keys for signed AOMQTT control policies")
    parser.add_argument("--private-out", default="examples/policy_signing_private.key", help="output file for raw-base64 private key")
    parser.add_argument("--public-out", default="examples/policy_signing_public.key", help="output file for raw-base64 public key")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing key files")
    args = parser.parse_args()

    private_path = Path(args.private_out)
    public_path = Path(args.public_out)
    for path in (private_path, public_path):
        if path.exists() and not args.overwrite:
            raise SystemExit(f"refusing to overwrite existing file: {path} (use --overwrite)")

    private_b64, public_b64 = generate_keypair()
    private_path.write_text(private_b64 + "\n", encoding="utf-8")
    public_path.write_text(public_b64 + "\n", encoding="utf-8")
    try:
        private_path.chmod(0o600)
        public_path.chmod(0o644)
    except OSError:
        pass
    print("generated AOMQTT policy signing keys")
    print(f"  private key: {private_path}")
    print(f"  public key:  {public_path}")
    print("Do not commit the private key to GitHub.")


if __name__ == "__main__":
    main()
