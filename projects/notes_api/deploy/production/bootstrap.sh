#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu server (24.04 or newer) for the Notes API. Run it as root,
# from projects/notes_api (the inner quotes keep the key one argument through ssh):
#   scp deploy/production/bootstrap.sh deploy/production/ci-command root@<server-ip>:
#   ssh root@<server-ip> bash bootstrap.sh "\"$(cat ~/.ssh/notes_deploy.pub)\""
# It installs Docker from Docker's apt repository, creates the "deploy" user (your keys, plus the
# CI key restricted to ci-command), /srv/notes, a swap file, automatic security updates and a
# nightly backup, then locks SSH down: keys only, only "deploy", no root login. Afterwards
# log in as deploy; "sudo reboot" is the one root command it may run.
set -euo pipefail
ci_public_key=${1:?usage: bash bootstrap.sh "<CI public key: ssh-ed25519 AAAA... notes-deploy-ci>"}
if [[ $ci_public_key == *$'\n'* ]] || ! ssh-keygen -l -f - <<<"$ci_public_key" >/dev/null; then
    echo "the argument must be exactly one public key (the content of notes_deploy.pub)" >&2
    exit 1
fi
if [[ ! -f ci-command ]]; then
    echo "ci-command is missing: copy it next to bootstrap.sh (scp both files)" >&2
    exit 1
fi
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
# The CI key may run ci-command only: "restrict" turns off forwarding, pty and user rc files.
install -m 755 -o root -g root ci-command /usr/local/sbin/notes-ci-command
ci_command='restrict,command="/usr/local/sbin/notes-ci-command"'
{
    grep -v "notes-ci-command" /root/.ssh/authorized_keys 2>/dev/null || true
    echo "$ci_command $ci_public_key"
} | sort -u >/home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
echo 'deploy ALL=(root) NOPASSWD: /usr/sbin/reboot' >/etc/sudoers.d/notes-deploy
chmod 440 /etc/sudoers.d/notes-deploy
visudo -cf /etc/sudoers.d/notes-deploy >/dev/null
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

echo "== nightly database backup at 03:17 UTC (state/backups, kept 14 days)"
echo '17 3 * * * deploy /srv/notes/deploy/production/backup.sh nightly >>/srv/notes/state/backup.log 2>&1' \
    >/etc/cron.d/notes-backup


echo "== SSH: keys only, only deploy, no root; checked before the reload and verified after"
if ! grep -qv "notes-ci-command" /home/deploy/.ssh/authorized_keys; then
    echo "deploy has no key of yours (root had none to copy): not locking SSH down" >&2
    exit 1
fi
# sshd keeps the FIRST value it reads for a keyword, and sshd_config includes the drop-ins in
# name order before its own lines: 00-notes.conf wins over 50-cloud-init.conf and the rest.
rm -f /etc/ssh/sshd_config.d/90-notes.conf # this file's old name (it lost to earlier files)
cat >/etc/ssh/sshd_config.d/00-notes.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers deploy
MaxAuthTries 3
CONF
install -d -m 755 /run/sshd # sshd -t needs it; ssh.socket activation may not have made it yet
sshd -t                     # a broken config must never reach the running daemon
if systemctl is-active --quiet ssh.service; then
    systemctl reload ssh.service # existing sessions stay open
fi
effective=$(sshd -T)
for setting in "passwordauthentication no" "kbdinteractiveauthentication no" \
    "permitrootlogin no" "allowusers deploy" "maxauthtries 3"; do
    if ! grep -qx "$setting" <<<"$effective"; then
        echo "sshd is not using '$setting': another file overrides it (sshd -T)" >&2
        exit 1
    fi
done

docker --version
docker compose version
echo "== done: log in as deploy@<server> from now on (root can no longer log in over SSH)"
