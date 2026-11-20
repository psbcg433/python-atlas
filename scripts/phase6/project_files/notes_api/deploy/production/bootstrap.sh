#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu server (24.04 or newer) for the Notes API. Run it as root:
#   scp deploy/production/bootstrap.sh root@<server-ip>:
#   ssh root@<server-ip> bash bootstrap.sh "$(cat ~/.ssh/notes_deploy.pub)"
# It installs Docker from Docker's apt repository, creates the "deploy" user (your keys plus the
# CI key), /srv/notes, a swap file, key-only SSH, automatic security updates and a nightly backup.
set -euo pipefail
ci_public_key=${1:?usage: bash bootstrap.sh "<CI public key: ssh-ed25519 AAAA... notes-deploy-ci>"}
# shellcheck source=/dev/null
source /etc/os-release
if [[ $ID != ubuntu ]]; then
    echo "this script expects Ubuntu, found $ID" >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive


echo "== packages and automatic security updates"
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl jq rsync unattended-upgrades
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
    >/etc/apt/apt.conf.d/20auto-upgrades

echo "== Docker Engine and the Compose plugin (Docker's apt repository)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
    "https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
    >/etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin


echo "== the deploy user (member of the docker group: root-equivalent, keep its keys safe)"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --groups docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
{
    cat /root/.ssh/authorized_keys 2>/dev/null || true
    echo "$ci_public_key"
} | sort -u >/home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
install -d -m 750 -o deploy -g deploy /srv/notes
install -d -m 700 -o deploy -g deploy /srv/notes/.secrets /srv/notes/state


echo "== 2 GB swap (headroom while old and new replicas overlap)"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

echo "== SSH: keys only"
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
    >/etc/ssh/sshd_config.d/90-notes.conf
systemctl try-reload-or-restart ssh.service || true

echo "== nightly database backup at 03:17 UTC (state/backups, kept 14 days)"
echo '17 3 * * * deploy /srv/notes/deploy/production/backup.sh nightly >>/srv/notes/state/backup.log 2>&1' \
    >/etc/cron.d/notes-backup

docker --version
docker compose version
echo "== done: log in as deploy@<server> from now on"
