"""Compatibility helpers for discovering main-agent domains."""

from app.agents.registry import AGENT_SPECS


def list_domains() -> dict[str, str]:
    return {
        name: spec.description
        for name, spec in AGENT_SPECS.items()
    }
