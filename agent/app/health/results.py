"""The three-state health vocabulary and result shapes shared by every check."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class HealthState(StrEnum):
    """Overall or per-check health state."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


#: Ordering used to combine several check results into one overall state.
_SEVERITY: Final[dict[HealthState, int]] = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.UNHEALTHY: 2,
}


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one named health check."""

    name: str
    state: HealthState
    detail: str | None = None


@dataclass(frozen=True)
class HealthReport:
    """The combined outcome of every health check, taken together."""

    state: HealthState
    checks: tuple[CheckResult, ...]


def combine_states(states: Iterable[HealthState]) -> HealthState:
    """Return the worst (most severe) state among ``states``, defaulting to HEALTHY."""
    worst = HealthState.HEALTHY
    for state in states:
        if _SEVERITY[state] > _SEVERITY[worst]:
            worst = state
    return worst
