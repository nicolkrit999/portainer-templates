// === 📦 CONFIGURATION VARIABLES ===

// 🔑 Your Actual Budget sync ID (Settings → Advanced → Sync ID)
const syncId = "example-sync-id"

// 🔐 API key set in your actual-http-api server (must match the `API_KEY` env variable)
const apiKey = "example-api-key"

// 🔒 Your budget's end-to-end encryption password (if applicable) (Actual Budget → Settings → Encryption)
// Sent on every request so the widget self-heals if the API's decrypted-budget cache is ever cleared.
const encryptionPassword = "example-encryption-password"

// 🌐 Base URL of your actual-http-api instance (no trailing slash)
const apiBaseUrl = "https://actual-http-api.example.com"

// 📁 Names of the category groups to display (comma separated)
const targetGroupNames = [
  "example-group-1",
  "example-group-2",
]

// 💸 Currency formatting
const currencyPrefix = "CHF"  // Symbol shown before the number
const currencySuffix = ""   // Text shown after the number

// === 🎨 APPEARANCE SETTINGS ===

// Font sizes
const textSize = 16                         // Category name
const balanceSize = 16                      // Category balance
const groupTitleSize = 12                   // Title line
const footerTextSize = 10                   // Footer line

// Text colors
const groupTitleColor = Color.gray()        // Title line color
const footerTextColor = Color.gray()        // Footer line color
const positiveColor = Color.green()         // Balance > 0
const zeroColor = Color.gray()              // Balance = 0
const negativeColor = Color.red()           // Balance < 0

// Layout
const itemSpacing = 2                      // Space between lines
const widgetPadding = 20                    // Padding around widget edges

// === 🔍 UNCATEGORISED TRANSACTIONS SETTINGS ===

const lookbackDays = 30                     // Days to look back for uncategorised txns
const uncategorisedBgColor = new Color("#333333", 0.2)  // Background box color
const uncategorisedTextColor = Color.orange()           // Text color
const uncategorisedBoxPadding = 6           // Padding inside the summary box
const uncategorisedFontSize = 12            // Font size for uncategorised summary

// === ⚙️ BEHAVIOUR SETTINGS ===

const enableDebugLogging = true             // Log fetch/debug info to console

// === 🔧 Helper: Format Amount
function formatAmount(amount) {
  const abs = Math.abs(amount)
  const formatted = `${currencyPrefix}${(abs / 100).toFixed(2)}${currencySuffix}`
  return amount < 0 ? `-${formatted}` : formatted
}

// === 📆 Helper: ISO date N days ago
function isoDateNDaysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

// === 📅 Format timestamps
const now = new Date()
const isoMonth = now.toISOString().slice(0, 7)

const monthFormatter = new DateFormatter()
monthFormatter.dateFormat = "MMMM yyyy"
const prettyMonth = monthFormatter.string(now)

const timeFormatter = new DateFormatter()
timeFormatter.useNoDateStyle()
timeFormatter.useShortTimeStyle()

// === 🧾 Try loading cache
let w = new ListWidget()
let cache = null
let data, lastSuccessTime, failedNow = false

if (Keychain.contains("actual-cache")) {
  try {
    cache = JSON.parse(Keychain.get("actual-cache"))
  } catch (e) {
    console.warn("⚠️ Cache could not be parsed")
  }
}

const req = new Request(`${apiBaseUrl}/v1/budgets/${syncId}/months/${isoMonth}/categorygroups`)
req.headers = {
  "x-api-key": apiKey,
  "budget-encryption-password": encryptionPassword,
  "accept": "application/json"
}
req.timeoutInterval = 30  // Add timeout to prevent hanging

try {
  data = await req.loadJSON()
  if (!data || !data.data) {
    throw new Error("Invalid category groups response: " + (data ? JSON.stringify(data) : "No data"))
  }
  Keychain.set("actual-cache", JSON.stringify({ timestamp: now.toISOString(), data }))
  lastSuccessTime = now
} catch (e) {
  console.error("❌ Category groups API fetch failed:", e.message)
  console.error("Response details:", req.response ? JSON.stringify(req.response) : "No response")
  if (cache) {
    data = cache.data
    lastSuccessTime = new Date(cache.timestamp || Date.now())
    failedNow = true
  } else {
    w.addText("❌ No data & no cache available. Check API connection, Tailscale, and server logs for encryption errors.")
    Script.setWidget(w)
    Script.complete()
    return
  }
}

// === 🧾 Fetch uncategorised transactions
const accountsReq = new Request(`${apiBaseUrl}/v1/budgets/${syncId}/accounts`)
accountsReq.headers = { "x-api-key": apiKey, "budget-encryption-password": encryptionPassword, "accept": "application/json" }
accountsReq.timeoutInterval = 30  // Add timeout

let uncategorised = []
let accountStats = []

