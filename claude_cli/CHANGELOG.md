# Changelog

All notable changes to the Claude CLI addon will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-03-14

### Changed

- **Replaced `SYS_ADMIN` with `AUDIT_WRITE`** — `SYS_ADMIN` was only needed for the devpts mount hack. The real SSH fix is `CAP_AUDIT_WRITE` (Debian's OpenSSH calls `fatal()` without it). `AUDIT_WRITE` is a narrow, low-risk capability (only allows writing audit log entries). HA security rating: 5/6.
- **AppArmor profile rewritten** — removed 2 capabilities (`sys_admin`, `sys_chroot`), tightened `/run/**` and `/etc/ssh/**` to specific paths, added explicit deny rules for critical system files (`/etc/passwd`, `/etc/shadow`, `/etc/resolv.conf`, etc.).
- **sshd config hardened** — removed deprecated `ChallengeResponseAuthentication`, added explicit `PubkeyAuthentication yes`, algorithm restrictions (curve25519/chacha20-poly1305/ed25519), sftp disabled, log level set to `INFO` (was `DEBUG3`).
- **Error handling overhauled** — replaced all silent `2>/dev/null || true` patterns with proper JSON validation, logged errors, and explicit existence checks.
- **Authorized keys written atomically** — uses mktemp + mv to prevent partial reads during sshd reload. Null/empty values filtered from the array.
- **Shared secret written atomically** — uses mktemp + mv to prevent TOCTOU race conditions.
- **Health endpoint checks sshd** — unauthenticated `/health` returns 503 if sshd is dead (only when SSH keys are configured), triggering HA watchdog restart. Authenticated responses include `"sshd": "running"/"dead"`.
- **Envdir locked down** — directory mode 0500 (read+execute), files mode 0400 (read-only) after writing. Prevents runtime modification of secrets by the `claude` user.
- **Input validation hardened** — session IDs validated as UUID format, model names validated against regex, log level validated against allowlist, jq injection prevented via `--arg`.
- **Rate limiter memory leak fixed** — stale IP entries now properly cleaned from the sliding window dict.
- **Dead code removed** — unused imports (`os`, `stat`, `tempfile`, `secrets`) and dead `generate_shared_secret()` function removed from security module. Dead `LOG_LEVEL` env var code path removed from server startup.

### Removed

- devpts mount hack (root cause was OpenSSH audit, not PTY allocation).
- TCP wrappers workaround (`echo "sshd: ALL" > /etc/hosts.allow`).
- Debug logging artifacts (`LogLevel DEBUG3`, `-E /tmp/sshd.log`).
- Stale `/opt/claude/**` AppArmor rules.
- Dead code in `security.py` (unused imports, unused `generate_shared_secret()` function).

## [0.2.2] - 2026-03-14

### Fixed

- **SSH PTY allocation**: added `SYS_ADMIN` Linux capability, AppArmor `mount` rules, and bind-mount of `/dev/pts/ptmx` over `/dev/ptmx` — the HA Supervisor's original devpts has `ptmxmode=000` which blocks sshd from allocating PTYs even after mounting a new devpts instance.
- **Silent PTY failure logging**: devpts mount/chmod errors now logged to stdout instead of being suppressed by `2>/dev/null`.

## [0.2.0] - 2026-03-14

### Fixed

- **SSH authentication**: unlocked `claude` user account (`usermod -p '*'`) — OpenSSH rejects key auth for locked accounts when `UsePAM no`.
- **SSH connection reset**: added TCP wrappers allowlist (`sshd: ALL` in `/etc/hosts.allow`) — Debian's libwrap-linked sshd silently refused connections.
- **Login shell validation**: ensured `/bin/bash` is in `/etc/shells` — OpenSSH rejects users with unlisted shells.
- **AppArmor directory permissions**: changed `/data/` subdirectory rules from `r` to `rw` to allow `mkdir`, `chown`, and `chmod` operations during init.
- **Atomic secret creation**: replaced `chmod` with `umask 077` subshell to avoid `CAP_FOWNER` requirement.

### Changed

- Version bumped to 0.2.0 to mark the first fully working release.
- SSH and bridge API verified end-to-end on real hardware.

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
