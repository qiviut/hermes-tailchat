from __future__ import annotations

import re

_TRANSIENT_NEEDLES = (
    'rate limit',
    'rate_limit',
    'too many requests',
    '429',
    'retry after',
    'temporarily unavailable',
    'temporary failure',
    'overloaded',
    'timeout',
    'timed out',
    'connection reset',
    'connection aborted',
    'connection refused',
    'connection error',
    'try again',
    'quota',
    '503',
    '529',
)

_RETRY_AFTER_PATTERNS = (
    r'retry after\s*(\d+)\s*s',
    r'retry in\s*(\d+)\s*s',
    r'after\s*(\d+)\s*seconds',
    r'please try again in\s*(\d+)\s*s',
)


def is_transient_error(error_text: str | None) -> bool:
    if not error_text:
        return False
    lowered = error_text.lower()
    return any(needle in lowered for needle in _TRANSIENT_NEEDLES)


def is_rate_limited_error(error_text: str | None) -> bool:
    if not error_text:
        return False
    lowered = error_text.lower()
    return any(needle in lowered for needle in ('rate limit', 'rate_limit', 'too many requests', '429'))


def can_auto_retry_error(error_text: str | None) -> bool:
    return is_transient_error(error_text) and not is_rate_limited_error(error_text)


def parse_retry_after_seconds(error_text: str | None) -> int | None:
    if not error_text:
        return None
    lowered = error_text.lower()
    for pattern in _RETRY_AFTER_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            try:
                return max(1, int(match.group(1)))
            except (TypeError, ValueError):
                return None
    return None
