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
SCRIPTS = ("dc", "lib.sh", "backup.sh", "rollout.sh", "bootstrap.sh")
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


def test_caddy_redirects_sets_hsts_and_hides_metrics() -> None:
    """The Caddyfile has the ACME e-mail, HSTS, retries and a hidden /metrics."""
    caddyfile = (PRODUCTION_DIR / "Caddyfile").read_text()
    assert "email {$ACME_EMAIL}" in caddyfile
    assert 'Strict-Transport-Security "max-age=31536000"' in caddyfile
    assert "respond @internal 404" in caddyfile
    assert "lb_try_duration" in caddyfile
    assert "{$NOTES_SITE} {" in caddyfile  # no default: production needs a real hostname


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
