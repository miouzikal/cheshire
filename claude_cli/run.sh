#!/bin/bash
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
    # Use jq 'has' + 'tostring' to correctly handle 0, false, and empty strings
    val=$(jq -r "if has(\"${key}\") then .${key} | tostring else \"\" end" "$CONFIG_PATH" 2>/dev/null)
    if [ -n "$val" ]; then
        export "$var"="$val"
        echo "[claude_cli] Set ${var}"
    fi
}

export_if_set "anthropic_api_key" "ANTHROPIC_API_KEY"
export_if_set "anthropic_base_url" "ANTHROPIC_BASE_URL"
export_if_set "anthropic_model" "ANTHROPIC_MODEL"
export_if_set "anthropic_custom_headers" "ANTHROPIC_CUSTOM_HEADERS"
export_if_set "max_output_tokens" "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
export_if_set "max_thinking_tokens" "MAX_THINKING_TOKENS"

# Handle disable_telemetry toggle (already set to 1 in Dockerfile,
# but user can override to false)
telemetry_disabled=$(jq -r '.disable_telemetry // true' "$CONFIG_PATH" 2>/dev/null)
if [ "$telemetry_disabled" = "false" ]; then
    unset CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC
    unset DISABLE_TELEMETRY
    echo "[claude_cli] Telemetry enabled by user configuration"
fi

# ----------------------------------------------------------------------------
# Configure and start SSH daemon (key-only authentication)
# ----------------------------------------------------------------------------
setup_ssh() {
    local ssh_dir="/root/.ssh"
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
PermitRootLogin prohibit-password
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM no
AuthorizedKeysFile ${auth_keys}
PrintMotd yes
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server
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
echo "[claude_cli] Claude Code CLI version: $(claude --version 2>/dev/null || echo 'not found')"
echo "[claude_cli] Bridge server starting on port 8099"

# ----------------------------------------------------------------------------
# Start the Python bridge server
# -u: unbuffered stdout/stderr for real-time log output
# ----------------------------------------------------------------------------
exec python3 -u /opt/bridge/server.py
