ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG CLAUDE_CLI_VERSION
ARG BUILD_VERSION
ARG BUILD_ARCH

# Single monolithic RUN — DinD builder has persistent cache that cannot be
# cleared from the host. Separate RUN layers get stale-cached across builds.
# Combining everything into one layer ensures either all or nothing is cached.
RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git \
        jq \
        openssh-server \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd \
    && CLAUDE_PLATFORM="linux-x64" \
    && if [ "${BUILD_ARCH}" = "aarch64" ]; then CLAUDE_PLATFORM="linux-arm64"; fi \
    && curl -fsSL -o /usr/local/bin/claude \
       "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases/${CLAUDE_CLI_VERSION}/${CLAUDE_PLATFORM}/claude" \
    && chmod +x /usr/local/bin/claude \
    && /usr/local/bin/claude --version \
    && echo "=== Installing Python dependencies ===" \
    && pip3 install --no-cache-dir --break-system-packages \
        claude-code-sdk==0.0.25 \
        PyJWT==2.12.1 \
        "cryptography>=46.0.0" \
        aiohttp==3.11.18 \
    && python3 -c "import aiohttp; print(f'aiohttp {aiohttp.__version__} OK')" \
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

# Hardcoded environment variables (not user-configurable)
ENV DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1 \
    CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /data/claude_environment

CMD ["/run.sh"]
