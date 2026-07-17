"""Auth domain: authentication and role/permission-based authorization.

Independent of transport — nothing here imports FastAPI. The same
``AuthService`` (and the pure ``decode_principal`` function backing it) is
meant to authenticate REST, a future WebSocket handshake, gRPC, or MQTT alike.
"""
