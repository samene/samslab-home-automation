"""The browser-facing terminal transport: relays an interactive PTY session
between a human user's browser and the Raspberry Pi agent that hosts it.

Coordination only, exactly like ``app/dispatcher/`` — never executes a shell
command itself, never touches a repository directly. Its two cross-domain
calls are ``DeviceApplicationService`` (confirming a device exists, is
enabled, and is currently connected, the same Application Layer seam
``app/websocket/gateway.py`` uses) and the WebSocket Gateway's own
``SessionManager`` (to check agent connectivity and relay envelopes to it) —
this package never imports the Command Dispatcher, and a terminal session is
never modeled as a ``Command``: it is a persistent, bidirectional stream, not
a one-shot request/reply (see ``docs/agent/TERMINAL.md`` and
``docs/architecture/PROTOCOL.md``).
"""
