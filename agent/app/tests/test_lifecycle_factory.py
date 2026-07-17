"""Tests for the lifecycle composition root."""

from __future__ import annotations

from app.health.service import HealthService
from app.lifecycle.factory import build_agent, build_health_service
from app.lifecycle.orchestrator import Agent
from app.plugins.registry import PluginManager
from app.tests.conftest import make_settings


def test_build_agent_returns_a_ready_agent() -> None:
    """build_agent wires every subsystem into a usable Agent."""
    agent = build_agent(make_settings())
    assert isinstance(agent, Agent)


def test_build_agent_accepts_a_custom_plugin_manager() -> None:
    """An explicitly passed PluginManager is used instead of an empty default."""
    plugin_manager = PluginManager()
    agent = build_agent(make_settings(), plugin_manager=plugin_manager)
    assert isinstance(agent, Agent)


def test_build_health_service_returns_a_usable_service() -> None:
    """build_health_service composes a HealthService that can run a check."""
    service = build_health_service(make_settings())
    assert isinstance(service, HealthService)
    report = service.check()
    assert report.checks
