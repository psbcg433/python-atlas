"""The production setup: Compose override, Caddy, monitoring, deploy scripts and workflows.

These tests read the files; the rehearsal in the Phase 6 Project runs them for real.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_DIR = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = PROJECT_DIR / "deploy" / "production"
WORKFLOWS_DIR = PROJECT_DIR.parents[1] / ".github" / "workflows"  # repository root
SCRIPTS = ("dc", "lib.sh", "backup.sh", "rollout.sh", "bootstrap.sh", "ci-command")
APP_SERVICES = ("migrate", "api", "worker")


class ComposeLoader(yaml.SafeLoader):
    """A YAML loader that understands Compose's !reset and !override tags."""


def construct_tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    """Read a tagged node as the plain value it wraps."""
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    value = loader.construct_scalar(node)
    return None if value in ("", "null", "~") else value  # !reset null removes the key


for tag in ("!reset", "!override"):
    ComposeLoader.add_constructor(tag, construct_tagged)


def load(path: Path) -> Any:
    """Parse a YAML file (Compose tags allowed)."""
    return yaml.load(path.read_text(), Loader=ComposeLoader)  # a SafeLoader subclass


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    """The services of compose.prod.yaml."""
    return load(PROJECT_DIR / "compose.prod.yaml")["services"]


def test_backing_services_publish_no_host_ports(services: dict[str, Any]) -> None:
    """PostgreSQL and Redis are reachable only inside the Compose network."""
    assert services["db"]["ports"] == []
    assert services["redis"]["ports"] == []


def test_app_services_run_the_pushed_image_and_never_build(services: dict[str, Any]) -> None:
    """migrate, api and worker run NOTES_IMAGE:TAG and have no build section."""
    for name in APP_SERVICES:
        assert services[name]["build"] is None, name
        assert services[name]["image"].startswith("${NOTES_IMAGE:?"), name
        assert ":${TAG:?" in services[name]["image"], name


def test_only_the_proxy_is_public(services: dict[str, Any]) -> None:
    """Only Caddy listens on every interface; the dashboards stay on localhost."""
    public = {name for name, service in services.items() if service.get("ports")}
    assert public == {"proxy", "prometheus", "grafana"}
    for name in ("prometheus", "grafana"):
        assert all(port.startswith("127.0.0.1:") for port in services[name]["ports"]), name
    assert [port.split(":")[-1] for port in services["proxy"]["ports"]] == ["80", "443", "443/udp"]


def test_every_service_rotates_its_logs(services: dict[str, Any]) -> None:
    """Every container's json-file log is capped, so logs cannot fill the disk."""
    for name, service in services.items():
        assert service["logging"]["options"]["max-size"] == "10m", name


def test_connection_budget_fits_during_a_rollout(services: dict[str, Any]) -> None:
    """Old + new replicas and the worker stay under PostgreSQL's max_connections."""
    environment = services["api"]["environment"]
    per_process = int(environment["NOTES_DATABASE_POOL_SIZE"]) + int(
        environment["NOTES_DATABASE_MAX_OVERFLOW"]
    )
    processes = int(environment["WEB_CONCURRENCY"]) * services["api"]["deploy"]["replicas"] * 2
    max_connections = int(services["db"]["command"][-1].split("=")[1])
    assert processes * per_process + per_process < max_connections  # + the worker


def test_secrets_are_required_not_defaulted() -> None:
    """A missing secret stops Compose instead of starting with an empty value."""
    text = (PROJECT_DIR / "compose.prod.yaml").read_text()
    for name in ("POSTGRES_PASSWORD", "NOTES_SITE", "ACME_EMAIL", "GRAFANA_ADMIN_PASSWORD"):
        assert f"${{{name}:?" in text, name
        assert f"${{{name}:-" not in text, name
    assert "ADMIN_EMAILS" not in text  # admins are promoted with notes_api.manage, not by e-mail


def test_redis_needs_a_password_and_only_caddy_may_forward(services: dict[str, Any]) -> None:
    """requirepass comes from a secret file; Uvicorn trusts X-Forwarded-For from Caddy only."""
    redis = services["redis"]
    assert "requirepass" in " ".join(redis["command"])
    assert redis["secrets"] == ["notes_redis_password"]
    assert "REDISCLI_AUTH" in redis["healthcheck"]["test"][1]
    proxy_address = services["proxy"]["networks"]["default"]["ipv4_address"]
    for name in APP_SERVICES:
        assert "notes_redis_password" in services[name]["secrets"], name
    assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] == proxy_address


