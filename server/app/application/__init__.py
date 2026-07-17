"""Application layer: orchestrates cross-domain use cases.

This is not a business domain. It coordinates domain services to implement
high-level use cases (e.g. "create a command, which requires confirming its
target device exists and is enabled"). Domain services never call one
another; any workflow that spans more than one domain belongs here.

REST controllers depend only on this layer's application services and never
call a domain service or repository directly.
"""
