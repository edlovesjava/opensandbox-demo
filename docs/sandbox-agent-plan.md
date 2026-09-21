# Plan: Sandboxed Claude Code Agent with GitHub Access

Goal: run Claude Code autonomously inside a locked-down container that can
reach git/GitHub and a controlled slice of the internet, with credentials
externalized from the container itself, plus strong auditing/logging of
everything the agent does.

**Runtime: OpenSandbox.** We already have `opensandbox-server` running
locally (see root `README.md`), and its API turns out to have exactly the
primitives this needs natively — a per-sandbox egress sidecar with a
`NetworkPolicy` (allow/deny by domain) and a **Credential Vault** that does
transparent MITM credential injection. That changes the credential mechanism
from "env var + git credential helper" to something stronger: the token
never enters the sandbox container's process space at all.

## Credential mechanism — OpenSandbox Credential Vault

Discovered in the installed `opensandbox` package (`api/egress/...`):

1. **Host-side secret storage** — the token lives in the host's secret store
   (macOS Keychain via `security`, or a `1Password CLI`/`op` vault), never in
   a plaintext `.env` file that's committed or left on disk.
2. **Push it straight to the sandbox's egress sidecar, not the container.**
   Each sandbox has its own egress sidecar (reached at `endpoint.endpoint`,
   resolved per-sandbox — separate from the main lifecycle API). The Python
   SDK's egress adapter talks to it directly:
   ```python
   # conceptually — see opensandbox/api/egress/api/credential_vault/post_credential_vault.py
   POST {sidecar_url}/credential-vault
   {
     "credentials": [
       {"name": "github-pat", "source": {"type": "inline", "value": "<token from Keychain>"}}
     ],
     "bindings": [
       {
         "name": "github-api",
         "match": {"hosts": ["api.github.com", "github.com"], "schemes": ["https"]},
         "auth": {"type": "bearer", "credential": "github-pat"}
       }
     ]
   }
   ```
   The sidecar holds the token in memory and injects `Authorization: Bearer
   <token>` transparently into matching outbound requests via MITM. Inside
   the sandbox, `git clone https://github.com/...` and `gh` calls just work —
   **no token is ever set as an env var or written to a file in the
   container**, so there's nothing for the agent process (or a prompt
   injection in the repo it's working on) to read or exfiltrate directly.
3. **Enable it at sandbox creation** via `CreateSandboxRequest.credentialProxy
   = {"enabled": true}` — required for the transparent MITM support; a plain
   `networkPolicy` alone does not enable it.
4. **Least privilege** — a fine-grained GitHub PAT scoped to only the
   specific repo(s) the agent needs, contents read/write only, short expiry
   to force rotation. Match narrowly (`hosts`, `methods`, `paths` are all
   available on `CredentialMatch`) so the token is only ever injected into
   GitHub API calls, not any other outbound request.
5. **Fallback (if credential vault isn't usable in some environment)**: the
   simpler env-var + git-credential-helper approach from the first draft of
   this plan still works as a degraded mode — inject `GITHUB_TOKEN` via
   `CreateSandboxRequest.env` (populated from Keychain at creation time, never
   from a file) and configure `credential.helper` to read it. Weaker, because
   the token does live in the container's env at that point.

## Egress control — OpenSandbox `NetworkPolicy`

Set via `CreateSandboxRequest.networkPolicy` (shape matches the sidecar's own
`/policy` endpoint): `defaultAction: "deny"`, then explicit `egress` allow
rules for `github.com`, `api.github.com`, `objects.githubusercontent.com`
(extend for package registries as needed). This is native to the sandbox —
no separate proxy container to stand up. `NetworkPolicy` is **not supported
together with `extensions.poolRef`** (pooled pods are pre-created before the
policy could be attached), so agent sandboxes with a credential vault or
custom egress policy must be created directly from an image, not from a
pool.

If OpenSandbox's own policy engine turns out to be too coarse for something
specific, the community options from the original research remain a
fallback layer: Anthropic's `init-firewall.sh` (iptables + ipset), or
[dockade](https://github.com/larsvikb/dockade) for a richer external audit
trail.

## Audit logging

Two native sources to start from, both already verified working against our
local instance:
- `GET /v1/sandboxes/{id}/diagnostics/logs` / `/diagnostics/events` /
  `/diagnostics/summary` — container-level logs and lifecycle events.
- The egress sidecar's own request handling (allow/deny/inject decisions) —
  need to confirm whether it exposes a log/audit endpoint alongside
  `/policy` and `/credential-vault`, or whether that has to be captured by
  shipping the sidecar's own logs out separately. **Open question below.**

Either way, logs should land somewhere the agent container can't write to or
truncate (the sidecar and diagnostics API run outside the sandboxed
container's own filesystem, which already satisfies this).

## Live validation (confirmed)

Ran `scripts/test_credential_vault.py` against the local server. Findings:

- **Server prerequisite**: `credentialProxy.enabled` is rejected unless the
  server's own config (`~/.sandbox.toml`) has `[egress] mode = "dns+nft"`
  (default is `"dns"`, which only supports domain-level allow/deny, not
  credential injection). Changed locally and restarted the server to
  proceed — this is a server-operator setting, not something a sandbox
  creation request can override per-call.
- **Egress sidecar image** (`opensandbox/egress:v1.1.7`) is not bundled and
  must be pulled separately (`docker pull opensandbox/egress:v1.1.7`) —
  the first sandbox-creation attempt after switching modes timed out
  client-side while the server pulled it server-side; the create actually
  succeeded async and left an orphaned sandbox+sidecar to clean up
  manually. **Takeaway: pre-pull the egress image as part of environment
  setup, and always create sandboxes with a generous timeout (or poll)
  the first time a new mode is used.**
- **Credential injection: CONFIRMED working, no extra CA setup needed.** A
  plain unauthenticated request from inside the sandbox
  (`urllib.request.urlopen('https://httpbin.org/headers')`, no curl
  install — the deny-by-default policy blocks apt too) came back with:
  ```json
  "Authorization": "Bearer test-token-do-not-use-1234567890"
  ```
  The MITM injection worked out of the box against Python's default TLS
  trust store — the CA-trust concern in the original draft of this plan
  didn't materialize in practice. (Not yet confirmed against `git`/`gh`
  specifically, or against a real GitHub PAT — see remaining open
  questions.)
- **Token isolation: CONFIRMED.** `env` inside the sandbox never showed the
  fake token — it truly never enters the container's process space.
- **Network policy: CONFIRMED.** A request to a non-allowlisted host
  (`example.com`) failed outright (`CommandExecError`, exit 1) under the
  deny-by-default policy, while the allowlisted host succeeded.

## Remaining open questions

- Repeat this validation with an actual `git clone`/`gh` call against
  `api.github.com` and a real (throwaway/scoped) PAT, not just a raw HTTP
  request — confirms the mechanism works for the actual tool the agent
  will use, not just `urllib`.
- Does the egress sidecar expose an audit-log endpoint for allow/deny/inject
  decisions, or only the `/policy` and `/credential-vault` config
  endpoints? Still needs checking.
- macOS Keychain vs 1Password CLI for host-side secret storage.
- Whether this lives in this repo or a dedicated sister repo.
- Token rotation: does `CredentialVaultMutationRequest` with
  `expectedRevision` let us rotate a credential in place without
  recreating the sandbox? Model shape supports it; not yet tested live.
