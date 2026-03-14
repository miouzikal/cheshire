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

# Export addon version from config.yaml (single source of truth)
if [ -f /opt/config.yaml ]; then
    ADDON_VERSION=$(grep '^version:' /opt/config.yaml | sed 's/version: *"\{0,1\}\([^"]*\)"\{0,1\}/\1/')
fi
export ADDON_VERSION="${ADDON_VERSION:-unknown}"

# ----------------------------------------------------------------------------
# Initialize default environment files on first run
# ----------------------------------------------------------------------------
if [ ! -f /data/claude_environment/CLAUDE.md ]; then
    echo "[claude_cli] First run — initializing default environment files"
    mkdir -p /data/claude_environment/.claude/commands
    cp -rn /opt/defaults/* /data/claude_environment/ 2>/dev/null || true
    cp -rn /opt/defaults/.claude /data/claude_environment/ 2>/dev/null || true
    echo "[claude_cli] Default environment initialized at /data/claude_environment/"
fi

# ----------------------------------------------------------------------------
# Export addon options as environment variables for Claude Code CLI
# Only sets the variable if the option has a non-empty value.
# ----------------------------------------------------------------------------
export_if_set() {
    local key="$1"
    local var="$2"
    local val
    val=$(jq -r "if has(\"${key}\") then .${key} | tostring else \"\" end" "$CONFIG_PATH" 2>/dev/null)
    if [ -n "$val" ]; then
        echo "${var}=${val}" >> /tmp/bridge_env
        echo "[claude_cli] Set ${var}"
    fi
}

# Create clean env file for the bridge process
: > /tmp/bridge_env
chmod 600 /tmp/bridge_env

export_if_set "anthropic_api_key" "ANTHROPIC_API_KEY"
export_if_set "anthropic_base_url" "ANTHROPIC_BASE_URL"
export_if_set "anthropic_model" "ANTHROPIC_MODEL"
export_if_set "anthropic_custom_headers" "ANTHROPIC_CUSTOM_HEADERS"
export_if_set "max_output_tokens" "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
export_if_set "max_thinking_tokens" "MAX_THINKING_TOKENS"

TELEMETRY_OPTS="DISABLE_TELEMETRY=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"
telemetry_disabled=$(jq -r '.disable_telemetry // true' "$CONFIG_PATH" 2>/dev/null)
if [ "$telemetry_disabled" = "false" ]; then
    TELEMETRY_OPTS=""
    echo "[claude_cli] Telemetry enabled by user configuration"
fi

# ----------------------------------------------------------------------------
# Configure and start SSH daemon (key-only authentication)
# ----------------------------------------------------------------------------
setup_ssh() {
    # Mount a fresh devpts instance so sshd can allocate PTYs
    # (HA Supervisor mounts /dev read-only with ptmxmode=000)
    if mount -t devpts devpts /dev/pts -o newinstance,ptmxmode=0666,mode=620,gid=5 2>/dev/null; then
        echo "[claude_cli] Mounted fresh devpts for PTY allocation"
    elif chmod 666 /dev/pts/ptmx 2>/dev/null; then
        echo "[claude_cli] Fixed /dev/pts/ptmx permissions (fallback)"
    fi

    local ssh_dir="/home/claude/.ssh"
    local auth_keys="${ssh_dir}/authorized_keys"
    local sshd_config="/etc/ssh/sshd_config"

    if [ ! -x /usr/sbin/sshd ]; then
        echo "[claude_cli] WARNING: sshd not found — SSH access unavailable"
        return 1
    fi

    mkdir -p "$ssh_dir"
    chmod 700 "$ssh_dir"

    # Write authorized keys from addon config
    jq -r '.ssh_authorized_keys[]? // empty' "$CONFIG_PATH" > "$auth_keys" 2>/dev/null
    chmod 600 "$auth_keys"
    chown -R claude:claude "$ssh_dir"

    local key_count
    key_count=$(wc -l < "$auth_keys" | tr -d ' ')

    if [ "$key_count" -eq 0 ]; then
        echo "[claude_cli] WARNING: No SSH authorized keys configured — SSH access disabled"
        return 1
    fi

    # Generate host keys if missing (persistent across restarts via /data)
    local host_key_dir="/data/.ssh_host_keys"
    mkdir -p "$host_key_dir"
    for key_type in rsa ed25519; do
        if [ ! -f "${host_key_dir}/ssh_host_${key_type}_key" ]; then
            if ! ssh-keygen -t "$key_type" -f "${host_key_dir}/ssh_host_${key_type}_key" -N "" -q; then
                echo "[claude_cli] ERROR: Failed to generate ${key_type} host key"
                return 1
            fi
        fi
    done

    # Configure sshd: key-only, hardened, no password
    cat > "$sshd_config" <<SSHD_EOF
Port 22
HostKey ${host_key_dir}/ssh_host_rsa_key
HostKey ${host_key_dir}/ssh_host_ed25519_key
PermitRootLogin no
AllowUsers claude
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM no
AuthorizedKeysFile ${auth_keys}
PrintMotd yes
AcceptEnv LANG LC_*
# Hardening
MaxAuthTries 3
MaxSessions 3
LoginGraceTime 30
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
ClientAliveInterval 300
ClientAliveCountMax 2
SSHD_EOF

    # Start sshd in background
    /usr/sbin/sshd
    echo "[claude_cli] SSH daemon started with ${key_count} authorized key(s)"
    return 0
}

setup_ssh || true

# ----------------------------------------------------------------------------
# Log startup information
# ----------------------------------------------------------------------------
echo "[claude_cli] Addon version: ${ADDON_VERSION}"
echo "[claude_cli] Claude Code CLI: $(claude --version 2>/dev/null || echo 'not found')"
echo "[claude_cli] Bridge server starting on port 8099"

# ----------------------------------------------------------------------------
# Start the Python bridge server
# -u: unbuffered stdout/stderr for real-time log output
# ----------------------------------------------------------------------------

# Generate shared secret as root (claude user can't write to /data/)
if [ ! -f /data/shared_secret ] || [ ! -s /data/shared_secret ]; then
    python3 -c "import secrets; print(secrets.token_hex(32), end='')" > /data/shared_secret
    chmod 600 /data/shared_secret
    echo "[claude_cli] Generated new shared secret"
fi

# Set up claude user's data directory and permissions
mkdir -p /data/claude_environment/.claude/commands
chown -R claude:claude /data/claude_environment
chown claude:claude /data/shared_secret
chmod 400 /data/shared_secret
# options.json must be readable by the bridge (but not writable)
chmod 644 /data/options.json 2>/dev/null || true

# Start bridge as claude user with only necessary env vars
exec s6-setuidgid claude env -i \
    HOME=/data \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    ADDON_VERSION="${ADDON_VERSION}" \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1 \
    CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 \
    $TELEMETRY_OPTS \
    $(cat /tmp/bridge_env 2>/dev/null | tr '\n' ' ') \
    python3 -u /opt/bridge/server.py
