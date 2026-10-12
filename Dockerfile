# syntax=docker/dockerfile:1

# Claude Code Remote Control session: Claude Code plus the tools a session uses.
# Everything is pinned; bump the ARGs by hand (README, Versions). linux/amd64 only.
FROM node:26-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.296
ARG GH_VERSION=2.102.0
ARG DOCKER_VERSION=29.9.0
ARG KIND_VERSION=v0.33.0
ARG KUBECTL_VERSION=v1.36.4
ARG HELM_VERSION=v4.3.0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl git tini; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
      | tar -xz -C /tmp "gh_${GH_VERSION}_linux_amd64/bin/gh"; \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh; \
    curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz" \
      | tar -xz -C /tmp docker/docker; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    curl -fsSLo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64"; \
    chmod 0755 /usr/local/bin/kind; \
    curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"; \
    chmod 0755 /usr/local/bin/kubectl; \
    curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar -xz -C /tmp linux-amd64/helm; \
    install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm; \
    rm -rf /tmp/*

RUN set -eux; \
    npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    npm cache clean --force

# The node image ships user "node" (uid 1000); the session runs as "claude" with that uid.
RUN set -eux; \
    usermod -l claude -d /home/claude -m node; \
    groupmod -n claude node; \
    mkdir -p /workspace; \
    chown claude:claude /workspace

COPY --chmod=0755 bin/claude-rc bin/git-credential-claude-rc /usr/local/bin/

ENV HOME=/home/claude \
    CLAUDE_CONFIG_DIR=/home/claude/.claude \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1

USER claude
WORKDIR /workspace
ENTRYPOINT ["tini", "--", "claude-rc"]
