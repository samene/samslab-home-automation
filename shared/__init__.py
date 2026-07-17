"""Cross-process contracts shared between Sam's Lab Cloud and the Raspberry Pi agent.

This package must never depend on anything transport- or infrastructure-specific
(FastAPI, SQLAlchemy, GPIO libraries, ...) — only ``pydantic``. Both the cloud
server (``server/app/websocket/``) and the agent (``agent/app/protocol/``)
import from here so the wire format has exactly one source of truth.
"""
