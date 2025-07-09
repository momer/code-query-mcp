"""Search analytics and monitoring module."""

from .search_analytics import SearchAnalytics
from .analytics_models import (
    QueryLogEntry,
    QueryStatus,
    QueryPerformanceMetrics,
    SlowQuery,
    FailedQuery,
    SearchTerm,
    SearchInsights
)
from .metrics_collector import MetricsCollector
from .analytics_storage import AnalyticsStorage

__all__ = [
    'SearchAnalytics',
    'QueryLogEntry',
    'QueryStatus',
    'QueryPerformanceMetrics',
    'SlowQuery',
    'FailedQuery',
    'SearchTerm',
    'SearchInsights',
    'MetricsCollector',
    'AnalyticsStorage'
]