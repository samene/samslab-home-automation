"""Protocol message construction/parsing for HELLO, WELCOME, PING, PONG, ERROR, GOODBYE.

COMMAND is intentionally unhandled here — dispatching it into real business
logic is future work (see ``docs/architecture/PROTOCOL.md``). No pure function
in this package does network I/O; that lives in ``app.connection``.
"""

from app.protocol.handlers import (
    build_goodbye,
    build_hello,
    build_ping,
    build_pong,
    parse_error,
    parse_goodbye,
    parse_ping,
    parse_pong,
    parse_welcome,
)

__all__ = [
    "build_goodbye",
    "build_hello",
    "build_ping",
    "build_pong",
    "parse_error",
    "parse_goodbye",
    "parse_ping",
    "parse_pong",
    "parse_welcome",
]
