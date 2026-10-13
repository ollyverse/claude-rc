# claude-rc

Claude Code [Remote Control](https://code.claude.com/docs/en/remote-control) sessions as Kubernetes workloads:
an image with Claude Code and the tools a session needs, and a Helm chart that runs one always-on,
unprivileged **controller** session plus a scale-from-zero StatefulSet of **worker** sessions with
Docker-in-Docker (so a worker can run `docker build` and `kind create cluster`). You drive the sessions
from claude.ai/code or the Claude app; nothing is exposed.

Why and how it is operated on ollyverse's cluster: `ollyplatform/docs/design/2026-10-12-claude-remote-control.md`
and `ollyplatform/docs/runbooks/claude-rc.md`.

## Layout

```
Dockerfile                        node:24-bookworm-slim + Claude Code, git, gh, docker CLI, kind, kubectl, helm
bin/claude-rc                     entrypoint: GitHub tokens, checkouts, wait for the claude.ai login, remote-control server
bin/git-credential-claude-rc      git credential helper: one token file per GitHub owner
bin/gh                            gh wrapper: the real gh (/usr/local/libexec/gh) with the current repository owner's token
charts/claude-rc                  the Helm chart (controller Deployment + RBAC, worker StatefulSet + dind)
tests/                            unit tests for the two scripts and the rendered chart
```

## Authentication

Remote Control needs a full claude.ai login (`claude auth login`); API keys and `claude setup-token` tokens
cannot open Remote Control sessions. The login lives on the pod's volume under `CLAUDE_CONFIG_DIR`; the
entrypoint waits until it exists and tells you the `kubectl exec` command to run. GitHub access is one
fine-grained token per owner, mounted as files named after the owner (`/etc/claude-rc/github/<owner>`);
`git-credential-claude-rc` picks the file from the repository path on every git call, and `gh` is a wrapper
that runs the real gh with the token of the current repository's `origin` owner in `GH_TOKEN` for that one
process. Nothing is ever logged in or stored (fine-grained tokens all authenticate as their creator, so
`gh auth login` could keep only one); a rotated token is used on the next call. Outside a repository, or in
one whose owner has no token file, `gh` runs unauthenticated; set `GH_TOKEN` yourself for that call.

## Versions

Tools are pinned as `ARG`s at the top of the `Dockerfile` and bumped by hand (Dependabot covers the base
image and the actions). Chart version = app version = image tag.

## Release

Releases are git tags `vMAJOR.MINOR.PATCH`. Pushing one runs `.github/workflows/release.yml`, which publishes,
in this order (each step only if the previous one succeeded):

1. image `ghcr.io/ollyverse/claude-rc:X.Y.Z` (+ `X.Y`, `X`, `latest`), linux/amd64,
2. Helm chart `oci://ghcr.io/ollyverse/charts/claude-rc` version `X.Y.Z`, appVersion `X.Y.Z` (runs image `X.Y.Z`),
3. the GitHub Release for the tag with auto-generated notes.

```bash
git switch main && git pull --ff-only
gh run list --workflow ci.yml --branch main --limit 1      # last CI must be green
VERSION=0.1.0
git tag -a "v$VERSION" -m "v$VERSION" && git push origin "v$VERSION"
gh run watch "$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

Pull requests only build the image; pushes to `main` never publish anything.
