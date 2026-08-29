from __future__ import annotations

import os


class MissingUserAgentError(ValueError):
    pass


def resolve_user_agent(explicit: str | None = None) -> str:
    value = explicit if explicit is not None else os.environ.get("SEC_EDGAR_USER_AGENT")
    if value is None or not value.strip():
        raise MissingUserAgentError(
            "Set SEC_EDGAR_USER_AGENT to a descriptive contact string, such as "
            "'Name email@example.com'. SEC requires it for automated requests."
        )
    return value.strip()
