"""Sam's Lab end-to-end verification framework: integration, e2e, and load tests.

Runs the real cloud server (a real TCP socket, a real SQLite database) against
a real WebSocket protocol client (``tests.fakes.FakeAgent``) — no mocked
transport anywhere. See ``docs/development/INTEGRATION_TESTING.md``.
"""
