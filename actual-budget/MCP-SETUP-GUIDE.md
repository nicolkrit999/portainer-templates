# Actual Budget MCP Server Setup Plan

## Context

You want Claude Code to interact directly with your Actual Budget instance for everyday tasks (exporting transactions as CSV, comparisons, etc.). Your NAS already runs Actual Server (port 5006) and the HTTP API wrapper (port 5007). An existing community MCP server already exists — no need to build one from scratch.

---

## Answers to Your Questions

### 1. Do I need the repo cloned? Can I use it from anywhere?

**Yes, you can use it from anywhere.** MCP servers in Claude Code have three scopes:

| Scope | Where it lives | Available from |
|-------|---------------|----------------|
| **User** (`--scope user`) | `~/.claude.json` | **Any directory, any project** |
| **Project** (`--scope project`) | `.mcp.json` in repo root | Only inside that repo |
| **Local** (default) | `~/.claude.json` keyed by project | Only inside that project |

**For your use case: use `--scope user`.** This registers the MCP server globally in `~/.claude.json`, making it available from any directory — no repo clone needed. You could be in your home folder, a random project, or this repo, and the Actual Budget tools will be there.

### 2. How does authentication work?

**The MCP server connects directly to your Actual Server — NOT through the HTTP API wrapper and NOT through Cloudflare.** Here's the auth chain:

```
Claude Code  →  MCP Server (runs locally via npx)  →  Actual Server (port 5006)
                    uses: @actual-app/api (Node.js)
                    auth: ACTUAL_PASSWORD (your server password)
                    + ACTUAL_BUDGET_SYNC_ID (your budget ID)
```

- The MCP server uses the **official `@actual-app/api` Node.js package** to talk directly to your Actual Server
- You authenticate with your **Actual Server password** (`ACTUAL_PASSWORD`)
- You do NOT need the `jhonderson/actual-http-api` for this — the MCP server bypasses it entirely
- Your Actual Server is exposed via Cloudflare Tunnel — the MCP server connects through that URL
- This means it works from anywhere (LAN or remote) with zero config changes

### 3. Cost

**Free.** The MCP server (`actual-mcp`) is open source. It runs locally as a stdio process spawned by Claude Code. No extra API calls, no hosted services. Your only cost is your existing Claude Pro subscription and the electricity for your NAS (which you said to exclude).

---

## Recommended Tool: `actual-mcp` by s-stefanov

**Why this one:**
- Open source, actively maintained
- Published on npm as `actual-mcp` — installable via `npx` (no clone needed)
- Uses the official `@actual-app/api` directly (not the HTTP wrapper)
- Supports read AND write operations
- Has a fork by `giorgiobrullo` with extra features (batch ops, budget management, scheduled transactions) if you want more later
- Works with Claude Code natively via stdio transport

**What it can do:**
- `get-transactions` — filter by account, date, amount, category, payee
- `create-transaction` — add transactions with category, payee, notes
- `update-transaction` — modify existing transactions
- `get-accounts` — list all accounts and balances
- Spending breakdowns by category over date ranges
- Monthly income/expenses/savings reports
- Account balance history over time

---

## Step-by-Step Setup Plan

### Step 1: Gather your Actual Budget credentials

You need these values for **each budget**:
- **ACTUAL_SERVER_URL** — Your Actual Server Cloudflare URL (e.g., `https://actual.yourdomain.com`) — always use the Cloudflare URL so it works from anywhere, even on LAN
- **ACTUAL_PASSWORD** — Your Actual Server password
- **ACTUAL_BUDGET_SYNC_ID** — Each budget's sync ID (found in Actual Budget UI → Settings → Advanced → Sync ID). You need one per budget.
- **ACTUAL_BUDGET_ENCRYPTION_PASSWORD** — Your encryption password (required, since you use end-to-end encryption)

### Step 2: Ensure Node.js/npx is available

The MCP server runs via `npx`. Verify:
```bash
npx --version
```
If not installed, install Node.js (v18+).

### Step 3: Register TWO MCP servers globally in Claude Code

**Main budget** (replace placeholders with your real values):

```bash
claude mcp add budget-principale \
  --scope user \
  --transport stdio \
  --env ACTUAL_SERVER_URL="https://actual.yourdomain.com" \
  --env ACTUAL_PASSWORD="your-server-password" \
  --env ACTUAL_BUDGET_SYNC_ID="your-main-budget-sync-id" \
  --env ACTUAL_BUDGET_ENCRYPTION_PASSWORD="your-encryption-password" \
  -- npx -y actual-mcp --enable-write
```

**Secondary budget:**

```bash
claude mcp add budget-euro \
  --scope user \
  --transport stdio \
  --env ACTUAL_SERVER_URL="https://actual.yourdomain.com" \
  --env ACTUAL_PASSWORD="your-server-password" \
  --env ACTUAL_BUDGET_SYNC_ID="your-secondary-budget-sync-id" \
  --env ACTUAL_BUDGET_ENCRYPTION_PASSWORD="your-encryption-password" \
  -- npx -y actual-mcp --enable-write
```

> Note: `--enable-write` allows creating/updating transactions. Remove it if you want read-only access for a budget.
> Both budgets share the same server URL and password — only the sync ID differs.

### Step 4: Verify it works

Start a new Claude Code session from any directory:
```bash
claude
```

Then type `/mcp` to check the server status. You should see both `budget-principale` and `budget-euro` listed as connected.

Try a test prompt:
> "List all my accounts and their balances"

### Step 5: Where does it live?

- **The MCP config** lives in `~/.claude.json` (user scope = global)
- **The MCP server code** is NOT stored anywhere permanently — `npx -y actual-mcp` downloads and runs it on-the-fly each time Claude Code starts a session, caching it in the npm cache
- **No repo clone needed**, no files in your project folder
- **Works from any directory** on any machine where you have Claude Code + Node.js installed

---

## Future-Proofing Notes

- If `actual-mcp` adds new tools (which it will as Actual Budget evolves), you get them automatically since `npx -y` always fetches the latest version
- If you want to pin a version: `npx -y actual-mcp@1.2.3`
- If you outgrow the base package, switch to `giorgiobrullo`'s fork which adds batch operations, budget management, and scheduled transactions — same setup, just change the package name
- Both MCP servers run independently — you can query both budgets in the same conversation

### Adding more budgets in the future

It's a single copy-paste command. Just change the name and sync ID:

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

- **No encryption?** Simply omit the `ACTUAL_BUDGET_ENCRYPTION_PASSWORD` line
- **Read-only?** Remove `--enable-write`
- **Remove a budget?** `claude mcp remove budget-NAME --scope user`
- **List all registered budgets?** `claude mcp list`

Each budget is fully independent — different encryption settings, different read/write permissions, no conflict between them

---

## Verification

After setup, test these prompts in Claude Code:
1. "List all my Actual Budget accounts" — confirms connection works
2. "Show my transactions from last month" — confirms data access
3. "Export February transactions as CSV" — confirms the export workflow
4. "Compare grocery spending this month vs last month" — confirms analytical capability
