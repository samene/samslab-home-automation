"""Parse and query the real Prometheus ``/metrics`` text-exposition output.

Uses ``prometheus_client``'s own parser rather than hand-rolling one — the
same library that produces the metrics on the server side.
"""

from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families


def metric_value(text: str, name: str, **labels: str) -> float | None:
    """Return one sample's value from raw Prometheus text, or ``None`` if absent.

    ``name`` must be the exact exposed metric name (e.g. ``commands_received_total``,
    not the family name ``commands_received``). ``labels`` must match exactly —
    a metric with additional unspecified labels does not match.
    """
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name != name:
                continue
            exact_label_match = len(sample.labels) == len(labels) and all(
                sample.labels.get(key) == value for key, value in labels.items()
            )
            if not labels or exact_label_match:
                return float(sample.value)
    return None


def all_samples(text: str, name: str) -> list[tuple[dict[str, str], float]]:
    """Every sample for a given exact metric name, as (labels, value) pairs."""
    return [
        (dict(sample.labels), float(sample.value))
        for family in text_string_to_metric_families(text)
        for sample in family.samples
        if sample.name == name
    ]
