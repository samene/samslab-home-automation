"""Pure retry-policy math: exponential backoff and the retry/give-up decision.

Retries apply only to transport failures — a command that was never
acknowledged, or that could not be handed to the WebSocket Gateway at all.
Nothing here touches a command's persisted state; ``ack_manager.py`` and
``worker.py`` are what call ``CommandApplicationService`` based on what this
module decides.
"""

from __future__ import annotations


def should_retry(retry_count: int, max_retries: int) -> bool:
    """Return whether another retry attempt is allowed after ``retry_count`` attempts so far."""
    return retry_count < max_retries


def compute_backoff_seconds(retry_count: int, *, base_seconds: float, max_seconds: float) -> float:
    """Return the delay before the ``retry_count``-th retry: base, 2x, 4x, 8x, ... capped.

    ``retry_count`` is 1-indexed (the first retry uses ``base_seconds``).
    """
    backoff = base_seconds * (2.0 ** max(retry_count - 1, 0))
    return min(backoff, max_seconds)
