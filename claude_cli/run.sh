#!/usr/bin/with-contenv bash
set -e

# ============================================================================
# Claude CLI Addon Entrypoint
# ============================================================================
# Initializes the Claude Code environment and starts the Python bridge server.
# Environment files are only copied on first run; subsequent starts preserve
# user modifications.
# ============================================================================

# Set HOME at runtime for persistent auth tokens, config, and sessions
export HOME=/data

CONFIG_PATH=/data/options.json

# Validate options.json — fail fast on corrupt config
if ! jq empty "$CONFIG_PATH"; then
    echo "[claude_cli] FATAL: options.json is missing or invalid JSON"
    exit 1
fi

# Export addon version from config.yaml (single source of truth)
ADDON_VERSION=$(sed -n 's/^version: *"\(.*\)"/\1/p' /opt/config.yaml)
export ADDON_VERSION="${ADDON_VERSION:-unknown}"

# ----------------------------------------------------------------------------
# Initialize default environment files on first run
# ----------------------------------------------------------------------------
if [ ! -f /data/claude_environment/CLAUDE.md ]; then
    echo "[claude_cli] First run — initializing default environment files"
    mkdir -p /data/claude_environment/.claude/commands
    cp -rn /opt/defaults/* /data/claude_environment/ 2>&1 || { echo "[claude_cli] ERROR: failed to copy default files"; exit 1; }
    cp -rn /opt/defaults/.claude /data/claude_environment/ 2>&1 || { echo "[claude_cli] ERROR: failed to copy .claude defaults"; exit 1; }
    echo "[claude_cli] Default environment initialized at /data/claude_environment/"
fi

# ----------------------------------------------------------------------------
# Build s6-envdir directory — each env var is a file (no cmdline leaks)
# ----------------------------------------------------------------------------
ENVDIR="/tmp/bridge_envdir"
rm -rf "$ENVDIR"
mkdir -p "$ENVDIR"
chmod 700 "$ENVDIR"

export_if_set() {
    local key="$1"
    local var="$2"
    local val
    val=$(jq -r --arg k "$key" 'if has($k) then .[$k] | tostring else "" end' "$CONFIG_PATH")
    if [ -n "$val" ]; then
        printf '%s' "$val" > "${ENVDIR}/${var}"
        echo "[claude_cli] Set ${var}"
    fi
}

export_if_set "anthropic_api_key" "ANTHROPIC_API_KEY"
export_if_set "anthropic_base_url" "ANTHROPIC_BASE_URL"
export_if_set "anthropic_model" "ANTHROPIC_MODEL"
export_if_set "anthropic_custom_headers" "ANTHROPIC_CUSTOM_HEADERS"
export_if_set "max_output_tokens" "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
export_if_set "max_thinking_tokens" "MAX_THINKING_TOKENS"

telemetry_disabled=$(jq -r '.disable_telemetry // true' "$CONFIG_PATH")
if [ "$telemetry_disabled" = "false" ]; then
    echo "[claude_cli] Telemetry enabled by user configuration"
else
    printf '1' > "${ENVDIR}/DISABLE_TELEMETRY"
    printf '1' > "${ENVDIR}/CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
fi

# Lock down envdir: read-only for owner (claude), no write access at runtime
# Use find to avoid glob failure when directory is empty (set -e would exit)
find "$ENVDIR" -maxdepth 1 -type f -exec chmod 400 {} +
chmod 500 "$ENVDIR"
chown -R claude:claude "$ENVDIR"

# ----------------------------------------------------------------------------
# Configure and start SSH daemon (key-only authentication)
# ----------------------------------------------------------------------------
setup_ssh() {
    local ssh_dir="/home/claude/.ssh"
    local auth_keys="${ssh_dir}/authorized_keys"
    local sshd_config="/etc/ssh/sshd_config"

    if [ ! -x /usr/sbin/sshd ]; then
        echo "[claude_cli] WARNING: sshd not found — SSH access unavailable"
        return 1
    fi

    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    # Write authorized keys atomically, filtering null/empty values.
    # Only accept lines starting with a valid key type to prevent
    # authorized_keys options injection (e.g., command="..." prefix).
    local temp
    temp=$(mktemp "${ssh_dir}/authorized_keys.XXXXXX")
    chmod 600 "$temp"
    chown claude:claude "$temp"
    jq -r '.ssh_authorized_keys[]? // empty | select(. != null and . != "")' "$CONFIG_PATH" | \
        grep -E '^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp[0-9]+|sk-ssh-ed25519|sk-ecdsa-sha2-nistp[0-9]+) ' > "$temp" || true
    mv "$temp" "$auth_keys"

    local key_count
    key_count=$(wc -l < "$auth_keys" | tr -d ' ')

    if [ "$key_count" -eq 0 ]; then
        echo "[claude_cli] WARNING: No SSH authorized keys configured — SSH access disabled"
        return 1
    fi

    chown -R claude:claude "$ssh_dir"

    # Generate host keys if missing (persistent across restarts via /data)
    local host_key_dir="/data/.ssh_host_keys"
    mkdir -p "$host_key_dir"
    if [ ! -f "${host_key_dir}/ssh_host_rsa_key" ]; then
        if ! ssh-keygen -t rsa -b 4096 -f "${host_key_dir}/ssh_host_rsa_key" -N "" -q; then
            echo "[claude_cli] ERROR: Failed to generate RSA host key"
            return 1
        fi
    fi
    if [ ! -f "${host_key_dir}/ssh_host_ed25519_key" ]; then
        if ! ssh-keygen -t ed25519 -f "${host_key_dir}/ssh_host_ed25519_key" -N "" -q; then
            echo "[claude_cli] ERROR: Failed to generate Ed25519 host key"
            return 1
        fi
    fi

    # Ensure privilege separation and runtime directories exist (required by OpenSSH)
    mkdir -p /var/empty /run/sshd

    # Configure sshd: key-only, hardened, no password, no sftp
    cat > "$sshd_config" <<SSHD_EOF
Port 22
HostKey ${host_key_dir}/ssh_host_rsa_key
HostKey ${host_key_dir}/ssh_host_ed25519_key
PermitRootLogin no
AllowUsers claude
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
AuthorizedKeysFile ${auth_keys}
PrintMotd yes
AcceptEnv LANG LC_*
# Algorithm hardening
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com
HostKeyAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256
# Session hardening
MaxAuthTries 3
MaxSessions 3
LoginGraceTime 30
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
ClientAliveInterval 300
ClientAliveCountMax 2
# sftp intentionally disabled — this is a CLI-only container
Subsystem sftp /bin/false
LogLevel INFO
SSHD_EOF

    # Validate config before starting
    if ! /usr/sbin/sshd -t; then
        echo "[claude_cli] ERROR: sshd config test failed — SSH will not start"
        return 1
    fi

    /usr/sbin/sshd
    echo "[claude_cli] SSH daemon started with ${key_count} authorized key(s)"
    return 0
}

setup_ssh || echo "[claude_cli] WARNING: SSH setup failed — bridge will start without SSH"

# ----------------------------------------------------------------------------
# Log startup information
# ----------------------------------------------------------------------------
echo "[claude_cli] Addon version: ${ADDON_VERSION}"
echo "[claude_cli] Claude Code CLI: $(claude --version 2>&1 || echo 'not found')"
echo "[claude_cli] Bridge server starting on port 8099"

# ----------------------------------------------------------------------------
# Start the Python bridge server
# -u: unbuffered stdout/stderr for real-time log output
# ----------------------------------------------------------------------------

# Generate shared secret atomically with correct ownership
if [ ! -f /data/shared_secret ] || [ ! -s /data/shared_secret ]; then
    temp=$(mktemp /data/.secret_XXXXXX)
    (umask 077 && python3 -c "import secrets; print(secrets.token_hex(32), end='')" > "$temp")
    chown claude:claude "$temp"
    mv "$temp" /data/shared_secret
    echo "[claude_cli] Generated new shared secret"
else
    # Ensure correct ownership on existing secret
    chown claude:claude /data/shared_secret
fi

# Set up claude user's data directory and permissions
mkdir -p /data/claude_environment/.claude/commands
chown -R claude:claude /data/claude_environment

# Protect settings.json from modification by the claude user at runtime.
# This prevents Claude Code (running as claude with allowEdits) from editing
# its own deny list to escalate privileges. Users can edit via HA file
# editor, Samba addon, or VS Code addon and restart.
if [ -f /data/claude_environment/.claude/settings.json ]; then
    chown root:claude /data/claude_environment/.claude/settings.json
    chmod 440 /data/claude_environment/.claude/settings.json
fi

# options.json: readable by bridge process via group, not world-readable
if [ -f /data/options.json ]; then
    chown root:claude /data/options.json
    chmod 640 /data/options.json
else
    echo "[claude_cli] WARNING: /data/options.json not found"
fi

# Start bridge as claude user with s6-envdir (env vars from files, not cmdline)
exec s6-setuidgid claude env -i \
    HOME=/data \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    ADDON_VERSION="${ADDON_VERSION}" \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1 \
    CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 \
    s6-envdir "$ENVDIR" \
    python3 -u /opt/bridge/server.py
