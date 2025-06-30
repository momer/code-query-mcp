"""Search module for FTS5 query building and optimization."""

from .query_builder import FTS5QueryBuilder
from .query_strategies import (
    QueryStrategy,
    DefaultQueryStrategy,
    CodeAwareQueryStrategy,
    FallbackStrategy
)

__all__ = [
    'FTS5QueryBuilder',
    'QueryStrategy',
    'DefaultQueryStrategy', 
    'CodeAwareQueryStrategy',
    'FallbackStrategy'
]