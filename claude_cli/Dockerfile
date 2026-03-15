ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG CLAUDE_CLI_VERSION
ARG BUILD_VERSION
ARG BUILD_ARCH

# Copy requirements first (needed inside monolithic RUN layer)
COPY requirements.txt /tmp/requirements.txt

# Single monolithic RUN — DinD builder has persistent cache that cannot be
# cleared from the host. Separate RUN layers get stale-cached across builds.
# Combining everything into one layer ensures either all or nothing is cached.
RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        git \
        openssh-server \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && CLAUDE_PLATFORM="linux-x64" \
    && if [ "${BUILD_ARCH}" = "aarch64" ]; then CLAUDE_PLATFORM="linux-arm64"; fi \
    && curl -fsSL -o /usr/local/bin/claude \
       "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases/${CLAUDE_CLI_VERSION}/${CLAUDE_PLATFORM}/claude" \
    && chmod +x /usr/local/bin/claude \
    && /usr/local/bin/claude --version \
    && echo "=== Installing Python dependencies ===" \
    && pip3 install --no-cache-dir --break-system-packages \
        -r /tmp/requirements.txt \
    && python3 -c "import aiohttp; print(f'aiohttp {aiohttp.__version__} OK')" \
    && groupadd -r claude \
    && useradd -r -d /home/claude -m -s /bin/bash -g claude claude \
    && usermod -p '*' claude \
    && mkdir -p /run/sshd \
    && rm -f /tmp/requirements.txt \
    && echo "Build complete: version=${BUILD_VERSION} claude=${CLAUDE_CLI_VERSION}"

# Copy bridge server code
COPY bridge/ /opt/bridge/

# Copy default environment files (CLAUDE.md, settings.json, etc.)
COPY defaults/ /opt/defaults/

# Copy config.yaml for version extraction at runtime
COPY config.yaml /opt/config.yaml

# Copy and prepare entrypoint
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Build-time defaults — run.sh uses `env -i` + s6-envdir at runtime,
# so these only apply during `docker build` (e.g. `claude --version` check).
# Runtime telemetry vars are set via s6-envdir in run.sh.
ENV DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1 \
    CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /data/claude_environment

CMD ["/run.sh"]
