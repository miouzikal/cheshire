# Changelog

All notable changes to the Claude CLI addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-14

### Added

- Initial release of the Claude CLI addon for Home Assistant.
- Python HTTP bridge server (aiohttp) on port 8099 with Bearer token authentication.
- Session pool for warm multi-turn conversations via `POST /converse`.
- One-shot structured generation via `POST /task`.
- Health monitoring endpoint at `GET /health` with authentication status.
- Environment inspection via `GET /environment`.
- Hot-reload of CLAUDE.md, settings.json, and MCP configuration via `POST /reload`.
- SSH access (key-only, hardened) for CLI authentication and management.
- Automatic discovery by the Claude CLI custom component.
- Support for model routing: fast (Haiku), default (Sonnet), smart (Opus).
- Custom API endpoint support for local models (Ollama, LM Studio, vLLM).
- Default CLAUDE.md system prompt optimized for French-speaking Quebec household.
- Default permissions deny list restricting dangerous CLI tools.
- Example slash command template in `.claude/commands/`.
- Custom AppArmor security profile.
