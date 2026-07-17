"""The agent WebSocket gateway: a transport layer only.

Maintains authenticated, persistent per-device sessions and delivers
versioned protocol messages. It never executes commands, never touches GPIO,
and never accesses a repository directly — the only cross-domain call it
makes is through the Application Layer (``DeviceApplicationService``), the
same seam a future MQTT or gRPC transport would use.
"""
