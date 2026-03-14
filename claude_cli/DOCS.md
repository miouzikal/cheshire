# Claude CLI Addon

The Claude CLI addon runs the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) inside a Home Assistant addon container and exposes it through a local HTTP bridge API. The companion [Claude CLI integration](https://github.com/miouzikal/cheshire/tree/main/custom_components/claude_cli) connects to this bridge to provide native conversation and AI task capabilities in Home Assistant.

## How it works

The addon maintains a pool of warm Claude CLI sessions for low-latency multi-turn conversations (voice, text) and supports one-shot queries for structured AI task generation. All communication happens over a local HTTP API on port 8099, authenticated with a shared secret.

```
Voice Pipeline / Automation
        │
        ▼
  HA Integration ──HTTP──▶ Bridge Server ──SDK──▶ Claude CLI ──API──▶ Anthropic
  (custom_component)        (port 8099)           (subprocess)
```

The bridge server runs as an unprivileged `claude` user (not root). Environment variables are injected via s6-envdir (file-based, no command-line leaks). The shared secret is generated atomically at startup with correct ownership.

## Prerequisites

- A Claude subscription (Pro, Team, or Max) **or** an Anthropic API key.
- Home Assistant OS or Supervised installation.

## Installation

1. Add this repository to your Home Assistant addon store:
   - Go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
   - Enter: `https://github.com/miouzikal/cheshire`
2. Install the **Claude CLI** addon.
3. Start the addon.
4. Note the shared secret from the addon log, or SSH in and run: `cat /data/shared_secret`

## Authentication

The Claude CLI must be authenticated before use. There are two methods:

### Method 1: Setup Token (recommended for Claude Max)

1. Add your SSH public key to the addon configuration.
2. SSH into the addon: `ssh claude@homeassistant -p 2222`
3. Run: `claude setup-token`
4. Follow the prompts to authenticate.

### Method 2: API Key

1. Go to the addon **Configuration** tab.
2. Enter your Anthropic API key in the **Anthropic API Key** field.
3. Restart the addon.

## Configuration

### SSH Authorized Keys

Public SSH keys allowed to connect to the addon container. Used for CLI authentication (`claude setup-token`) and management. One key per line, in standard OpenSSH format.

### Model Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Fast Model | `claude-haiku-4-5` | Used for quick, low-latency responses (light switches, simple questions). |
| Default Model | `claude-sonnet-4-6` | Used for most conversations and general tasks. |
| Smart Model | `claude-opus-4-6` | Used for complex reasoning, planning, and multi-step tasks. |

### API Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Anthropic API Key | *(empty)* | API key for Anthropic's Claude API. Leave empty if using `claude setup-token`. |
| Custom API Base URL | *(empty)* | Override the API endpoint for local models (Ollama, LM Studio, vLLM). |
| Custom Model Override | *(empty)* | Override the model name sent to the API. |
| Custom API Headers | *(empty)* | Additional HTTP headers for API requests. |

### Generation Limits

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Max Output Tokens | 32,000 | 1,000–64,000 | Maximum tokens in Claude's response. |
| Max Thinking Tokens | 0 | 0–128,000 | Token budget for extended thinking. Set to 0 to disable. |

### Behavior

| Option | Default | Description |
|--------|---------|-------------|
| Disable Telemetry | `true` | Disable all non-essential network traffic from the CLI. |
| Request Timeout | 120s | Maximum time to wait for a CLI response (10–600s). |
| Max Tool Iterations | 10 | Maximum tool call round-trips per request (1–50). |
| Log Level | `info` | Verbosity: `debug`, `info`, `warning`, `error`. |

## Customizing the environment

The addon's working directory is `/data/claude_environment/`. You can customize Claude's behavior by editing these files via SSH:

- **`CLAUDE.md`** — System prompt and instructions. This is loaded as context for every conversation.
- **`.claude/settings.json`** — Tool permissions (allow/deny lists). The bridge uses `allowEdits` permission mode, which respects the deny list in settings.json.
- **`mcp.json`** — MCP server configuration for extending Claude's capabilities.
- **`.claude/commands/`** — Custom slash commands (Markdown files with YAML frontmatter).

After editing, call the **Reload Environment** service from Home Assistant or restart the addon.

## Bridge API

The bridge server runs on port 8099 and exposes these endpoints:

| Method | Path | Auth | Rate Limited | Description |
|--------|------|------|-------------|-------------|
| `GET` | `/health` | Optional | No | Unauthenticated: `{"status": "ok"}`. Authenticated: full health with CLI version, auth status, active sessions, configured models. |
| `POST` | `/converse` | Required | Yes | Multi-turn conversation (uses session pool). |
| `POST` | `/task` | Required | Yes | One-shot structured generation. |
| `GET` | `/environment` | Required | No | Current environment configuration. |
| `POST` | `/reload` | Required | No | Reload CLAUDE.md, settings, and MCP config from disk. |

Authentication uses Bearer token: `Authorization: Bearer <shared_secret>`

### Rate Limiting

`/converse` and `/task` are rate-limited to **60 requests per minute per IP**. `/health` is exempt (used by the HA watchdog). Exceeding the limit returns HTTP 429 with a `Retry-After` header.

### Input Validation

| Field | Max Size |
|-------|----------|
| `system_prompt` | 10 KB |
| `message_text` | 100 KB |
| `task_prompt` | 100 KB |
| Request body | 512 KB |

## Security

- **Unprivileged execution**: The bridge server runs as the `claude` user (not root), started via `s6-setuidgid`.
- **Secret management**: The shared secret (64-character hex) is generated atomically (mktemp + mv) with owner-read-only permissions (mode 0400), owned by `claude:claude`. Environment variables are injected via s6-envdir (file-based), so secrets never appear in process command lines.
- **SSH access**: Key-only authentication, runs as `claude` user (`PermitRootLogin no`, `AllowUsers claude`). PTY allocation uses a fresh devpts mount. Hardened config: no password auth, no tunneling, no forwarding, max 3 auth attempts, 30s login grace time.
- **AppArmor**: Custom profile with deny rules for `/proc/sys/kernel/core_pattern`, `/sys/**`, `/boot/**`, and `/root/.bash_history`.
- **Rate limiting**: 60 requests/minute per IP on `/converse` and `/task` endpoints.
- **Permission mode**: `allowEdits` — the Claude CLI respects the deny list defined in `.claude/settings.json`.
- **Dependencies**: Only `claude-code-sdk` and `aiohttp` (no PyJWT, no cryptography library).

## SSH

SSH runs on port 22 inside the container (mapped to host port 2222 by default). Connections authenticate as the `claude` user with key-only auth.

```
ssh claude@homeassistant -p 2222
```

Requirements:
- At least one SSH public key configured in the addon options.
- Key format: `ssh-ed25519 AAAA...` or `ssh-rsa AAAA...`.

Host keys are persisted at `/data/.ssh_host_keys/` across restarts.

## Troubleshooting

### "Claude CLI not authenticated" repair issue

SSH into the addon and run `claude setup-token` to authenticate, or add an API key in the addon configuration.

### "Claude CLI addon unreachable" repair issue

Verify the addon is running. Check the addon logs for errors. Ensure the bridge URL in the integration configuration is correct.

### Slow responses

- Try reducing **Max Thinking Tokens** to 0.
- Use the **fast** model tier for simple tasks.
- Check your network connection to the Anthropic API.

### SSH connection refused

- Ensure you have added your SSH public key to the addon configuration.
- Verify the SSH port mapping (default: 2222 on the host).
- Check that the key format is correct (`ssh-ed25519 AAAA...` or `ssh-rsa AAAA...`).

## Support

Report issues at [github.com/miouzikal/cheshire/issues](https://github.com/miouzikal/cheshire/issues).
