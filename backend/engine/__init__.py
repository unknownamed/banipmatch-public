"""Dispatch-engine entry point; no API, database, or external actions."""
from .solver import EngineInputError, solve

__all__ = ["EngineInputError", "solve"]
