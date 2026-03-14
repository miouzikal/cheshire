# Claude CLI Addon

Claude-powered voice assistant and AI automation for Home Assistant.

Runs the Claude Code CLI inside an isolated container with an HTTP bridge API for native integration with Home Assistant conversation pipelines and AI task automations. The bridge runs as an unprivileged `claude` user with AppArmor confinement and rate limiting.

**Stage: experimental** — expect breaking changes between releases.

See [DOCS.md](DOCS.md) for full documentation.
