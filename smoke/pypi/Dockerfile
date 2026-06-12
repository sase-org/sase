# syntax=docker/dockerfile:1

FROM python:3.12-slim

ARG UV_VERSION=0.11.20
ARG CLAUDE_CODE_NPM_SPEC=@anthropic-ai/claude-code
ARG USER_ID=1000
ARG GROUP_ID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    TERM=xterm-256color \
    PATH="/home/tester/.local/bin:/usr/local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gh \
        git \
        locales \
        nodejs \
        npm \
        tmux \
    && sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && python -m pip install --no-cache-dir "uv==${UV_VERSION}" \
    && npm install -g "${CLAUDE_CODE_NPM_SPEC}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${GROUP_ID}" tester \
    && useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home --shell /bin/bash tester \
    && mkdir -p /work /results \
    && chown -R tester:tester /home/tester /work /results

COPY entrypoint.sh /usr/local/bin/pypi-smoke-entrypoint
COPY smoke_check.sh /usr/local/bin/pypi-smoke-check

RUN chmod 0755 /usr/local/bin/pypi-smoke-entrypoint /usr/local/bin/pypi-smoke-check

USER tester
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/pypi-smoke-entrypoint"]
CMD ["check"]
