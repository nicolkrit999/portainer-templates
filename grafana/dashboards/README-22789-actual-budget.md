# Actual Budget (grafana.com ID 22789)

## Source
https://grafana.com/grafana/dashboards/22789/ - the dashboard shipped with
sakowicz/actual-budget-prometheus-exporter (`grafana/dashboard.json`, version 9).

## What it's for
Per-budget overview from the exporter's metrics: total balance, transaction and
uncategorized-transaction counts, transactions per category, balance per account.
A `budget` dropdown picks between the budgets (the `budget` label is the
`ACTUAL_BUDGET_NAME_<n>` value in the exporter stack).

## Fixes applied (2026-11-19)
- `${DS_PROMETHEUS}` (11 places) hardcoded to the provisioned datasource uid
  `prometheus`, and the `__inputs` block removed (file provisioning cannot ask for it).
- `id` reset to null so Grafana assigns it.
- Balance panels divide by 100: the exporter reports amounts in minor units.

## Provisioning
Lives next to the UniFi dashboards in `${VOLUME_CONFIG}/grafana/provisioning/dashboards/json/`
(host copy, copied by hand from the stack checkout after a push to `main`).