def test_caddy_redirects_sets_hsts_and_hides_metrics() -> None:
    """The Caddyfile has the ACME e-mail, HSTS, retries and a hidden /metrics."""
    caddyfile = (PRODUCTION_DIR / "Caddyfile").read_text()
    assert "email {$ACME_EMAIL}" in caddyfile
    assert 'Strict-Transport-Security "max-age=31536000"' in caddyfile
    assert "respond @internal 404" in caddyfile
    assert "lb_try_duration" in caddyfile
    assert "{$NOTES_SITE} {" in caddyfile  # no default: production needs a real hostname
    assert re.search(r"request_body \{\s+max_size 1MB", caddyfile)


def test_alert_rules_use_metrics_the_app_exports() -> None:
    """Every metric an alert rule queries is defined in core/metrics.py."""
    metrics_source = (PROJECT_DIR / "src" / "notes_api" / "core" / "metrics.py").read_text()
    rules = load(PRODUCTION_DIR / "alerts.yml")["groups"][0]["rules"]
    assert {rule["alert"] for rule in rules} == {
        "NotesApiDown",
        "NotesApiHighErrorRate",
        "NotesApiSlowP95",
    }
    for rule in rules:
        for metric in re.findall(r"notes_[a-z_]+", rule["expr"]):
            base = metric.removesuffix("_bucket")
            assert f'"{base}"' in metrics_source, (rule["alert"], metric)


def test_prometheus_discovers_every_api_replica() -> None:
    """Prometheus finds the api replicas through DNS and loads the rules."""
    config = load(PRODUCTION_DIR / "prometheus.yml")
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    assert jobs["notes-api"]["dns_sd_configs"][0]["names"] == ["api"]
    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_are_strict_executable_bash(script: str) -> None:
    """Each script parses with bash -n; the runnable ones are strict and executable."""
    path = PRODUCTION_DIR / script
    text = path.read_text()
    if script != "lib.sh":  # sourced, not run
        assert text.startswith("#!/usr/bin/env bash\n"), script
        assert "set -euo pipefail" in text, script
        assert path.stat().st_mode & 0o111, f"{script} is not executable"
    assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0


def test_rollout_order_backup_migrate_pin_start_drain_stop() -> None:
    """rollout.sh backs up, migrates, pins, starts, drains, stops, then replaces the worker."""
    text = (PRODUCTION_DIR / "rollout.sh").read_text()
    steps = [
        'deploy/production/backup.sh "pre-$TAG"',
        "run --rm --no-deps migrate",
        'pin_upstreams "${old[@]}"',
        "--no-recreate --wait",
        'pin_upstreams "${new[@]}"',
        'docker stop --timeout 30 "${old[@]}"',
        "up --detach --no-deps --wait worker",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)


FAKE_DOCKER = r"""#!/usr/bin/env bash
# Records each call; answers the few questions rollout.sh asks.
echo "$*" >>"$FAKE_LOG"
case " $* " in
*" exec -T db psql "*) echo "${FAKE_DB_REVISION:-}" ;;
*" alembic show "*)
    revision=${*: -1}
    if [[ " $FAKE_IMAGE_REVISIONS " != *" $revision "* ]]; then
        echo "Can't locate revision identified by '$revision'" >&2
        exit 255
    fi
    ;;
*" ps --format {{.Image}} api "*) echo "$NOTES_IMAGE:$TAG" ;;
*" config --services "*) printf '%s\n' db redis migrate api worker proxy prometheus grafana ;;
esac
"""


