"""Analytics data models and DTOs."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class QueryStatus(Enum):
    """Status of a search query execution."""
    SUCCESS = "success"
    NO_RESULTS = "no_results"
    FALLBACK_USED = "fallback_used"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class QueryLogEntry:
    """Single search query log entry."""
    query_id: str
    query_text: str
    dataset: str
    normalized_query: str
    fts_query: str
    status: QueryStatus
    result_count: int
    duration_ms: float
    timestamp: datetime
    error_message: Optional[str] = None
    fallback_attempted: bool = False
    client_info: Optional[Dict[str, Any]] = None


@dataclass
class QueryPerformanceMetrics:
    """Aggregated performance metrics for a query pattern."""
    query_pattern: str
    avg_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    total_executions: int
    success_rate: float
    avg_result_count: float
    time_period: str  # e.g., "hour", "day", "week"


@dataclass
class SlowQuery:
    """Slow query identification."""
    query_text: str
    dataset: str
    duration_ms: float
    result_count: int
    timestamp: datetime
    execution_plan: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)


@dataclass
class FailedQuery:
    """Failed query for analysis."""
    query_text: str
    dataset: str
    error_type: str
    error_message: str
    failure_count: int
    first_seen: datetime
    last_seen: datetime
    suggested_alternatives: List[str] = field(default_factory=list)


@dataclass
class SearchTerm:
    """Popular search term with usage stats."""
    term: str
    search_count: int
    unique_users: int
    avg_result_count: float
    success_rate: float
    datasets: List[str]
    first_seen: datetime
    last_seen: datetime


@dataclass
class SearchInsights:
    """Aggregated search insights."""
    total_queries: int
    unique_queries: int
    avg_response_time_ms: float
    success_rate: float
    fallback_rate: float
    no_results_rate: float
    top_queries: List[Dict[str, Any]]
    top_datasets: List[Dict[str, Any]]
    query_volume_trend: List[Dict[str, Any]]
    time_period: str