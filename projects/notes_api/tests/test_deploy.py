"""Deployment files and settings: checked statically, since CI has no cluster to deploy to."""

import re
from pathlib import Path
from typing import Any

import fakeredis
import pytest
import yaml
from pydantic import SecretStr

from helpers import PROJECT_DIR
from notes_api import db, worker
from notes_api.core.config import Settings

pytestmark = pytest.mark.anyio


def load_yaml(relative: str) -> list[dict[str, Any]]:
    """Every document of a YAML file in the project."""
    return list(yaml.safe_load_all((PROJECT_DIR / relative).read_text(encoding="utf-8")))


def test_dockerfile_is_multi_stage_and_unprivileged() -> None:
    """Build and runtime stages; the final user is not root; a health check is declared."""
    dockerfile = (PROJECT_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM ", dockerfile, re.M)) >= 3
    assert re.findall(r"^USER (\S+)", dockerfile, re.M)[-1] not in ("root", "0")
    assert "HEALTHCHECK" in dockerfile and "--no-dev" in dockerfile


def test_compose_stack_order_and_health() -> None:
    """Migrations run before api/worker; backing services and the worker have health checks."""
    services = load_yaml("compose.yaml")[0]["services"]
    assert set(services) == {"db", "redis", "migrate", "api", "worker", "proxy"}
    for name in ("api", "worker"):
        depends = services[name]["depends_on"]
        assert depends["migrate"]["condition"] == "service_completed_successfully"
    for name in ("db", "redis", "worker", "proxy"):
        assert "healthcheck" in services[name]
    assert "ports" not in services["api"]  # only the proxy is published
    assert services["api"]["read_only"] is True and services["api"]["cap_drop"] == ["ALL"]


def test_compose_secret_comes_from_an_ignored_file() -> None:
    """The JWT secret is a file under .secrets/, which git ignores."""
    secrets = load_yaml("compose.yaml")[0]["secrets"]
    assert secrets["notes_jwt_secret"]["file"].startswith("./.secrets/")


def test_kubernetes_api_probes_and_rollout() -> None:
    """Three probes, no unavailable pods during a rollout, enough time to shut down."""
    deployment = load_yaml("deploy/k8s/api-deployment.yaml")[0]
    spec = deployment["spec"]["template"]["spec"]
    container = spec["containers"][0]
    probes = {key for key in container if key.endswith("Probe")}
    assert probes == {"startupProbe", "readinessProbe", "livenessProbe"}
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 0
    assert spec["terminationGracePeriodSeconds"] > 20 and spec["securityContext"]["runAsNonRoot"]
    kinds = [doc["kind"] for doc in load_yaml("deploy/k8s/api-service.yaml")]
    assert kinds == ["Service", "HorizontalPodAutoscaler"]


def test_proxy_blocks_metrics_and_procfile_has_three_processes() -> None:
    """Caddy hides /metrics; the PaaS Procfile declares web, worker and release."""
    caddyfile = (PROJECT_DIR / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "respond @internal 404" in caddyfile and "reverse_proxy" in caddyfile
    procfile = (PROJECT_DIR / "Procfile").read_text(encoding="utf-8").splitlines()
    assert [line.split(":")[0] for line in procfile] == ["web", "worker", "release"]


def test_secrets_are_read_from_files(tmp_path: Path) -> None:
    """Docker/Kubernetes secret files fill settings (a file per variable, name case-insensitive)."""
    (tmp_path / "notes_jwt_secret").write_text("from-a-secret-file-" + "x" * 20, encoding="utf-8")
    settings = Settings(_env_file=None, _secrets_dir=tmp_path)
    assert settings.jwt_secret is not None
    assert settings.jwt_secret.get_secret_value().startswith("from-a-secret-file-")


def test_pgbouncer_mode_disables_statement_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind PgBouncer in transaction mode, asyncpg must not cache prepared statements."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(db, "create_async_engine", lambda url, **kwargs: captured.update(kwargs))
    url = SecretStr("postgresql+asyncpg://notes:notes@pgbouncer:6432/notes")
    db.create_engine_from_settings(
        Settings(_env_file=None, database_url=url, database_pgbouncer=True)
    )
    assert captured["connect_args"]["statement_cache_size"] == 0
    assert captured["connect_args"]["prepared_statement_cache_size"] == 0


async def test_worker_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """--check passes while a worker keeps its health key fresh, fails when it is gone."""
    fake = fakeredis.FakeAsyncRedis()
    monkeypatch.setattr(worker.redis_asyncio, "from_url", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(fake, "aclose", lambda: _noop())
    settings = Settings(_env_file=None)
    assert await worker.worker_is_healthy(settings) is False
    await fake.set(worker.HEALTH_CHECK_KEY, "j_complete=3", px=31_000)
    assert await worker.worker_is_healthy(settings) is True


async def _noop() -> None:
    """Keep the fake client open between the two checks."""
