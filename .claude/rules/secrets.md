---
description: Secrets and environment-variable handling for all compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Secrets & environment variables

- **Never hardcode** sensitive values (passwords, API keys, tokens, URLs with
  embedded credentials) in compose files.
- Use `${VARIABLE_NAME}` syntax for every secret and user-configurable value.
  Secrets are configured inside Portainer itself — the compose file only
  references them with `${}`.
- When a `.env` file is needed instead, note that `**.env` is already gitignored.
- Use descriptive, purpose-clear names: `DB_PASSWORD`, `SMTP_USER`,
  `NEXTAUTH_SECRET`, `REDIS_PASSWORD`, etc.
- **If you spot a hardcoded secret in an existing compose file, flag it
  immediately** and provide a corrected version using `${VAR}` references.
- Non-sensitive but deployment-varying values (ports, domains, feature flags)
  should also use environment variables when they are likely to differ between
  deployments.

> Canonical rule. The `docker-compose-architect` agent embeds the same policy;
> the `compose-security-auditor` enforces it read-only across the repo.
