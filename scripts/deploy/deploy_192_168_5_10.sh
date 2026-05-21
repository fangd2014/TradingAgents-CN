#!/usr/bin/env bash
#
# One-command deployment for TradingAgents-CN on 192.168.5.10.
#
# Run this script from a developer machine that can SSH to the server. It
# updates the server checkout from GitHub, builds only backend/frontend images,
# starts the required Docker Compose services, and verifies the app endpoints.
# MongoDB keeps using the compose-defined mongo:4.4 image and existing volume.

set -Eeuo pipefail

DEFAULT_HOST="root@192.168.5.10"
DEFAULT_DIR="/root/src/TradingAgents-CN"
DEFAULT_BRANCH="codex/stock-detail-financial-technical-insights"
DEFAULT_REMOTE="origin"
DEFAULT_HEALTH_TIMEOUT="240"

REMOTE_HOST="${REMOTE_HOST:-$DEFAULT_HOST}"
REMOTE_DIR="${REMOTE_DIR:-$DEFAULT_DIR}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-$DEFAULT_BRANCH}"
GIT_REMOTE="${GIT_REMOTE:-$DEFAULT_REMOTE}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-$DEFAULT_HEALTH_TIMEOUT}"
SKIP_BUILD=0

SCRIPT_PATH="$0"

usage() {
  cat <<USAGE
Usage:
  ${SCRIPT_PATH} [options]

Options:
  --host <ssh-host>        SSH target. Default: ${DEFAULT_HOST}
  --dir <remote-dir>       Project directory on the server. Default: ${DEFAULT_DIR}
  --branch <branch>        Git branch to deploy. Default: ${DEFAULT_BRANCH}
  --remote <remote-name>   Git remote name on the server. Default: ${DEFAULT_REMOTE}
  --timeout <seconds>      Health check timeout. Default: ${DEFAULT_HEALTH_TIMEOUT}
  --skip-build             Skip docker compose build backend frontend.
  -h, --help               Show this help.

Examples:
  ${SCRIPT_PATH}
  ${SCRIPT_PATH} --branch codex/stock-detail-financial-technical-insights
  ${SCRIPT_PATH} --skip-build --timeout 120
USAGE
}

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy][error] %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      [ "$#" -ge 2 ] || fail "--host requires a value"
      REMOTE_HOST="$2"
      shift 2
      ;;
    --dir)
      [ "$#" -ge 2 ] || fail "--dir requires a value"
      REMOTE_DIR="$2"
      shift 2
      ;;
    --branch)
      [ "$#" -ge 2 ] || fail "--branch requires a value"
      DEPLOY_BRANCH="$2"
      shift 2
      ;;
    --remote)
      [ "$#" -ge 2 ] || fail "--remote requires a value"
      GIT_REMOTE="$2"
      shift 2
      ;;
    --timeout)
      [ "$#" -ge 2 ] || fail "--timeout requires a value"
      HEALTH_TIMEOUT="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

case "$HEALTH_TIMEOUT" in
  ''|*[!0-9]*)
    fail "--timeout must be a positive integer"
    ;;
esac

require_cmd ssh

log "Target: ${REMOTE_HOST}:${REMOTE_DIR}"
log "Branch: ${DEPLOY_BRANCH}"
log "Remote: ${GIT_REMOTE}"
if [ "$SKIP_BUILD" -eq 1 ]; then
  log "Build: skipped"
else
  log "Build: backend frontend"
fi

log "Checking SSH connectivity..."
ssh -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_HOST" "printf ok" >/dev/null

log "Starting remote deployment..."
ssh "$REMOTE_HOST" "bash -s" -- \
  "$REMOTE_DIR" \
  "$DEPLOY_BRANCH" \
  "$GIT_REMOTE" \
  "$SKIP_BUILD" \
  "$HEALTH_TIMEOUT" <<'REMOTE_SCRIPT'
set -Eeuo pipefail

REMOTE_DIR="$1"
DEPLOY_BRANCH="$2"
GIT_REMOTE="$3"
SKIP_BUILD="$4"
HEALTH_TIMEOUT="$5"

log() {
  printf '[remote-deploy] %s\n' "$*"
}

fail() {
  printf '[remote-deploy][error] %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command on server: $1"
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local deadline
  deadline=$((SECONDS + HEALTH_TIMEOUT))

  log "Waiting for ${name}: ${url}"
  until curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      fail "Timed out waiting for ${name} at ${url}"
    fi
    sleep 5
  done
  log "${name} is reachable"
}

backup_server_state() {
  local backup_dir="$1"
  mkdir -p "$backup_dir"

  git rev-parse HEAD >"${backup_dir}/git-head.txt" 2>/dev/null || true
  git status --short >"${backup_dir}/git-status.txt" 2>/dev/null || true
  git diff >"${backup_dir}/worktree.diff" 2>/dev/null || true

  local items=()
  [ -e ".env" ] && items+=(".env")
  [ -e "data" ] && items+=("data")
  [ -e "config" ] && items+=("config")

  if [ "${#items[@]}" -gt 0 ]; then
    tar -czf "${backup_dir}/runtime-files.tgz" "${items[@]}" 2>/dev/null || true
  fi
}

require_cmd git
require_cmd docker
require_cmd curl
require_cmd tar

cd "$REMOTE_DIR" || fail "Remote directory not found: ${REMOTE_DIR}"
[ -d ".git" ] || fail "Remote directory is not a Git checkout: ${REMOTE_DIR}"
[ -f "docker-compose.yml" ] || fail "docker-compose.yml not found in ${REMOTE_DIR}"

docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is not available"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="/root/backups/tradingagents-${timestamp}"
log "Backing up current server state to ${backup_dir}"
backup_server_state "$backup_dir"

log "Fetching ${GIT_REMOTE}/${DEPLOY_BRANCH}"
git fetch "$GIT_REMOTE" "$DEPLOY_BRANCH"
git checkout -B "$DEPLOY_BRANCH" "${GIT_REMOTE}/${DEPLOY_BRANCH}"
git reset --hard "${GIT_REMOTE}/${DEPLOY_BRANCH}"

if [ ! -f ".env" ]; then
  if [ -f ".env.docker" ]; then
    cp ".env.docker" ".env"
    chmod 600 ".env"
    log "Created .env from .env.docker"
  else
    fail ".env is missing and .env.docker was not found"
  fi
fi

if ! grep -Eq '^[[:space:]]*image:[[:space:]]*mongo:4\.4([[:space:]]|$)' docker-compose.yml; then
  fail "Refusing to deploy: docker-compose.yml does not pin mongodb image to mongo:4.4"
fi

log "Validating docker compose config"
docker compose config >/dev/null

if [ "$SKIP_BUILD" -eq 1 ]; then
  log "Skipping image build"
else
  log "Building backend and frontend images"
  docker compose build backend frontend
fi

log "Starting required services"
docker compose up -d mongodb redis backend frontend

wait_for_url "backend health" "http://127.0.0.1:8000/api/health"
wait_for_url "frontend" "http://127.0.0.1:3000"

current_commit="$(git rev-parse --short HEAD)"

log "Deployment complete"
log "Commit: ${current_commit}"
log "Backup: ${backup_dir}"
log "Frontend: http://192.168.5.10:3000"
log "Backend health: http://192.168.5.10:8000/api/health"
docker compose ps
REMOTE_SCRIPT

log "Remote deployment finished."
log "Frontend: http://192.168.5.10:3000"
log "Backend health: http://192.168.5.10:8000/api/health"
