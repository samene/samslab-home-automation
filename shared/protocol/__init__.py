"""The versioned WebSocket wire protocol shared by the cloud server and the agent.

Nothing here is transport-specific: no WebSocket client/server library, no
FastAPI, no domain concept beyond the envelope/payload shapes themselves.
"""
