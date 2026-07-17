# Observability

## Purpose

Make behavior, health, and failures diagnosable without exposing secrets.

## Scope

Server, agent, database, storage integration, and deployment telemetry.

## Architecture

Services emit structured JSON logs with timestamp, level, component, event name, correlation ID, request ID, agent ID where applicable, and sanitized context. Prometheus-format metrics are collected by VictoriaMetrics/vmagent and visualized in Grafana. Node exporter covers Pi host health.

Key signals: WebSocket connection state/age/reconnects; command queue depth, latency, failures, and duplicates; SQLite/spool size and replay age; driver errors; upload outcomes; API latency/errors; database pool/query health; disk, CPU, memory, temperature, and clock skew. Trace/correlation IDs flow from UI request through command to agent result.

## Design Decisions

Logs explain events, metrics detect trends, and audit records explain security-sensitive mutations. Metric labels must have bounded cardinality; command UUIDs and unbounded device values are not labels.

## Future Considerations

Add alert routing, SLOs, distributed tracing, synthetic agent checks, and redaction testing.

## Open Questions

Which availability and command-latency SLOs justify paging?

## References

- [Deployment](DEPLOYMENT.md)
- [Security](SECURITY.md)
