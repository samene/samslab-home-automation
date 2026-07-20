"""E2E Scenario 1: agent connects -> create system.echo -> result -> DB -> metrics -> logs.

This test builds its own server (rather than using the shared ``server``
fixture) so it can wrap startup in a ``LogCapture`` — logging must be
captured from the moment the app's lifespan calls ``configure_logging()``.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes.fake_agent import FakeAgent
from tests.utils.logs import LogCapture
from tests.utils.metrics import metric_value
from tests.utils.server_harness import default_test_settings, run_server
from tests.utils.waiters import wait_for_command_status


async def test_agent_connects_echo_completes_db_metrics_and_logs_all_verify(
    tmp_path: Path,
) -> None:
    """The full happy path, with every observability surface checked at the end."""
    settings = default_test_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'server.db'}")

    with LogCapture() as logs:
        async with run_server(settings) as server:
            # Agent connects.
            device_id = await server.register_device(display_name="Scenario 1 Device")
            token = server.issue_device_token(device_id)
            agent = FakeAgent()
            await agent.connect(server.ws_url, token)

            metrics_before = await server.metrics_text()
            dispatched_before = metric_value(metrics_before, "commands_dispatched_total") or 0.0
            results_before = (
                metric_value(
                    metrics_before, "messages_received_total", message_type="COMMAND_RESULT"
                )
                or 0.0
            )

            # Create system.echo.
            command_id = await server.create_command(
                device_id, "system.echo", payload={"hello": "world"}
            )

            # Result returned.
            final = await wait_for_command_status(server, command_id, "COMPLETED")

            # Verify database: the command's persisted row reflects the real result.
            assert final["result"]["success"] is True
            assert final["result"]["result"] == {"hello": "world"}
            assert final["status"] == "COMPLETED"

            # Verify metrics: real Prometheus counters moved by exactly this command.
            metrics_after = await server.metrics_text()
            dispatched_after = metric_value(metrics_after, "commands_dispatched_total")
            results_after = metric_value(
                metrics_after, "messages_received_total", message_type="COMMAND_RESULT"
            )
            connected_devices = metric_value(metrics_after, "connected_devices")
            assert dispatched_after == dispatched_before + 1
            assert results_after == results_before + 1
            assert connected_devices == 1

            await agent.disconnect()

    # Verify logs: structured JSON events carry the documented correlation fields.
    events = logs.events()
    assert events, "expected at least one structured log event to be captured"
    request_completed = [event for event in events if event.get("event") == "request_completed"]
    assert request_completed
    assert all("correlation_id" in event for event in request_completed)
    assert all("request_id" in event for event in request_completed)

    connected_events = [event for event in events if event.get("event") == "websocket_connected"]
    assert connected_events
    assert connected_events[0]["device_id"] == str(device_id)
