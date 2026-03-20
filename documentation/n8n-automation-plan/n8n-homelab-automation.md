# n8n Homelab Automation — Setup & Use Cases

> Personal reference guide covering setup and all planned automations.
> Notification channel: **Discord webhooks**

---

## 1. n8n — Self-Hosted Setup on NixOS

### Installation options

**Docker (recommended for NixOS)**
Add to your `docker-compose.nix` or run directly:

```yaml
services:
  n8n:
    image: n8nio/n8n
    restart: always
    ports:
      - "5678:5678"
    environment:
      - N8N_HOST=n8n.local        # or your LAN hostname
      - N8N_PORT=5678
      - WEBHOOK_URL=http://n8n.local:5678/
      - GENERIC_TIMEZONE=Europe/Zurich
    volumes:
      - n8n_data:/home/node/.n8n
```

**NixOS native (via overlay or nixpkgs)**
n8n is available in nixpkgs. Add to your `configuration.nix` or flake:

```nix
services.n8n = {
  enable = true;
  settings = {
    port = 5678;
    generic.timezone = "Europe/Zurich";
  };
};
```

> The NixOS module is relatively new — check nixpkgs version availability.
> Docker is more battle-tested for n8n specifically.

### First-time setup

1. Open `http://localhost:5678`
2. Create owner account (local, no cloud account needed)
3. Go to **Settings → Community Nodes** if you need extra integrations
4. Set up **Discord credentials** (just a webhook URL — no OAuth needed)

---

## 2. Duplicati → Discord Backup Notifications

### Concept

Duplicati fires an HTTP POST to an n8n webhook after every backup job.
n8n checks the status and sends a Discord alert only on failure/warning,
plus a weekly digest regardless of status.

### Duplicati configuration

In each backup job → **Advanced options**, add:

| Option | Value |
|---|---|
| `--send-http-url` | `http://localhost:5678/webhook/duplicati` |
| `--send-http-result-output-format` | `JSON` |
| `--send-http-level` | `Warning,Error` (or `All` for full digest) |
| `--send-http-verb` | `POST` |

### n8n workflow outline

```
[Webhook] POST /webhook/duplicati
  → [IF] status == "Success"
      → do nothing (or log to weekly digest)
  → [ELSE]
      → [Discord Webhook] send embed with:
           - Job name
           - Status (Warning / Error)
           - Error message
           - Timestamp
           - Bytes processed / duration
```

### Discord embed format (example)

```
🔴 Backup Failed — NAS Full Backup
Status:  Error
Reason:  Could not connect to pCloud
Time:    2025-03-15 02:34 UTC
Job:     /home + /data → pCloud
```

### Weekly digest variant

Add a second workflow triggered by **Cron (Sunday 09:00)**:
- Reads last backup status from n8n's static data (stored per job run)
- Posts a summary of all jobs: last run time, status, size
- Green embed if all OK, yellow if any warnings in the week

---

## 3. School Portal — Auth + Course ID Mapping → OwnCloud

### Concept

A Playwright script handles the Microsoft SSO authentication and file
downloading. n8n orchestrates when it runs and handles the OwnCloud
upload via WebDAV. Course ID → folder mapping is maintained in a simple
config file you update once per semester.

### Course config file

Maintain a JSON file at a fixed path, e.g. `~/.config/school-sync/courses.json`:

```json
{
  "courses": [
    {
      "id": "22233",
      "name": "Numerical Computing",
      "owncloud_path": "/school/sem4/numerical-computing/"
    },
    {
      "id": "19847",
      "name": "Algorithms & Data Structures",
      "owncloud_path": "/school/sem4/algorithms/"
    }
  ],
  "base_url": "https://www.icorsi.ch"
}
```

Update this file at the start of each semester (~5 minutes of work).

### Playwright script responsibilities

```
1. Load saved session cookie
2. If session expired → re-authenticate via Microsoft SSO
   (requires stored username/password in env or secrets file)
3. For each course in config:
   a. GET /course/view.php?id={id}
   b. Find all links matching /mod/resource/view.php?id=*
   c. For each resource link:
      - Check if file already downloaded (track seen IDs in a local file)
      - If new: download file, extract real filename from Content-Disposition
      - Upload to OwnCloud via WebDAV to mapped path
4. Output JSON summary: new files found, errors
```

