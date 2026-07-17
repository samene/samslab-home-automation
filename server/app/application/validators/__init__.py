"""Centralized request validation shared across application services.

Controllers must not duplicate these rules with per-domain ``Query`` bounds;
an application service that accepts pagination or a sort token validates it
by calling into this package exactly once.
"""

from __future__ import annotations

from app.application.validators.pagination import PaginationParams
from app.application.validators.sorting import validate_sort_field

__all__ = ["PaginationParams", "validate_sort_field"]
