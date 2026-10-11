#!/usr/bin/env bash
#
# Build locally, ship the artefacts, restart the services.
#
#   ./deploy/deploy.sh --host root@1.2.3.4 --domain example.com
#
# Building happens here and never on the server: a 1.6-2 GB host has no business running a Maven
# or Vite build, and keeping the toolchains on the development machine means node and maven never
# have to be installed on the server at all (see deploy/bootstrap.sh).
#
# Configuration is read from, in order of precedence: command-line flags, environment variables,
# then deploy/.deploy.env. That file is git-ignored on purpose -- it holds a real host name, which
# does not belong in a public repository.
#
#   DEPLOY_HOST          ssh target, e.g. root@1.2.3.4
#   DEPLOY_DOMAIN        public hostname, used for the post-deploy check
#   DEPLOY_SSH_KEY       private key path
#   DEPLOY_APP_ROOT      remote install directory   (default /opt/fusionpilot)
#   DEPLOY_SERVICE_USER  owner of the remote files  (default fusionpilot)
#
# Flags: --host --domain --ssh-key --app-root --service-user --only backend|web|agent
#        --with-tests --no-restart --help
#
# Exit code is non-zero if any step fails, including the health check: a deploy that returns 0
# while the site is down is worse than no deploy script at all.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Defaults, then overridden by .deploy.env, then by the environment, then by flags.
DEPLOY_HOST=""
DEPLOY_DOMAIN=""
DEPLOY_SSH_KEY="$HOME/.ssh/id_ed25519"
DEPLOY_APP_ROOT="/opt/fusionpilot"
DEPLOY_SERVICE_USER="fusionpilot"

if [[ -f "$REPO_ROOT/deploy/.deploy.env" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/deploy/.deploy.env"
fi

ONLY=""
WITH_TESTS=0
DO_RESTART=1
BACKEND_SERVICES="fusionpilot-backend fusionpilot-agent"

usage() {
  # Print the header comment block, whatever its length: awk stops at the first non-comment line,
  # so adding or removing a line up there cannot silently truncate the help text.
  awk 'NR > 1 { if (/^#/) { sub(/^# ?/, ""); print } else { exit } }' "${BASH_SOURCE[0]}"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) DEPLOY_HOST="${2:?--host needs a value}"; shift 2 ;;
    --domain) DEPLOY_DOMAIN="${2:?--domain needs a value}"; shift 2 ;;
    --ssh-key) DEPLOY_SSH_KEY="${2:?--ssh-key needs a value}"; shift 2 ;;
    --app-root) DEPLOY_APP_ROOT="${2:?--app-root needs a value}"; shift 2 ;;
    --service-user) DEPLOY_SERVICE_USER="${2:?--service-user needs a value}"; shift 2 ;;
    --only) ONLY="${2:?--only needs a value}"; shift 2 ;;
    --with-tests) WITH_TESTS=1; shift ;;
    --no-restart) DO_RESTART=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown flag: $1" >&2; usage 1 ;;
  esac
done

case "$ONLY" in
  ""|backend|web|agent) ;;
  *) echo "--only must be backend, web or agent" >&2; exit 1 ;;
esac

if [[ -z "$DEPLOY_HOST" ]]; then
  echo "error: no host. Pass --host root@1.2.3.4, or set DEPLOY_HOST, or create deploy/.deploy.env." >&2
  echo >&2
  usage 1
fi
if [[ ! -f "$DEPLOY_SSH_KEY" ]]; then
  echo "error: ssh key not found: $DEPLOY_SSH_KEY" >&2
  exit 1
fi

SSH=(ssh -i "$DEPLOY_SSH_KEY" -o StrictHostKeyChecking=accept-new "$DEPLOY_HOST")
SCP=(scp -i "$DEPLOY_SSH_KEY" -o StrictHostKeyChecking=accept-new)

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
note() { printf '    %s\n' "$1"; }

# The Maven wrapper ships both flavours; the POSIX one fails under Git Bash on Windows with a
# ClassNotFoundException, so pick by platform rather than by what happens to be on PATH.
MVN="backend/mvnw"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) MVN="backend/mvnw.cmd" ;;
esac

