"""The terminal plugin: one interactive PTY session per device, streamed over
the existing agent<->server WebSocket connection.

Not a ``CommandHandler`` — see ``app/plugins/terminal/service.py`` for why a
persistent, bidirectional shell session doesn't fit the Command Framework's
request/reply lifecycle, and ``docs/agent/TERMINAL.md`` for the full design.
"""
