#!/usr/bin/env bash
#
# One-shot initialisation for a fresh Ubuntu / Debian host.
#
#   scp -r deploy root@YOUR_HOST:/root/
#   ssh root@YOUR_HOST 'bash /root/deploy/bootstrap.sh'
#
# Idempotent: safe to re-run. Installs the runtimes needed to *run* the three
# services, not the toolchains needed to build them. Java, Node and Maven builds
# happen on the development machine and only the artefacts are uploaded — a 2 GB
# host does not want to run a Maven build, and this way node and maven never get
# installed on the server at all.

set -euo pipefail

APP_USER=fusionpilot
APP_ROOT=/opt/fusionpilot
REPO_URL="${REPO_URL:-https://github.com/poyuntunhai/FusionPilot.git}"

if [[ $EUID -ne 0 ]]; then
  echo "run this with sudo: sudo bash deploy/bootstrap.sh" >&2
  exit 1
fi

echo "==> packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  openjdk-17-jre-headless \
  mysql-server \
  nginx \
  python3 python3-venv python3-pip \
  git curl ca-certificates ufw

echo "==> application user"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  # A system user with no password and no login shell: it exists to own the
  # processes, nothing more. Services are reachable only through nginx.
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> directories"
mkdir -p "$APP_ROOT"/{backend,agent-service,web}
chown -R "$APP_USER:$APP_USER" "$APP_ROOT"
chmod 755 "$APP_ROOT"

# The env file holds the database password; only the service user may read it.
if [[ ! -f "$APP_ROOT/.env" ]]; then
  echo "==> NOTE: $APP_ROOT/.env does not exist yet."
  echo "    Copy deploy/env.example there, fill in FUSIONPILOT_DB_PASSWORD, then:"
  echo "      chown $APP_USER:$APP_USER $APP_ROOT/.env && chmod 600 $APP_ROOT/.env"
else
  chown "$APP_USER:$APP_USER" "$APP_ROOT/.env"
  chmod 600 "$APP_ROOT/.env"
fi

echo "==> firewall"
# SSH is allowed BEFORE enabling ufw. Enabling first would drop the connection
# mid-script and lock you out of the box.
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "    enabled: 22 (SSH), 80, 443. 8000 / 3306 / 8080 stay closed: ufw blocks"
echo "    them, and all three bind to 127.0.0.1 - the backend needs"
echo "    --server.address=127.0.0.1 for that, since Spring binds 0.0.0.0 by default."

echo "==> mysql"
systemctl enable --now mysql >/dev/null
echo "    mysql is running. Create the database and user with the same password"
echo "    you put in $APP_ROOT/.env:"
echo
echo "      mysql -e \"CREATE DATABASE IF NOT EXISTS fusionpilot CHARACTER SET utf8mb4;\""
echo "      mysql -e \"CREATE USER IF NOT EXISTS 'fusionpilot'@'127.0.0.1' IDENTIFIED BY '<same password>';\""
echo "      mysql -e \\\"GRANT ALL ON fusionpilot.* TO 'fusionpilot'@'127.0.0.1'; FLUSH PRIVILEGES;\\\""
echo
echo "    (MYSQL_ROOT_PASSWORD / the root auth plugin was left untouched on purpose -"
echo "     the default socket auth is already root-only.)"

echo "==> versions"
java -version 2>&1 | head -1
python3 --version
nginx -v 2>&1 | head -1
mysql --version

cat <<EOF

Done. Next steps are in deploy/README.md:
  1. upload the built artefacts (backend/app.jar, web/dist, agent-service/)
  2. create the venv and install agent requirements
  3. install the systemd units and the nginx site
  4. point a domain at this host and run certbot

Repository for reference: $REPO_URL
EOF