# ------------------------------------------------------------------ preflight
step "Preflight"
if [[ -n "${JAVA_HOME:-}" ]]; then
  note "JAVA_HOME=$JAVA_HOME"
else
  note "WARNING: JAVA_HOME is unset; the Maven wrapper will fall back to whatever 'java' is on PATH."
fi
"${SSH[@]}" "test -d '$DEPLOY_APP_ROOT/backend' && test -d '$DEPLOY_APP_ROOT/web'" \
  || { echo "error: $DEPLOY_APP_ROOT/backend or /web is missing on the host. Run deploy/bootstrap.sh first." >&2; exit 1; }
note "host reachable, $DEPLOY_APP_ROOT present"

# ------------------------------------------------------------------ build
if [[ "$ONLY" != "web" && "$ONLY" != "agent" ]]; then
  step "Build backend"
  cd "$REPO_ROOT"
  if [[ "$WITH_TESTS" == "1" ]]; then
    "$MVN" -f backend/pom.xml -B test
  fi
  "$MVN" -f backend/pom.xml -B -DskipTests package
  JAR="$(ls -t "$REPO_ROOT"/backend/target/fusionpilot-backend-*.jar 2>/dev/null | head -1)"
  [[ -n "$JAR" ]] || { echo "error: no jar produced under backend/target" >&2; exit 1; }
  note "built $(basename "$JAR") ($(du -h "$JAR" | cut -f1))"
fi

if [[ "$ONLY" != "backend" && "$ONLY" != "agent" ]]; then
  step "Build frontend"
  cd "$REPO_ROOT/web"
  # Vite empties the output directory itself, but doing it here keeps the build honest: the result
  # can never be a mix of this build and a stale one. Relative path on purpose — an absolute
  # /d/... path is a POSIX-style path that Windows-level delete hooks cannot resolve.
  if [[ -d dist ]]; then
    rm -rf dist
  fi
  npm run build
  [[ -f "$REPO_ROOT/web/dist/index.html" ]] || { echo "error: web/dist/index.html missing after build" >&2; exit 1; }
  note "built web/dist ($(du -sh "$REPO_ROOT/web/dist" | cut -f1))"
fi

# ------------------------------------------------------------------ upload
if [[ -n "${JAR:-}" ]]; then
  step "Upload backend jar"
  # Keep the build that is currently running next to the new one. A bad deploy is then
  # `mv app.jar.prev app.jar && systemctl restart fusionpilot-backend` away from being undone,
  # rather than a rebuild.
  "${SSH[@]}" "if [ -f '$DEPLOY_APP_ROOT/backend/app.jar' ]; then cp '$DEPLOY_APP_ROOT/backend/app.jar' '$DEPLOY_APP_ROOT/backend/app.jar.prev'; fi"
  "${SCP[@]}" "$JAR" "$DEPLOY_HOST:$DEPLOY_APP_ROOT/backend/app.jar"
  note "-> $DEPLOY_APP_ROOT/backend/app.jar (previous kept as app.jar.prev)"
fi

if [[ "$ONLY" != "backend" && "$ONLY" != "agent" ]]; then
  step "Upload frontend"
  # Vite content-hashes its filenames, so nothing can safely overwrite: dropping assets/ first is
  # what keeps stale bundles out of the directory instead of letting them pile up forever.
  "${SSH[@]}" "rm -rf '$DEPLOY_APP_ROOT/web/dist/assets' && mkdir -p '$DEPLOY_APP_ROOT/web/dist'"
  # tar instead of `scp -r`: it preserves modes and skips the shell-metacharacter pitfalls of
  # filenames, and the archive is built from the repo root so the remote side needs no cd.
  tar -czf - -C "$REPO_ROOT/web" dist | "${SSH[@]}" "tar -xzf - -C '$DEPLOY_APP_ROOT/web'"
  note "-> $DEPLOY_APP_ROOT/web/dist"
fi