### n8n workflow outline

```
[Cron] Every day at 08:00
  → [Execute Command] run playwright-sync.js
  → [IF] new files found
      → [Discord Webhook] "📚 New files synced" embed
           listing course + filename
  → [IF] errors
      → [Discord Webhook] 🔴 error alert
```

### Notes

- Session cookies for Microsoft SSO typically last several hours to days.
  The script should detect a redirect to login and re-auth automatically.
- Store credentials in a `.env` file, never hardcoded.
- Seen resource IDs can be tracked in a simple `seen_ids.json` file
  alongside the script — no database needed.

---

## 4. Lichess Game Analysis → Discord

### Concept

n8n polls the Lichess public API (no auth needed for public games) daily,
retrieves your recent games, and sends a digest to Discord.
Optionally, once a week, games are sent to Claude API for pattern analysis.

### Lichess API

No API key required for public data. Key endpoint:

```
GET https://lichess.org/api/user/{username}/games
    ?max=20
    &rated=true
    &perfType=blitz,rapid   (filter by time control)
    &opening=true           (include opening name)
    &clocks=false
```

Returns NDJSON (newline-delimited JSON). n8n's HTTP Request node handles this.

### n8n workflow outline

```
[Cron] Daily at 21:00
  → [HTTP Request] GET lichess.org/api/user/{username}/games?max=10
  → [Code node] parse NDJSON, filter to today's games
  → [IF] no games today → stop
  → [Code node] calculate:
       - Win/loss/draw counts
       - Average accuracy (if available)
       - Openings played
       - Biggest blunder (from ?accuracy=true)
  → [Discord Webhook] daily results embed

[Cron] Weekly Sunday 20:00
  → [HTTP Request] GET last 30 games
  → [HTTP Request] POST to Claude API
       prompt: "Analyse these chess games and identify 2-3 recurring
                weaknesses or patterns. Be concise and practical."
  → [Discord Webhook] weekly analysis embed
```

### Discord embed (daily)

```
♟️ Chess Today — 5 games played
Result:    3W / 1D / 1L
Openings:  Sicilian x3, French x2
Accuracy:  87% avg
```

---

## 5. Ski Resort Weather → Discord

### Concept

Morning briefing sent to Discord on weekend days (or every day in season).
You maintain a config list of resorts with coordinates or resort identifiers.
OpenMeteo is recommended because it is free, requires no API key, covers
all of Switzerland and Italy, and has specific mountain/altitude parameters.

### Resort config

Maintain a list in n8n's workflow (or a JSON file) — example structure:

```json
{
  "resorts": [
    {
      "name": "Resort Name A",
      "latitude": 46.123,
      "longitude": 8.456,
      "altitude_m": 1800
    },
    {
      "name": "Resort Name B",
      "latitude": 46.789,
      "longitude": 9.012,
      "altitude_m": 2200
    }
  ]
}
```

To add a resort: find its coordinates on Google Maps (right-click → copy
coordinates), add an entry. Altitude is optional but improves accuracy.

### OpenMeteo API

Free, no key needed:

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude={lat}
    &longitude={lon}
    &daily=snowfall_sum,precipitation_sum,windspeed_10m_max,temperature_2m_max,temperature_2m_min
    &timezone=Europe/Zurich
    &forecast_days=3
```

Key fields for skiing:
- `snowfall_sum` — fresh snow in cm per day
- `windspeed_10m_max` — wind (relevant for lifts)
- `temperature_2m_max/min` — freeze/thaw cycle assessment

### n8n workflow outline

```
[Cron] Saturday + Sunday at 07:30
  → [Loop] for each resort in config
      → [HTTP Request] OpenMeteo API with resort coordinates
      → [Code node] extract today + tomorrow conditions
  → [Code node] build summary comparing all resorts
  → [Discord Webhook] morning briefing embed
```

### Discord embed (example)

```
⛷️ Weekend Snow Report — Sat 15 Mar

Resort Name A (1800m)
  Fresh snow:  8cm today, 3cm tomorrow
  Wind:        22 km/h
  Temp:        -4°C / -1°C

Resort Name B (2200m)
  Fresh snow:  12cm today, 0cm tomorrow
  Wind:        35 km/h ⚠️
  Temp:        -8°C / -3°C
