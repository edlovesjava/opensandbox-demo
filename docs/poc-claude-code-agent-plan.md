# POC Plan: Claude Code Reference Implementation in an OpenSandbox Container

Goal: a proof of concept where a specification goes in, and a GitHub pull
request ready for human review comes out — with Claude Code doing the
implementation work autonomously inside an OpenSandbox sandbox that has
scoped GitHub access and full auditability, using the mechanism validated
in `docs/sandbox-agent-plan.md`.

## Scope (POC, not production)

- One target repository, one spec, one PR. No multi-repo orchestration, no
  auto-merge, no retry/self-healing loops yet.
- Human review gate is the PR itself — the agent's job ends at "PR opened,"
  never "PR merged."
- Optimize for proving the mechanism end-to-end, not for polish.

## Workflow

```
spec (markdown/text)
   │
   ▼
1. Create sandbox (image with Claude Code CLI + git + gh + language
   runtime for the target repo; credentialProxy enabled; networkPolicy
   allowlisting github.com, api.github.com, objects.githubusercontent.com,
   api.anthropic.com, + package registries the repo needs)
   │
   ▼
2. Register Credential Vault bindings:
     - GitHub PAT  → hosts: github.com, api.github.com
     - Anthropic API key → host: api.anthropic.com
   (both injected transparently; neither ever touches the sandbox's env)
   │
   ▼
3. Inside the sandbox:
     git clone https://github.com/<org>/<repo>.git
     git checkout -b <generated-branch-name>
     claude -p "<spec text>" --permission-mode <auto|bypassPermissions>
            --cwd <repo>          # non-interactive, unattended
     git add -A && git commit -m "..."
     git push -u origin <branch>
     gh pr create --title ... --body "... links back to spec ..."
   │
   ▼
4. Collect audit trail (diagnostics/logs, egress decisions, Claude Code's
   own session transcript) and hand back: PR URL + audit bundle.
```

## Open design questions, in priority order

1. **Claude Code auth in headless/unattended mode.** Does a non-interactive
   `claude -p` run need an `ANTHROPIC_API_KEY`-style credential, or does it
   support OAuth/subscription auth without an interactive login flow? This
   decides whether step 2's Anthropic credential is even the right shape,
   and whether it needs to be injected via the vault (MITM header) vs.
   passed some other way Claude Code specifically expects.
2. **Unattended permission mode.** With no human present to approve tool
   calls, the agent needs a permission mode that doesn't block on prompts
   (`auto` or `bypassPermissions`) scoped tightly to the sandbox — since
   the sandbox is already the security boundary (no host filesystem
   access, egress locked down), bypassing in-container prompts is
   reasonable, but needs to be an explicit, documented choice, not a
   default.
3. **Branch naming and idempotency.** What generates the branch name (spec
   slug + timestamp?), and what happens on a rerun against the same spec —
   new branch each time, or detect/reuse?
4. **Audit trail completeness.** `docs/sandbox-agent-plan.md` already flags
   that we haven't confirmed whether the egress sidecar exposes an
   allow/deny/inject audit log beyond `/policy` and `/credential-vault`
   config endpoints. For this POC we additionally want Claude Code's own
   transcript (what it read, what it changed, why) captured and handed
   back alongside the PR — need to check whether `claude -p` supports a
   transcript/log output path.
5. **Failure handling.** What happens if `claude -p` can't satisfy the
   spec, or the build/tests fail before commit? For the POC: don't push a
   broken branch — surface the failure and the sandbox's diagnostics
   instead of a PR.
6. **PR body contents.** Should include: the spec (or a link to it), a
   summary of what was implemented, and an explicit "opened autonomously,
   needs human review" marker — never claim tests passed unless they
   verifiably did in the sandbox.

## Phased build-out

- **Phase 1 — walking skeleton.** Hand-picked trivial spec (e.g. "add a
  one-line README badge") against a throwaway test repo. Everything else
  hardcoded. Goal: prove the full chain works once, end to end, with a
  human watching every step.
- **Phase 2 — generalize inputs.** Accept an arbitrary spec + target repo
  as parameters. Add the branch-naming and idempotency answers from above.
- **Phase 3 — harden auditability and least privilege.** Real audit bundle
  captured and attached to the PR or stored alongside it; PAT scoped to
  exactly the target repo; resource limits and timeouts tuned from
  observed usage.

## Prerequisites carried over from `sandbox-agent-plan.md`

- `[egress] mode = "dns+nft"` on the server, egress sidecar image
  pre-pulled.
- A scoped, short-lived GitHub PAT for the target repo (contents
  read/write only).
- Decide macOS Keychain vs 1Password CLI for host-side secret storage
  before this touches anything beyond a local throwaway test repo.

## Next step

Answer open question 1 (Claude Code headless auth) first — it blocks
everything else in the workflow above. Then build Phase 1 against a
disposable test repo.