if [[ "$ONLY" != "backend" && "$ONLY" != "web" ]]; then
  step "Sync agent-service"
  cd "$REPO_ROOT"
  if [[ -n "$(git status --porcelain agent-service)" ]]; then
    note "WARNING: agent-service has uncommitted changes; HEAD is what gets shipped."
  fi
  # git archive ships exactly the tracked files, so the server's .venv (untracked, and expensive to
  # rebuild) is left alone: tar extracts over the directory without deleting anything.
  git archive HEAD agent-service | "${SSH[@]}" "tar -x -C '$DEPLOY_APP_ROOT'"
  note "-> $DEPLOY_APP_ROOT/agent-service"
fi

step "Fix ownership"
"${SSH[@]}" "chown -R '$DEPLOY_SERVICE_USER:$DEPLOY_SERVICE_USER' '$DEPLOY_APP_ROOT'"
note "$DEPLOY_SERVICE_USER owns $DEPLOY_APP_ROOT"

# ------------------------------------------------------------------ restart
if [[ "$DO_RESTART" == "1" && "$ONLY" == "web" ]]; then
  # Nothing to restart: nginx reads /opt/fusionpilot/web/dist from disk on every request, so a
  # frontend-only deploy is live the moment the upload finishes.
  step "Restart skipped (frontend only; nginx serves the new dist immediately)"
elif [[ "$DO_RESTART" == "1" ]]; then
  step "Restart services"
  "${SSH[@]}" "systemctl restart $BACKEND_SERVICES && systemctl is-active --quiet $BACKEND_SERVICES"
  note "restarted: $BACKEND_SERVICES"
else
  step "Restart skipped (--no-restart); the new artefacts are on disk but not live yet"
fi

# ------------------------------------------------------------------ verify
step "Health check"
if [[ -z "$DEPLOY_DOMAIN" ]]; then
  # No public hostname configured: check the two services where they actually listen. Both bind to
  # 127.0.0.1, so this has to run on the host rather than from here.
  note "no --domain given, checking the loopback ports over ssh instead"
  check_service() {
    local port="$1" path="$2" unit="$3"
    "${SSH[@]}" "curl -fsS --max-time 5 http://127.0.0.1:$port$path" | grep -q '"status":"UP"' \
      || { echo "error: $unit did not come up. Check: 'journalctl -u $unit -n 50'" >&2; exit 1; }
    note "$unit: UP"
  }
  check_service 8080 /api/v1/system/health fusionpilot-backend
  check_service 8000 /api/v1/agent/health fusionpilot-agent
  printf '\n\033[32mDeployed.\033[0m Services are up on the host (no --domain given, so this is not a public check).\n'
  exit 0
fi

# The backend takes a few seconds to bind its port, so poll instead of sleeping a fixed amount and
# hoping. 30 x 2s is generous for a jar this size on a 2 vCPU host.
deadline=30
for ((attempt = 1; attempt <= deadline; attempt++)); do
  if curl -fsS --max-time 5 "https://$DEPLOY_DOMAIN/api/v1/system/health" 2>/dev/null | grep -q '"status":"UP"'; then
    note "backend: UP"
    break
  fi
  if [[ "$attempt" == "$deadline" ]]; then
    echo "error: backend did not report UP within $((deadline * 2))s. Check: ${SSH[*]} 'journalctl -u fusionpilot-backend -n 50'" >&2
    exit 1
  fi
  sleep 2
done

curl -fsS --max-time 5 "https://$DEPLOY_DOMAIN/api/v1/agent/health" | grep -q '"status":"UP"' \
  || { echo "error: agent did not report UP. Check: ${SSH[*]} 'journalctl -u fusionpilot-agent -n 50'" >&2; exit 1; }
note "agent: UP"

curl -fsSI --max-time 10 "https://$DEPLOY_DOMAIN/" | head -1 | grep -q ' 200' \
  || { echo "error: the landing page did not return 200" >&2; exit 1; }
note "landing page: 200"

printf '\n\033[32mDeployed.\033[0m https://%s\n' "$DEPLOY_DOMAIN"
