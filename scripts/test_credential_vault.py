#!/usr/bin/env python3
"""
Live validation of OpenSandbox's Credential Vault + NetworkPolicy mechanism.

Does NOT use a real GitHub token. Instead it binds a fake bearer token to
httpbin.org (which echoes back the request headers it receives) so we can
directly observe whether the egress sidecar's transparent MITM injection
actually adds the Authorization header, without needing real credentials
or network access to GitHub during validation.

Requires the local opensandbox-server's config (~/.sandbox.toml) to have
[egress] mode = "dns+nft" — credentialProxy.enabled rejects sandbox
creation otherwise (confirmed live). Uses python3's built-in urllib inside
the sandbox instead of curl, since curl isn't preinstalled and apt is
itself blocked by the deny-by-default network policy in this test.

What this checks, concretely:
  1. Register a fake credential + host-scoped binding in the sandbox's
     Credential Vault after creating it with credential_proxy enabled and
     a network policy that denies-by-default and allows only httpbin.org.
  2. Is the fake token absent from the sandbox's own environment (`env`)
     — i.e. does the agent process never see it?
  3. Does a plain unauthenticated request to https://httpbin.org/headers
     from inside the sandbox come back with our injected Authorization
     header?
  4. Does a request to a non-allowlisted host (example.com) get blocked by
     the network policy?

Run with the project venv:
  .venv/bin/python scripts/test_credential_vault.py
"""

import asyncio
import sys

from opensandbox.config import ConnectionConfig
from opensandbox.models.sandboxes import (
    CredentialProxyConfig,
    NetworkPolicy,
    NetworkRule,
)
from opensandbox.sandbox import Sandbox

FAKE_TOKEN = "test-token-do-not-use-1234567890"


async def main() -> int:
    config = ConnectionConfig(domain="localhost:8080", protocol="http")

    policy = NetworkPolicy(
        default_action="deny",
        egress=[
            NetworkRule(action="allow", target="httpbin.org"),
        ],
    )

    print("Creating sandbox with credential_proxy enabled + deny-by-default network policy...")
    sandbox = await Sandbox.create(
        "python:3.11-slim",
        entrypoint=["sleep", "600"],
        resource={"cpu": "500m", "memory": "512Mi"},
        network_policy=policy,
        credential_proxy=CredentialProxyConfig(enabled=True),
        metadata={"purpose": "credential-vault-validation"},
        connection_config=config,
    )
    print(f"Sandbox created: {sandbox.id}")

    try:
        print("\n--- Step 1: register credential + binding in the vault ---")
        vault_state = await sandbox.credential_vault.create(
            credentials=[
                {"name": "test-cred", "source": {"type": "inline", "value": FAKE_TOKEN}},
            ],
            bindings=[
                {
                    "name": "httpbin-binding",
                    "match": {"hosts": ["httpbin.org"], "schemes": ["https"]},
                    "auth": {"type": "bearer", "credential": "test-cred"},
                },
            ],
        )
        print(f"Vault state: revision={vault_state.revision}, "
              f"credentials={[c.name for c in vault_state.credentials]}, "
              f"bindings={[b.name for b in vault_state.bindings]}")

        print("\n--- Step 2: env inside sandbox must NOT contain the token ---")
        r = await sandbox.commands.run("env")
        print("TOKEN LEAKED INTO ENV!" if FAKE_TOKEN in r.text else "OK: token not present in sandbox env")

        print("\n--- Step 3: unauthenticated request to httpbin.org/headers (allowlisted), via python3 (no curl install needed) ---")
        py_get = (
            "python3 -c \"import urllib.request;"
            "print(urllib.request.urlopen('https://httpbin.org/headers', timeout=10).read().decode())\""
        )
        r = await sandbox.commands.run(py_get)
        print(r.text)
        if r.error:
            print(f"[error] {r.error.name}: {r.error.value}")
        if FAKE_TOKEN in r.text:
            print(f"CONFIRMED: sidecar injected the Authorization header (found token '{FAKE_TOKEN}' in response)")
        else:
            print("NOT CONFIRMED: token not seen in response — check CA trust / MITM mode (see docs/sandbox-agent-plan.md open questions)")

        print("\n--- Step 4: request to a NON-allowlisted host (example.com) should be blocked ---")
        py_get_blocked = (
            "python3 -c \"import urllib.request;"
            "print(urllib.request.urlopen('https://example.com/', timeout=5).read()[:50])\""
        )
        r = await sandbox.commands.run(py_get_blocked)
        print(r.text)
        if r.error:
            print(f"[error] {r.error.name}: {r.error.value}")

    finally:
        print(f"\nCleaning up sandbox {sandbox.id}...")
        await sandbox.destroy()
        print("Deleted.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