class FakeServer:
    """rollout.sh against a fake docker: the decisions are real, the containers are not."""

    def __init__(self, tmp_path: Path) -> None:
        """A bin folder with the fake docker and an empty state folder."""
        self.state = tmp_path / "state"
        self.log = tmp_path / "docker.log"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(FAKE_DOCKER)
        (bin_dir / "docker").chmod(0o755)
        self.environment = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "NOTES_STATE_DIR": str(self.state),
            "NOTES_IMAGE": "ghcr.io/owner/notes-api",
            "SKIP_PULL": "1",
            "PRUNE_IMAGES": "0",
            "DRAIN_SECONDS": "0",
            "FAKE_LOG": str(self.log),
        }

    def run(
        self, *arguments: str, db: str = "", image_knows: str = "0001 0002 0003 0004 0005 0006"
    ) -> tuple[int, str, list[str]]:
        """rollout.sh <arguments>: (exit code, its output, the docker calls it made)."""
        self.log.write_text("")
        run = subprocess.run(
            [str(PRODUCTION_DIR / "rollout.sh"), *arguments],
            env={**self.environment, "FAKE_DB_REVISION": db, "FAKE_IMAGE_REVISIONS": image_knows},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return run.returncode, run.stdout + run.stderr, self.log.read_text().splitlines()

    def current(self) -> str:
        """The tag release.env records."""
        return (self.state / "release.env").read_text().split("TAG=")[1].strip()


def starts_migrate(call: str) -> bool:
    """An "up" without --no-deps starts the services it names and their dependencies; without
    names, every service, the one-off migrate job (alembic upgrade head) included."""
    words = call.split()
    if "up" not in words or "--no-deps" in words:
        return False
    named = [word for word in words[words.index("up") + 1 :] if not word.startswith("-")]
    return not named or bool({"migrate", "api", "worker"} & set(named))


def migrated(calls: list[str]) -> bool:
    """Did rollout.sh run alembic upgrade head, directly or through an "up"?"""
    ran_job = any(call.endswith("run --rm --no-deps migrate") for call in calls)
    return ran_job or any(starts_migrate(call) for call in calls)


def test_rollback_after_a_migration_skips_it_and_never_returns_to_the_bad_release(
    tmp_path: Path,
) -> None:
    """A good; B adds migration 0007 and passes its smoke test, but is bad; roll back twice.

    Before the fix the rollback ran A's `alembic upgrade head` against a database at 0007
    ("Can't locate revision") and stopped, and a second rollback went back to B.
    """
    server, with_0007 = FakeServer(tmp_path), "0001 0002 0003 0004 0005 0006 0007"
    assert server.run("release-a", db="0006")[0] == 0
    assert server.run("mark-good")[0] == 0
    code, _, calls = server.run("release-b", db="0006", image_knows=with_0007)
    assert code == 0 and migrated(calls)
    assert server.run("mark-good")[0] == 0
    code, output, calls = server.run("rollback", db="0007")
    assert (code, server.current(), migrated(calls)) == (0, "release-a", False)
    assert "rolling back from release-b to release-a" in output
    code, output, _ = server.run("rollback", db="0007")
    assert code == 1 and "no known-good release other than release-a" in output
    assert server.current() == "release-a"  # not release-b
    history = (server.state / "history.log").read_text().splitlines()
    assert [line.split(" ", 1)[1] for line in history] == [
        "release-a",
        "release-b",
        "release-a rollback",
    ]


def test_an_image_older_than_the_database_does_not_migrate(tmp_path: Path) -> None:
    """Deploying an older tag by name (not rollback) also leaves a newer schema alone."""
    server = FakeServer(tmp_path)
    code, output, calls = server.run("release-a", db="0007")
    assert (code, migrated(calls)) == (0, False)
    assert "the database is at 0007, newer than this image" in output
    code, _, calls = server.run("release-a", db="0005")
    assert (code, migrated(calls)) == (0, True)


def test_rollback_needs_a_known_good_release(tmp_path: Path) -> None:
    """The first release failed its smoke test: there is nothing to go back to."""
    server = FakeServer(tmp_path)
    assert server.run("release-a")[0] == 0
    code, output, _ = server.run("rollback")
    assert code == 1 and "no known-good release" in output


CI_COMMAND_STUBS = {
    "rollout.sh": 'echo "rollout.sh $* NOTES_IMAGE=${NOTES_IMAGE:-} SKIP_PULL=${SKIP_PULL:-}"',
    "docker": 'echo "docker $*"',
    "rrsync": 'echo "rrsync $*"',
}
SHA = "0123456789abcdef0123456789abcdef01234567"


def ci_command(tmp_path: Path, request: str) -> subprocess.CompletedProcess[str]:
    """Run ci-command as sshd would for the CI key, with stand-ins for what it may start."""
    bin_dir, notes_dir = tmp_path / "bin", tmp_path / "srv-notes"
    (notes_dir / "deploy" / "production").mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    for name, body in CI_COMMAND_STUBS.items():
        folder = notes_dir / "deploy" / "production" if name == "rollout.sh" else bin_dir
        (folder / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (folder / name).chmod(0o755)
    return subprocess.run(
        [str(PRODUCTION_DIR / "ci-command")],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "NOTES_DIR": str(notes_dir),
            "SSH_ORIGINAL_COMMAND": request,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    ("request_line", "expected"),
    [
        (
            f"rollout ghcr.io/owner/notes-api {SHA}",
            f"rollout.sh {SHA} NOTES_IMAGE=ghcr.io/owner/notes-api SKIP_PULL=",
        ),
        ("rollback", "rollout.sh rollback NOTES_IMAGE= SKIP_PULL=1"),
        ("mark-good", "rollout.sh mark-good NOTES_IMAGE= SKIP_PULL="),
        ("registry-login octo-cat", "docker login ghcr.io --username octo-cat --password-stdin"),
        ("registry-logout", "docker logout ghcr.io"),
        ("rsync --server -logDtprRze.iLsfxCIvu --delete . .", "rrsync -wo "),
    ],
)
def test_ci_command_allows_the_deploy_commands(
    tmp_path: Path, request_line: str, expected: str
) -> None:
    """Each command the workflow sends reaches exactly one fixed program."""
    run = ci_command(tmp_path, request_line)
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith(expected)


@pytest.mark.parametrize(
    "request_line",
    [
        "",
        "bash",
        "docker ps",
        "rollback now",
        f"rollout ghcr.io/owner/notes-api {SHA} && reboot",
        f"rollout evil.example/owner/notes-api {SHA}",
        "rollout ghcr.io/owner/notes-api latest",
        "registry-login $(id)",
        "rsync -e sh . .",
        "/srv/notes/deploy/production/rollout.sh rollback",
    ],
)
def test_ci_command_refuses_everything_else(tmp_path: Path, request_line: str) -> None:
    """A stolen CI key gets no shell, no docker, no other script and no extra arguments."""
    run = ci_command(tmp_path, request_line)
    assert run.returncode == 1
    assert run.stdout == ""
    assert "not allowed" in run.stderr


def start_worker(
    redis_url: str, database: Path
) -> tuple[subprocess.Popen[str], list[str], threading.Thread]:
    """Start `python -m notes_api.worker` and wait (up to 20 s) until arq says it started."""
    environment = {
        **os.environ,
        "NOTES_ENVIRONMENT": "test",
        "NOTES_REDIS_URL": redis_url,
        "NOTES_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
        "PYTHONPATH": str(PROJECT_DIR / "src"),
    }
    worker = subprocess.Popen(
        [sys.executable, "-m", "notes_api.worker"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.extend(worker.stdout or []), daemon=True)
    reader.start()
    deadline = time.monotonic() + 20
    while not any("Starting worker" in line for line in lines) and time.monotonic() < deadline:
        time.sleep(0.1)
    return worker, lines, reader


@pytest.mark.redis
def test_worker_stops_cleanly_on_sigterm(redis_url: str, tmp_path: Path) -> None:
    """docker stop sends SIGTERM to PID 1: the worker must exit, not wait for SIGKILL."""
    worker, lines, reader = start_worker(redis_url, tmp_path / "worker.db")
    worker.send_signal(signal.SIGTERM)
    try:
        return_code = worker.wait(timeout=10)
    finally:
        worker.kill()
    reader.join(timeout=5)
    assert return_code == 0, "".join(lines[-20:])
    assert any("shutdown on SIGTERM" in line for line in lines)


workflows_present = pytest.mark.skipif(
    not (WORKFLOWS_DIR / "notes-api.yml").exists(), reason="outside the course repository"
)


@workflows_present
def test_deploy_runs_after_every_check_and_only_on_main() -> None:
    """deploy needs push, push needs scan, scan needs build, build needs the checks."""
    jobs = load(WORKFLOWS_DIR / "notes-api.yml")["jobs"]
    assert jobs["build"]["needs"] == ["lint", "types", "test"]
    assert (jobs["scan"]["needs"], jobs["push"]["needs"], jobs["deploy"]["needs"]) == (
        "build",
        "scan",
        "push",
    )
    assert "refs/heads/main" in jobs["push"]["if"]
    assert jobs["deploy"]["environment"]["name"] == "production"
    assert jobs["deploy"]["if"] == "vars.NOTES_HOST != ''"


@workflows_present
def test_workflows_use_only_the_documented_secrets() -> None:
    """The workflows use exactly the secrets and variables DEPLOY.md documents."""
    text = "".join(path.read_text() for path in WORKFLOWS_DIR.glob("notes-api*.yml"))
    secrets = set(re.findall(r"secrets\.([A-Z_]+)", text))
    variables = set(re.findall(r"vars\.([A-Z_]+)", text))
    assert secrets == {"GITHUB_TOKEN", "DEPLOY_SSH_KEY", "DEPLOY_KNOWN_HOSTS"}
    assert variables == {"NOTES_HOST"}
    deploy_guide = PROJECT_DIR / "DEPLOY.md"
    if deploy_guide.exists():
        guide = deploy_guide.read_text()
        assert all(name in guide for name in (secrets - {"GITHUB_TOKEN"}) | variables)


@workflows_present
def test_uptime_check_is_scheduled() -> None:
    """The uptime workflow runs on a schedule and needs no permissions."""
    workflow = load(WORKFLOWS_DIR / "notes-api-uptime.yml")
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["schedule"][0]["cron"].endswith("* * * *")
    assert workflow["permissions"] == {}
