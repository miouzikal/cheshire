# Cheshire

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Addon-blue.svg)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Claude-powered voice assistant and AI automation for Home Assistant.**

Cheshire brings [Claude](https://claude.ai) into Home Assistant as a native conversation agent and AI task processor. Talk to Claude through your voice pipelines, automate with AI-generated data, and control your smart home — all running locally through a dedicated addon.

## Components

### Claude CLI Addon (`claude_cli/`)

A Home Assistant addon that runs the Claude Code CLI inside an isolated Docker container with:

- **HTTP bridge server** on port 8099 for low-latency conversation and task APIs.
- **Session pool** with warm CLI subprocesses for sub-second multi-turn responses.
- **Model routing** — fast (Haiku), default (Sonnet), smart (Opus) tiers.
- **Local model support** — connect to Ollama, LM Studio, or any OpenAI-compatible endpoint.
- **SSH access** for CLI authentication and environment management.
- **Customizable environment** — CLAUDE.md system prompt, MCP servers, tool permissions, slash commands.

### Claude CLI Integration (`custom_components/claude_cli/`)

A Home Assistant custom component that consumes the addon's bridge API and registers as:

- **Conversation agent** — use Claude in voice pipelines, the chat UI, or automations.
- **AI Task entity** — structured data generation for automations and scripts.
- **Sensors** — authentication status, active model, CLI version, session count.
- **Binary sensor** — addon connectivity health.
- **Repair issues** — actionable alerts when the addon is unreachable or CLI is unauthenticated.

## Quick start

### 1. Install the addon

Add this repository to your Home Assistant addon store:

```
https://github.com/miouzikal/cheshire
```

Install and start the **Claude CLI** addon.

### 2. Authenticate Claude

SSH into the addon and run:

```bash
ssh claude@homeassistant -p 2222
claude setup-token
```

Or add an Anthropic API key in the addon configuration.

### 3. Install the integration

Copy `custom_components/claude_cli/` to your Home Assistant `config/custom_components/` directory and restart HA. The integration will auto-discover the addon, or you can add it manually.

### 4. Set up voice

Go to **Settings → Voice assistants** and select the Claude CLI conversation agent for your voice pipeline.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Home Assistant                         │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Voice        │  │ Automations  │  │ Chat UI      │  │
│  │ Pipeline     │  │              │  │              │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │           │
│         ▼                 ▼                 ▼           │
│  ┌─────────────────────────────────────────────────┐    │
│  │         Claude CLI Integration                   │    │
│  │  conversation.process  │  ai_task.generate_data  │    │
│  └────────────────────────┼─────────────────────────┘    │
│                           │ HTTP (port 8099)             │
└───────────────────────────┼──────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────┐
│  Claude CLI Addon         ▼                              │
│  ┌─────────────────────────────────────────────────┐     │
│  │         Bridge Server (aiohttp)                  │     │
│  │  /converse (session pool)  │  /task (one-shot)   │     │
│  └────────────────────────────┼─────────────────────┘     │
│                               │ claude-code-sdk           │
│  ┌────────────────────────────┼─────────────────────┐     │
│  │         Claude Code CLI (subprocess)              │     │
│  │  Persistent sessions  │  MCP servers  │  Tools    │     │
│  └───────────────────────┼───────────────────────────┘     │
│                          │ HTTPS                          │
└──────────────────────────┼────────────────────────────────┘
                           ▼
                    Anthropic API
```

## Configuration

See the addon's [DOCS.md](claude_cli/DOCS.md) for full configuration reference.

## Development

This project uses:

- **Python 3.11+** for the bridge server and HA integration.
- **claude-code-sdk 0.0.25** for Claude CLI communication.
- **aiohttp** for the HTTP bridge server.
- **Home Assistant 2025.1+** with conversation and ai_task platforms.

## License

MIT License. See [LICENSE](LICENSE) for details.
