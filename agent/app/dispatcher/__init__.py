"""Routes an incoming envelope to the handler registered for its message type."""

from app.dispatcher.dispatcher import MessageDispatcher, MessageHandler

__all__ = ["MessageDispatcher", "MessageHandler"]
