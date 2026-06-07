#!/usr/bin/env bash
# PostToolUse hook — lint docker-compose.yml edits against repo conventions.
# Non-blocking: prints advisory warnings to stderr and always exits 0.
# Enforces a subset of .claude/rules/{conventions,secrets}.md mechanically.

input="$(cat)"

# Extract the edited file path from the hook's JSON payload (Edit/Write/MultiEdit).
file="$(printf '%s' "$input" | node -e '
let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
  try{const j=JSON.parse(s);
    const ti=j.tool_input||{};
    process.stdout.write(String(ti.file_path||ti.path||""));
  }catch(e){process.stdout.write("");}
});' 2>/dev/null)"

# Only act on docker-compose files that exist on disk.
case "$file" in
  *docker-compose.yml|*docker-compose.yaml) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

warn() { printf '[compose-lint] %s\n' "$1" >&2; }

# 1) Obsolete top-level `version:` key (Compose V2 — conventions.md).
if grep -Eq '^version:' "$file"; then
  warn "remove the top-level 'version:' field (Compose V2 format)."
fi

# 2) Unquoted environment values (conventions.md: quote every env value).
#    Heuristic over the environment: mapping; PUID/PGID numerics are allowed.
awk '
  /^[[:space:]]*environment:[[:space:]]*$/ { inenv=1; envind=match($0,/[^ ]/); next }
  inenv {
    if ($0 ~ /^[[:space:]]*$/) next
    ind=match($0,/[^ ]/)
    if (ind<=envind) { inenv=0; next }
    if ($0 ~ /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*:[[:space:]]*[^"'"'"'[:space:]]/) {
      key=$0; sub(/:.*/,"",key); gsub(/[[:space:]]/,"",key)
      if (key!="PUID" && key!="PGID") {
        v=$0; sub(/^[[:space:]]*/,"",v)
        printf "L%d: %s\n", NR, v
      }
    }
  }
' "$file" | while IFS= read -r line; do
  warn "quote this environment value -> ${line}"
done

# 3) Obvious hardcoded secrets (secrets.md: use ${VAR}).
if grep -EnI '(PASSWORD|SECRET|TOKEN|API_?KEY)[A-Z_]*:[[:space:]]*["'"'"']?[^$"'"'"'[:space:]]' "$file" \
     | grep -Ev '\$\{' >/dev/null 2>&1; then
  warn "possible hardcoded secret — use \${VAR} references (see rules/secrets.md)."
fi

exit 0
