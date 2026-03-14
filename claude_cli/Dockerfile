ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG CLAUDE_CLI_VERSION

# Install minimal dependencies for Claude Code CLI and Python bridge
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git \
        jq \
        openssh-server \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd

# Install Claude Code CLI native binary to /opt/claude (NOT under /data)
# /data is a runtime mount that would shadow build-time files
# Subshell isolates the temporary HOME override
RUN ( export HOME=/opt/claude \
    && mkdir -p /opt/claude/.local/bin \
    && curl -fsSL https://claude.ai/install.sh | bash -s -- "${CLAUDE_CLI_VERSION}" ) \
    && ln -sf /opt/claude/.local/bin/claude /usr/local/bin/claude

# HOME=/data is set at runtime only (in run.sh) for persistent auth/config

# Install Python bridge dependencies
COPY requirements.txt /opt/bridge/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages \
    -r /opt/bridge/requirements.txt

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
# DISABLE_AUTOUPDATER: version is pinned at build time
# DISABLE_TELEMETRY: no telemetry from addon container
# CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY: no interactive surveys in headless mode
# CLAUDE_CODE_DISABLE_TERMINAL_TITLE: no terminal title manipulation
# CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: disable all non-essential network calls
ENV DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1 \
    CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /data/claude_environment

CMD ["/run.sh"]
