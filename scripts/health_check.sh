#!/usr/bin/env bash

set -u

frontend_url="http://localhost:5173/"
backend_url="http://localhost:8000/health"
public_dev_url="https://dev.ghostglue.io/"
public_hooks_url="https://hooks.ghostglue.io/"

pass() {
  printf "[OK] %s\n" "$1"
}

warn() {
  printf "[WARN] %s\n" "$1"
}

check_status() {
  local url="$1"
  local expected="$2"
  local label="$3"
  local status

  status=$(curl -sS -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)
  if [ "$status" = "$expected" ]; then
    pass "$label ($status)"
  else
    warn "$label (got ${status:-n/a}, expected $expected)"
  fi
}

echo "GhostGlue health check"
echo "----------------------"

if pgrep -f "cloudflared tunnel run dev" >/dev/null 2>&1; then
  pass "Cloudflare tunnel 'dev' process is running"
else
  warn "Cloudflare tunnel 'dev' is not running"
fi

check_status "$frontend_url" "200" "Local frontend reachable"

backend_status=$(curl -sS -o /dev/null -w "%{http_code}" "$backend_url" 2>/dev/null || true)
if [ "$backend_status" = "200" ]; then
  pass "Local backend health endpoint reachable (200)"
else
  warn "Local backend health endpoint not ready (got ${backend_status:-n/a})"
fi

public_dev_status=$(curl -sS -o /dev/null -w "%{http_code}" "$public_dev_url" 2>/dev/null || true)
if [ "$public_dev_status" = "200" ] || [ "$public_dev_status" = "302" ]; then
  pass "Public dev hostname reachable ($public_dev_status)"
else
  warn "Public dev hostname issue (got ${public_dev_status:-n/a})"
fi

public_hooks_status=$(curl -sS -o /dev/null -w "%{http_code}" "$public_hooks_url" 2>/dev/null || true)
if [ "$public_hooks_status" = "200" ] || [ "$public_hooks_status" = "404" ]; then
  pass "Public hooks hostname reachable ($public_hooks_status)"
else
  warn "Public hooks hostname issue (got ${public_hooks_status:-n/a})"
fi

printf "\nHint: if dev shows a black screen, check browser console + Cloudflare Access session.\n"
