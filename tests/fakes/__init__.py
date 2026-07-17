"""Test doubles that speak the real wire protocol — no mocked transport."""

from tests.fakes.fake_agent import SUPPORTED_COMMAND_TYPES, FakeAgent, FakeAgentError

__all__ = ["SUPPORTED_COMMAND_TYPES", "FakeAgent", "FakeAgentError"]