let accountData
try {
  accountData = await accountsReq.loadJSON()
  if (!accountData || !accountData.data) {
    throw new Error("Invalid accounts response: " + (accountData ? JSON.stringify(accountData) : "No data"))
  }
  const validAccounts = accountData.data.filter(a => !a.closed && !a.offbudget)
  if (enableDebugLogging) console.log(`✅ Found ${validAccounts.length} accounts`)

  const sinceDate = isoDateNDaysAgo(lookbackDays)

  for (let acc of validAccounts) {
    const txUrl = `${apiBaseUrl}/v1/budgets/${syncId}/accounts/${acc.id}/transactions?since_date=${sinceDate}`
    const txReq = new Request(txUrl)
    txReq.headers = { "x-api-key": apiKey, "budget-encryption-password": encryptionPassword, "accept": "application/json" }
    txReq.timeoutInterval = 30  // Add timeout

    try {
      const txData = await txReq.loadJSON()
      const uncats = txData.data.filter(tx =>
        !tx.category &&
        !tx.transfer_id &&
        !tx.starting_balance_flag
      )

      uncategorised.push(...uncats)

      if (enableDebugLogging) {
        console.log(`📒 ${acc.name}: ${uncats.length} uncategorised / ${txData.data.length} total`)
        for (const tx of uncats) {
          console.log(`  - ${formatAmount(tx.amount)} on ${tx.date}`)
        }
      }

      accountStats.push({ name: acc.name, total: txData.data.length, uncategorised: uncats.length, error: false })

    } catch (err) {
      console.warn(`❌ Failed to fetch transactions for '${acc.name}' (${acc.id})`)
      console.warn(err.message || err)
      accountStats.push({ name: acc.name, total: 0, uncategorised: 0, error: true })
      failedNow = true
    }
  }

} catch (err) {
  console.error("❌ Failed to fetch account list")
  console.error(err.message || err)
  console.error("Response details:", accountsReq.response ? JSON.stringify(accountsReq.response) : "No response")
  failedNow = true
}

if (enableDebugLogging) {
  console.log(`📦 Uncategorised transactions pulled from ${failedNow ? "cache" : "API"} | Count: ${uncategorised.length}`)
}

// === 📂 Display category group
const groups = data.data

for (const groupName of targetGroupNames) {
  const targetGroup = groups.find(g => g.name === groupName)

  if (!targetGroup) {
    const err = w.addText(`❌ Group '${groupName}' not found`)
    err.textColor = Color.red()
    w.addSpacer(12)
    continue
  }

  // Draw Group Title
  const title = w.addText(`${targetGroup.name}`)
  title.font = Font.boldSystemFont(groupTitleSize)
  title.textColor = groupTitleColor
  w.addSpacer(4)

  // Draw Categories
  for (const cat of targetGroup.categories) {

    if (cat.hidden || cat.balance === 0) continue

    const stack = w.addStack()
    stack.layoutHorizontally()
    stack.centerAlignContent()

    const nameTxt = stack.addText(cat.name)
    nameTxt.font = Font.systemFont(textSize)
    nameTxt.textColor = Color.white()

    stack.addSpacer()

    const balTxt = stack.addText(formatAmount(cat.balance))
    balTxt.font = Font.boldSystemFont(balanceSize)

    if (cat.balance > 0) balTxt.textColor = positiveColor
    else if (cat.balance < 0) balTxt.textColor = negativeColor
    else balTxt.textColor = zeroColor

    w.addSpacer(itemSpacing)
  }

  w.addSpacer(12)
}

// === 📦 Insert uncategorised transaction box (if applicable)
if (uncategorised.length >= 1) {
  const totalAmount = uncategorised.reduce((sum, tx) => sum + tx.amount, 0)
  const totalFormatted = formatAmount(totalAmount)

  const uncatBox = w.addStack()
  uncatBox.layoutVertically()
  uncatBox.backgroundColor = uncategorisedBgColor
  uncatBox.cornerRadius = 8
  uncatBox.setPadding(
    uncategorisedBoxPadding,
    uncategorisedBoxPadding,
    uncategorisedBoxPadding,
    uncategorisedBoxPadding
  )

  const daysNote = `past ${lookbackDays} days`
  const uncatText = uncatBox.addText(`${uncategorised.length} uncategorised: ${totalFormatted} • ${daysNote}`)
  uncatText.font = Font.mediumSystemFont(uncategorisedFontSize)
  uncatText.textColor = uncategorisedTextColor

  w.addSpacer(itemSpacing)
}

// === 🕓 Footer
w.addSpacer(4)
if (failedNow) {
  const failText = w.addText(`❌ Failed: ${timeFormatter.string(now)}`)
  failText.font = Font.systemFont(footerTextSize)
  failText.textColor = footerTextColor

  const lastText = w.addText(`🕓 Last retrieved: ${timeFormatter.string(lastSuccessTime)}`)
  lastText.font = Font.systemFont(footerTextSize)
  lastText.textColor = footerTextColor
} else {
  const refreshText = w.addText(`Last retrieved: ${timeFormatter.string(lastSuccessTime)}`)
  refreshText.font = Font.systemFont(footerTextSize)
  refreshText.textColor = footerTextColor
}

// === 🔁 Auto-refresh
const refreshInterval = failedNow ? 30 : 360 // in minutes
const nextRefresh = new Date(Date.now() + refreshInterval * 60 * 1000)
w.refreshAfterDate = nextRefresh

// === 📱 Display widget
w.setPadding(widgetPadding, widgetPadding, widgetPadding, widgetPadding)
w.presentLarge()
Script.setWidget(w)
Script.complete()