```

### MeteoSwiss alternative

MeteoSwiss has an unofficial JSON API used by their own app, but it is
undocumented and may break. OpenMeteo is more stable and also covers
Italian resorts (Livigno, Cervinia, etc.) with the same API — just change
the coordinates. Recommended to stick with OpenMeteo.

---

## 6. Service Uptime Monitoring → Discord

### Concept

n8n pings each self-hosted service on a schedule. If any fail to respond,
an immediate Discord alert fires. A weekly digest summarises uptime.

### Service config (n8n workflow variables)

Define a list of services to monitor — example structure:

```json
{
  "services": [
    { "name": "OwnCloud",   "url": "http://192.168.x.x:port/status.php" },
    { "name": "Duplicati",  "url": "http://192.168.x.x:8200" },
    { "name": "n8n",        "url": "http://192.168.x.x:5678/healthz" }
  ]
}
```

Add any service that has an HTTP endpoint. For services without a health
endpoint, pinging the root URL (`/`) is sufficient.

### n8n workflow outline

```
[Cron] Every 15 minutes
  → [Loop] for each service
      → [HTTP Request] GET service URL
           timeout: 10s, ignore SSL errors on LAN
      → [IF] status code != 200 OR timeout
          → [Discord Webhook] 🔴 immediate alert
               "Service DOWN: OwnCloud — no response (15:32)"

[Cron] Weekly Sunday 09:00
  → [Run all health checks]
  → [Discord Webhook] weekly status digest
       all green = ✅ embed, any red = ⚠️ embed
```

### Tips

- Use n8n's **static data** to track how long a service has been down,
  so you don't get spammed with alerts every 15 minutes for the same outage.
- Only alert on **state change**: down → send alert; still down → silence;
  recovered → send "✅ OwnCloud is back" message.
- For NixOS disk pressure, add an SSH step: `df -h /` and alert if >85% used.

---

## 7. RSS Feeds (selfh.st + r/selfhosted) → Discord

### Concept

n8n polls RSS feeds periodically, deduplicates already-seen items, filters
by optional keywords, and posts new items to a dedicated Discord channel.

### Feeds to start with

| Source | RSS URL |
|---|---|
| selfh.st/news | `https://selfh.st/news/rss/` |
| r/selfhosted | `https://www.reddit.com/r/selfhosted/.rss` |
| r/NixOS (optional) | `https://www.reddit.com/r/NixOS/.rss` |
| NixOS Discourse (optional) | `https://discourse.nixos.org/latest.rss` |

### n8n workflow outline

```
[Cron] Every 6 hours (or daily)
  → [RSS Feed node] fetch each feed URL
  → [Code node] filter:
       - Skip if item GUID already in seen list
       - Optional: skip if title doesn't match keyword list
         e.g. ["NAS", "backup", "docker", "self-host", "nixos"]
  → [Loop] for each new item
      → [Discord Webhook] post item embed
           title, source, link, short description
  → [Code node] add new GUIDs to seen list
       (stored in n8n static workflow data)
```

### Deduplication

n8n has built-in static data per workflow. Store seen GUIDs as a JSON array.
Cap the array at ~500 entries to avoid unbounded growth.

### Discord embed (example)

```
📰 selfh.st/news
Coolify 4.0 released — new dashboard and improved reverse proxy support
🔗 https://selfh.st/...
```

---

## General Notes

### Secrets management on NixOS

Never hardcode credentials in n8n workflows. Options:
- Use n8n's built-in **Credentials** store (encrypted at rest)
- For the Playwright school script: use a `.env` file with `sops-nix` or
  `agenix` for secret management — consistent with NixOS best practices

### Keeping n8n config in version control

n8n workflows can be exported as JSON. Consider:
- Exporting workflows periodically and committing to your private Gitea
- Using n8n's **Source Control** feature (available in recent versions)
  to sync workflows to a Git repo automatically

### Claude API usage — when it's worth it

Only two workflows above actually benefit from Claude:
1. **Weekly chess analysis** — synthesising patterns across many games
2. **School file classifier** — if you want smarter folder routing than ID matching

Everything else (uptime checks, RSS, weather, backup alerts) is pure
logic — no AI tokens needed.
