# Actual Budget MCP Server Setup Guide

## What this does

Connects Claude Code to your Actual Budget instance so you can ask things like:
- "Export all transactions from February as CSV"
- "Compare grocery spending this month vs last month"
- "List all accounts and balances"
- "Show transactions over 100 CHF in the last 30 days"

Uses the open-source [`actual-mcp`](https://github.com/s-stefanov/actual-mcp) npm package (by s-stefanov).

## How it works

```
Claude Code  →  MCP Server (runs locally via npx)  →  Actual Server (via Cloudflare Tunnel)
                    uses: @actual-app/api (Node.js)
                    auth: ACTUAL_PASSWORD + ACTUAL_BUDGET_SYNC_ID
```

- The MCP server runs **locally on your machine** as a stdio process spawned by Claude Code
- `npx -y actual-mcp` downloads and runs it on-the-fly (cached in npm cache)
- Connects to Actual Server through the **Cloudflare Tunnel URL** — works from anywhere
- No extra Docker container needed — your existing Actual Server is all you need
- **Cost: Free** (open source, runs locally, included in Claude Pro plan)

### Why CLI per machine and not claude.ai web connectors?

Claude.ai connectors (`claude.ai/settings/connectors`) only support **OAuth 2.1 or authless** servers.
`actual-mcp` uses **bearer token auth**, which the web UI has no field for.
The CLI approach (`--scope user`) is the simplest working solution. If `actual-mcp` adds OAuth
support in the future, we can switch to web connectors for cross-machine sync.

---

## New Machine Setup

Run these commands on **each new machine** where you want Actual Budget access in Claude Code.
Total time: ~2 minutes.

### Prerequisites

1. **Claude Code CLI** installed and logged in
2. **Node.js v18+** installed (verify: `npx --version`)

### Credentials you need

Get these before running the commands:

| Value | Where to find it |
|-------|-----------------|
| `ACTUAL_SERVER_URL` | Your Cloudflare Tunnel URL (e.g., `https://actual.yourdomain.com`) |
| `ACTUAL_PASSWORD` | Your Actual Server password |
| `ACTUAL_BUDGET_SYNC_ID` | Actual Budget UI → Settings → Advanced → Sync ID (one per budget) |
| `ACTUAL_BUDGET_ENCRYPTION_PASSWORD` | Your E2E encryption password |

### Step 1: Register budget-principale

```bash
claude mcp add budget-principale \
  --scope user \
  --transport stdio \
  --env ACTUAL_SERVER_URL="https://actual.yourdomain.com" \
  --env ACTUAL_PASSWORD="your-server-password" \
  --env ACTUAL_BUDGET_SYNC_ID="your-principale-sync-id" \
  --env ACTUAL_BUDGET_ENCRYPTION_PASSWORD="your-encryption-password" \
  -- npx -y actual-mcp --enable-write
```

### Step 2: Register budget-euro

```bash
claude mcp add budget-euro \
  --scope user \
  --transport stdio \
  --env ACTUAL_SERVER_URL="https://actual.yourdomain.com" \
  --env ACTUAL_PASSWORD="your-server-password" \
  --env ACTUAL_BUDGET_SYNC_ID="your-euro-sync-id" \
  --env ACTUAL_BUDGET_ENCRYPTION_PASSWORD="your-encryption-password" \
  -- npx -y actual-mcp --enable-write
```

> Both budgets share the same server URL and password — only the sync ID differs.
> `--enable-write` allows creating/updating transactions. Remove it for read-only access.

### Step 3: Verify

```bash
claude
```

Type `/mcp` — both `budget-principale` and `budget-euro` should show as connected.

Test with: *"List all my accounts and their balances"*

### Where does it live?

- **Config**: `~/.claude.json` (user scope = available from any directory)
- **Server code**: Not stored permanently — `npx` fetches it on-the-fly
- **No repo clone needed** — works from any directory on the machine

---

## Adding a new budget

Copy-paste, change the name and sync ID:

```bash
claude mcp add budget-NEW-NAME \
  --scope user \
  --transport stdio \
  --env ACTUAL_SERVER_URL="https://actual.yourdomain.com" \
  --env ACTUAL_PASSWORD="your-server-password" \
  --env ACTUAL_BUDGET_SYNC_ID="the-new-budget-sync-id" \
  --env ACTUAL_BUDGET_ENCRYPTION_PASSWORD="your-encryption-password" \
  -- npx -y actual-mcp --enable-write
```

- **No encryption on this budget?** Omit the `ACTUAL_BUDGET_ENCRYPTION_PASSWORD` line
- **Read-only access?** Remove `--enable-write`

---

## Managing budgets

| Action | Command |
|--------|---------|
| List all registered | `claude mcp list` |
| Remove one | `claude mcp remove budget-NAME --scope user` |
| Check connection status | `/mcp` inside a Claude Code session |

Each budget is fully independent — different encryption settings, different read/write permissions, no conflicts.

---

## Available MCP tools

| Tool | Description |
|------|-------------|
| `get-accounts` | List all accounts with balances |
| `get-transactions` | Filter by account, date, amount, category, payee |
| `create-transaction` | Add transaction with optional category, payee, notes |
| `update-transaction` | Modify existing transaction |
| `balance-history` | Account balance over time |
| `spending-by-category` | Spending breakdowns by category |
| `monthly-summary` | Income/expenses/savings report |
| `get-grouped-categories` | List all categories and groups |
| `create/update/delete-category` | Manage categories |
| `get-payees` | List all payees |
| `create/update/delete-payee` | Manage payees |
| `get-rules` | List all rules |
| `create/update/delete-rule` | Manage rules |

---

## Upgrading

`npx -y actual-mcp` always fetches the latest version. To pin a specific version:

```
-- npx -y actual-mcp@1.11.1 --enable-write
```

If you outgrow the base package, consider [giorgiobrullo's fork](https://github.com/giorgiobrullo/actual-mcp) which adds batch operations, budget management, and scheduled transactions — same setup pattern, just change the package name.

---

## Verification prompts

After setup, test these in Claude Code:
1. "List all my Actual Budget accounts" — confirms connection works
2. "Show my transactions from last month" — confirms data access
3. "Export February transactions as CSV" — confirms export workflow
4. "Compare grocery spending this month vs last month" — confirms analytical capability
