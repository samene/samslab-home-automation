"""The Command Dispatcher: delivers Commands to connected devices over the WebSocket Gateway.

Coordination only. It never executes a command, never knows command
semantics beyond ``command_type``/``payload`` as opaque values, and never
accesses a repository directly — it talks only to the Application Layer
(``CommandApplicationService``) and the WebSocket Gateway's ``SessionManager``,
the same seams REST and the gateway itself already use.
"""
