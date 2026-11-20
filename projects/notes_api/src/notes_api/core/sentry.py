"""Error tracking with Sentry: off unless NOTES_SENTRY_DSN is set; secrets are scrubbed first."""

import importlib.util
import logging
from typing import TYPE_CHECKING, Any

from notes_api import __version__
from notes_api.core.config import Settings
from notes_api.core.logging import redact_value

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = logging.getLogger("notes_api.sentry")


def scrub_event(event: Event, _hint: Hint) -> Event | None:
    """before_send hook: redact headers, cookies, bodies and messages before they leave."""
    request: dict[str, Any] = event.get("request", {})
    for part in ("headers", "cookies", "data", "query_string"):
        if isinstance(request.get(part), dict):
            request[part] = {key: redact_value(key, value) for key, value in request[part].items()}
        elif isinstance(request.get(part), str):
            request[part] = redact_value(part, request[part])
    if isinstance(event.get("logentry"), dict):
        event["logentry"] = redact_value("logentry", event["logentry"])  # type: ignore[typeddict-item]
    return event


def install_sentry(settings: Settings, transport: Any = None) -> bool:
    """Initialise the Sentry SDK (FastAPI integration auto-enabled); False when disabled."""
    if settings.sentry_dsn is None:
        return False
    if importlib.util.find_spec("sentry_sdk") is None:
        logger.warning("NOTES_SENTRY_DSN is set but sentry-sdk is not installed")
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        release=f"notes-api@{__version__}",
        traces_sample_rate=0.0,  # tracing goes to OpenTelemetry
        before_send=scrub_event,  # the SDK's defaults send no IPs or cookies; this scrubs the rest
        transport=transport,  # tests pass a fake; production sends to the DSN
    )
    return True
