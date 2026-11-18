"""Log redaction: secrets must never reach log files (OWASP API8, and plain good sense)."""

import logging
import re

SENSITIVE_KEYS = ("password", "token", "secret", "authorization", "api_key", "cookie")
REDACTED = "[REDACTED]"
PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),  # Authorization header values
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),  # anything shaped like a JWT
    re.compile(r"\bnk_[A-Za-z0-9_-]{16,}"),  # our API keys
    re.compile(  # key=value pairs (but leave "Bearer ..." to the first pattern)
        rf"(?i)\b((?:{'|'.join(SENSITIVE_KEYS)})\w*\s*[=:]\s*)(?!bearer\b|\[REDACTED\])[^\s,;&]+"
    ),
]


def redact_text(text: str) -> str:
    """Replace secrets in a string (prefixes such as 'Bearer ' or 'password=' are kept)."""
    for pattern in PATTERNS:
        replacement = rf"\g<1>{REDACTED}" if pattern.groups else REDACTED
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: object) -> object:
    """Redact a mapping value whose key looks sensitive; recurse into nested mappings."""
    if isinstance(value, dict):
        return {inner: redact_value(inner, item) for inner, item in value.items()}
    if any(word in key.lower() for word in SENSITIVE_KEYS):
        return REDACTED
    return redact_text(value) if isinstance(value, str) else value


class RedactingFilter(logging.Filter):
    """Rewrite each record's message and arguments before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact in place; never drop the record."""
        if isinstance(record.args, dict):
            record.args = {key: redact_value(key, value) for key, value in record.args.items()}
        message = record.getMessage() if record.args else str(record.msg)
        record.msg, record.args = redact_text(message), None
        return True


def install_redaction(logger_names: tuple[str, ...] = ("notes_api", "uvicorn.access")) -> None:
    """Attach the filter to the app's loggers (idempotent)."""
    for name in logger_names:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactingFilter) for existing in logger.filters):
            logger.addFilter(RedactingFilter())
