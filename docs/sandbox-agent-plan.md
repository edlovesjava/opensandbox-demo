# Plan: Sandboxed Claude Code Agent with GitHub Access

Goal: run Claude Code autonomously inside a locked-down container that can
reach git/GitHub and a controlled slice of the internet, with credentials
supplied via environment variables that are externalized from the container
image and filesystem, plus strong auditing/logging of everything the agent
does.

## Credential mechanism

Never bake a GitHub token into the image or write it to disk inside the
container.

1. **Host-side secret storage** — the token lives in the host's secret store
   (macOS Keychain via `security`, or a `1Password CLI`/`op` vault), never in
   a plaintext `.env` file that's committed or left on disk.
2. **Injection via env var at container-launch time only**:
   ```bash
   docker run -e GITHUB_TOKEN="$(security find-generic-password -s github-agent-token -w)" ...
   # or
   op run --env-file=... -- docker run ...
   ```
   The value exists only in the launching process's environment and the
   container's env — never in a file on either side.
3. **Git credential helper reads the env var, not a file**, inside the
   container:
   ```bash
   git config --global credential.helper '!f() { echo "password=$GITHUB_TOKEN"; }; f'
   ```
   `git push`/`pull`/`clone` over HTTPS authenticate straight from the env
   var; nothing touches `~/.git-credentials` or any credential cache file.
4. **Least privilege** — a fine-grained GitHub PAT scoped to only the
   specific repo(s) the agent needs, contents read/write only, short expiry
   to force rotation.
5. **Redact in logs** — since the token is injected by the host launch
   command (never typed inside the container), audit logging must redact
   `$GITHUB_TOKEN` specifically when capturing command output.

## Egress control

Default-deny network; allowlist only what the agent needs to start with:
`github.com`, `api.github.com`, `objects.githubusercontent.com` (extend for
package registries as needed). Candidates, in rough order of effort:

- Anthropic's own `init-firewall.sh` reference (iptables + ipset
  domain allowlist) from the `anthropics/claude-code` devcontainer — simplest,
  official, minimal auditing.
- [dockade](https://github.com/larsvikb/dockade) — capability-limited
  sandbox, no direct egress, governed proxy as the sole path out, auditing
  control plane the agent can't reach, forwards host git identity.
- `iron-proxy` — structured per-request audit trail (allowed/blocked/swapped)
  designed to sit in front of CI/agent egress.

## Audit logging

Every git/gh command and every proxied network request logged to a location
the agent container can write to but not read back or truncate — an
append-only bind mount, or logs shipped out via a proxy sidecar the agent has
no access to.

## Runtime

We already have OpenSandbox (`opensandbox-server`) running locally with
resource limits, pause/resume, and a `/diagnostics/logs` endpoint. Worth
evaluating as the container runtime instead of raw `docker run`, since it
already gives lifecycle control and logging for free — see the root
`README.md` for the API examples we've exercised against it.

## Open questions

- macOS Keychain vs 1Password CLI for host-side secret storage.
- Which egress/audit stack: Anthropic's reference firewall (simplest) vs.
  dockade/iron-proxy (richer audit trail, less battle-tested).
- Whether this lives in this repo or a dedicated sister repo.
