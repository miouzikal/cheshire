# Changelog

All notable changes to the Claude CLI addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.22] - 2026-03-14

### Changed

- **Stage set to `experimental`** — reflects the current maturity of the addon.
- **Bridge runs as unprivileged `claude` user** — the server process is started via `s6-setuidgid claude` instead of running as root.
- **SSH runs as `claude` user** — `PermitRootLogin no` and `AllowUsers claude` enforced in sshd config.
- **Environment variables injected via s6-envdir** — secrets are stored as files under `/tmp/bridge_envdir/` (mode 0400, owned by `claude`), never passed on the command line.
- **Atomic shared secret generation** — uses mktemp + mv to prevent partial reads; file owned by `claude:claude` with mode 0400.
- **Removed PyJWT and cryptography dependencies** — only `claude-code-sdk` and `aiohttp` remain.

### Added

- **Rate limiting** — 60 requests per minute per IP on `/converse` and `/task` endpoints (sliding window). Returns HTTP 429 with `Retry-After` header when exceeded.
- **Input validation** — `system_prompt` capped at 10 KB, `message_text` and `task_prompt` capped at 100 KB, request body capped at 512 KB.
- **Tiered `/health` responses** — unauthenticated requests (watchdog) get `{"status": "ok"}`; authenticated requests get full health details (CLI version, auth status, sessions, models).
- **AppArmor deny rules** — explicit denials for `/proc/sys/kernel/core_pattern`, `/sys/**`, `/boot/**`, and `/root/.bash_history`.
- **PTY allocation via devpts mount** — mounts a fresh devpts instance so sshd can allocate PTYs in the HA Supervisor environment.
- **Permission mode `allowEdits`** — respects the deny list in `.claude/settings.json` for tool permissions.

### Security

- Bridge process environment is scrubbed with `env -i` before re-populating only required variables.
- Envdir directory permissions set to 0500 (read+execute for owner only).
- `/data/options.json` set to root:claude 0640 (readable by bridge, not world-readable).
- SSH hardening: max 3 auth attempts, 30s login grace, no TCP/agent/X11 forwarding, no tunneling, 5-minute client alive interval.

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
