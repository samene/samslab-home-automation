"""Failures raised by the agent's lifecycle state machine."""

from __future__ import annotations


class InvalidStateTransitionError(Exception):
    """Raised when a transition isn't in the current state's allowed target set."""
