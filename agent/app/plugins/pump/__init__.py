"""The pump plugin: fires a short GPIO pulse into a timer relay module.

The Raspberry Pi never controls watering duration — a timer relay wired to
the configured GPIO line owns that entirely. The agent's only job is a single
command, ``pump.trigger``, which pulses the line for a configured duration to
fire the relay's own timer. See ``docs/agent/PUMP.md``.
"""

from __future__ import annotations
