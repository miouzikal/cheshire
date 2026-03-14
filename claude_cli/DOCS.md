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
2. SSH into the addon: `ssh root@homeassistant -p 2222`
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
- **`.claude/settings.json`** — Tool permissions (allow/deny lists).
- **`mcp.json`** — MCP server configuration for extending Claude's capabilities.
- **`.claude/commands/`** — Custom slash commands (Markdown files with YAML frontmatter).

After editing, call the **Reload Environment** service from Home Assistant or restart the addon.

## Bridge API

The bridge server runs on port 8099 and exposes these endpoints:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | Optional | Health status, CLI version, auth status, active sessions. |
| `POST` | `/converse` | Required | Multi-turn conversation (uses session pool). |
| `POST` | `/task` | Required | One-shot structured generation. |
| `GET` | `/environment` | Required | Current environment configuration. |
| `POST` | `/reload` | Required | Reload CLAUDE.md, settings, and MCP config from disk. |

Authentication uses Bearer token: `Authorization: Bearer <shared_secret>`

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

## Security

- The bridge API is authenticated with a randomly generated shared secret (64-character hex string).
- SSH access is key-only with hardened configuration (no password, no tunneling, max 3 auth attempts).
- The Claude CLI runs with restricted tool permissions by default (file system access denied).
- A custom AppArmor profile restricts the container's capabilities.
- The shared secret file is stored with mode 0600 (owner-read only).

## Support

Report issues at [github.com/miouzikal/cheshire/issues](https://github.com/miouzikal/cheshire/issues).
