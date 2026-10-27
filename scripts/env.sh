# Sourced by the deploy scripts: per-installation settings come from .env, never the repository.
# Expects ROOT and die() to be defined by the caller.

ENV_FILE="${ENV_FILE:-$ROOT/.env}"

env_value() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

require_env() {
  local value
  value="$(env_value "$1")"
  [ -n "$value" ] || die "$1 is not set in .env: $2. See .env.example."
  printf '%s' "$value"
}

# "https://host:8100/x" -> "host"
host_of() {
  printf '%s' "$1" | sed -E 's#^[a-z]+://##; s#[:/].*$##'
}
