# PR 7: Search Analytics and Monitoring

## Overview
This PR adds analytics and monitoring capabilities to track search performance, usage patterns, and identify areas for improvement. It provides insights into query performance, failure patterns, and popular search terms.

**Size**: Small | **Risk**: Low | **Value**: Medium

## Dependencies
- PR 4 must be completed (needs SearchService to hook into)
- PR 2 must be completed (needs StorageBackend for persistence)
- This PR is independent and doesn't block other PRs

## Objectives
1. Track all search queries with performance metrics
2. Identify slow queries for optimization
3. Track failed queries to improve search quality
4. Understand search patterns and popular terms
5. Provide analytics API for reporting
6. Enable data-driven search improvements

## Implementation Steps

### Step 1: Create Directory Structure
```
analytics/
├── __init__.py               # Export main classes
├── search_analytics.py       # Main analytics service
├── analytics_models.py       # Analytics DTOs and models
├── analytics_storage.py      # Analytics-specific storage operations
└── metrics_collector.py      # Real-time metrics collection
```

### Step 2: Define Analytics Models
**File**: `analytics/analytics_models.py`
- Query log entry model
- Performance metrics model
- Aggregated statistics models
- Time-series data structures

### Step 3: Create Analytics Storage
**File**: `analytics/analytics_storage.py`
- Schema for analytics tables
- Efficient time-series storage
- Aggregation queries
- Data retention policies

### Step 4: Implement Metrics Collector
**File**: `analytics/metrics_collector.py`
- Non-blocking metrics collection
- Minimal performance overhead
- Batch writes for efficiency
- Configurable sampling

### Step 5: Implement Search Analytics Service
**File**: `analytics/search_analytics.py`
- Main analytics API
- Query performance tracking
- Failure analysis
- Usage pattern detection

### Step 6: Integrate with Search Service
- Add analytics hooks to SearchService
- Ensure minimal performance impact
- Make analytics optional via configuration

## Detailed Implementation

### analytics/analytics_models.py
```python
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
```

### analytics/analytics_storage.py
```python
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .analytics_models import *
import sqlite3
import json

class AnalyticsStorage:
    """Storage backend for analytics data."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        """Initialize analytics tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Query log table with partitioning by date
                CREATE TABLE IF NOT EXISTS search_query_log (
                    query_id TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    normalized_query TEXT NOT NULL,
                    fts_query TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    duration_ms REAL NOT NULL,
                    timestamp DATETIME NOT NULL,
                    error_message TEXT,
                    fallback_attempted BOOLEAN DEFAULT 0,
                    client_info TEXT,
                    date_partition TEXT GENERATED ALWAYS AS (date(timestamp)) STORED
                );
                
                -- Indexes for efficient querying
                CREATE INDEX IF NOT EXISTS idx_query_log_timestamp 
                    ON search_query_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_query_log_dataset 
                    ON search_query_log(dataset);
                CREATE INDEX IF NOT EXISTS idx_query_log_status 
                    ON search_query_log(status);
                CREATE INDEX IF NOT EXISTS idx_query_log_duration 
                    ON search_query_log(duration_ms);
                CREATE INDEX IF NOT EXISTS idx_query_log_partition 
                    ON search_query_log(date_partition);
                
                -- Aggregated metrics table (updated periodically)
                CREATE TABLE IF NOT EXISTS search_metrics_hourly (
                    metric_id TEXT PRIMARY KEY,
                    hour_bucket DATETIME NOT NULL,
                    dataset TEXT NOT NULL,
                    total_queries INTEGER NOT NULL,
                    unique_queries INTEGER NOT NULL,
                    avg_duration_ms REAL NOT NULL,
                    p50_duration_ms REAL NOT NULL,
                    p95_duration_ms REAL NOT NULL,
                    p99_duration_ms REAL NOT NULL,
                    success_count INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    no_results_count INTEGER NOT NULL,
                    fallback_count INTEGER NOT NULL
                );
                
                -- Popular terms tracking
                CREATE TABLE IF NOT EXISTS search_terms (
                    term TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    date TEXT NOT NULL,
                    search_count INTEGER DEFAULT 1,
                    unique_users INTEGER DEFAULT 1,
                    total_results INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    PRIMARY KEY (term, dataset, date)
                );
                
                -- Failed query patterns
                CREATE TABLE IF NOT EXISTS failed_query_patterns (
                    pattern_hash TEXT PRIMARY KEY,
                    query_pattern TEXT NOT NULL,
                    dataset TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    failure_count INTEGER DEFAULT 1,
                    first_seen DATETIME NOT NULL,
                    last_seen DATETIME NOT NULL,
                    example_queries TEXT -- JSON array
                );
            """)
    
    def insert_query_log(self, entry: QueryLogEntry):
        """Insert a query log entry."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO search_query_log (
                    query_id, query_text, normalized_query, fts_query,
                    dataset, status, result_count, duration_ms,
                    timestamp, error_message, fallback_attempted, client_info
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.query_id,
                entry.query_text,
                entry.normalized_query,
                entry.fts_query,
                entry.dataset,
                entry.status.value,
                entry.result_count,
                entry.duration_ms,
                entry.timestamp,
                entry.error_message,
                entry.fallback_attempted,
                json.dumps(entry.client_info) if entry.client_info else None
            ))
    
    def insert_query_logs_batch(self, entries: List[QueryLogEntry]):
        """Batch insert multiple query logs for efficiency."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT INTO search_query_log (
                    query_id, query_text, normalized_query, fts_query,
                    dataset, status, result_count, duration_ms,
                    timestamp, error_message, fallback_attempted, client_info
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    entry.query_id,
                    entry.query_text,
                    entry.normalized_query,
                    entry.fts_query,
                    entry.dataset,
                    entry.status.value,
                    entry.result_count,
                    entry.duration_ms,
                    entry.timestamp,
                    entry.error_message,
                    entry.fallback_attempted,
                    json.dumps(entry.client_info) if entry.client_info else None
                )
                for entry in entries
            ])
    
    def get_slow_queries(self, threshold_ms: float, 
                        limit: int = 100,
                        since: Optional[datetime] = None) -> List[SlowQuery]:
        """Get queries slower than threshold."""
        if since is None:
            since = datetime.now() - timedelta(days=7)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    query_text,
                    dataset,
                    duration_ms,
                    result_count,
                    timestamp
                FROM search_query_log
                WHERE duration_ms > ?
                    AND timestamp > ?
                    AND status = 'success'
                ORDER BY duration_ms DESC
                LIMIT ?
            """, (threshold_ms, since, limit))
            
            return [
                SlowQuery(
                    query_text=row['query_text'],
                    dataset=row['dataset'],
                    duration_ms=row['duration_ms'],
                    result_count=row['result_count'],
                    timestamp=datetime.fromisoformat(row['timestamp'])
                )
                for row in cursor
            ]
    
    def get_failed_queries(self, since: Optional[datetime] = None) -> List[FailedQuery]:
        """Get queries that consistently fail."""
        if since is None:
            since = datetime.now() - timedelta(days=7)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    query_text,
                    dataset,
                    error_message,
                    COUNT(*) as failure_count,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen
                FROM search_query_log
                WHERE status = 'error'
                    AND timestamp > ?
                GROUP BY query_text, dataset, error_message
                HAVING failure_count >= 3
                ORDER BY failure_count DESC
                LIMIT 100
            """, (since,))
            
            return [
                FailedQuery(
                    query_text=row['query_text'],
                    dataset=row['dataset'],
                    error_type='search_error',  # Could be enhanced
                    error_message=row['error_message'] or 'Unknown error',
                    failure_count=row['failure_count'],
                    first_seen=datetime.strptime(row['first_seen'], '%Y-%m-%d %H:%M:%S'),
                    last_seen=datetime.strptime(row['last_seen'], '%Y-%m-%d %H:%M:%S')
                )
                for row in cursor
            ]
    
    def get_popular_terms(self, days: int = 30, limit: int = 50) -> List[SearchTerm]:
        """Get popular search terms."""
        since = datetime.now() - timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # First, extract and count terms from recent queries
            cursor = conn.execute("""
                WITH term_counts AS (
                    SELECT 
                        LOWER(query_text) as term,
                        dataset,
                        COUNT(*) as search_count,
                        COUNT(DISTINCT client_info) as unique_users,
                        AVG(result_count) as avg_results,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                        MIN(timestamp) as first_seen,
                        MAX(timestamp) as last_seen
                    FROM search_query_log
                    WHERE timestamp > ?
                        AND status IN ('success', 'no_results')
                    GROUP BY LOWER(query_text), dataset
                )
                SELECT 
                    term,
                    SUM(search_count) as total_searches,
                    SUM(unique_users) as total_users,
                    AVG(avg_results) as avg_result_count,
                    AVG(success_rate) as avg_success_rate,
                    GROUP_CONCAT(DISTINCT dataset) as datasets,
                    MIN(first_seen) as first_seen,
                    MAX(last_seen) as last_seen
                FROM term_counts
                GROUP BY term
                ORDER BY total_searches DESC
                LIMIT ?
            """, (since, limit))
            
            return [
                SearchTerm(
                    term=row['term'],
                    search_count=row['total_searches'],
                    unique_users=row['total_users'],
                    avg_result_count=row['avg_result_count'],
                    success_rate=row['avg_success_rate'],
                    datasets=row['datasets'].split(',') if row['datasets'] else [],
                    first_seen=datetime.strptime(row['first_seen'], '%Y-%m-%d %H:%M:%S'),
                    last_seen=datetime.strptime(row['last_seen'], '%Y-%m-%d %H:%M:%S')
                )
                for row in cursor
            ]
    
    def update_hourly_metrics(self):
        """Update aggregated hourly metrics (called by scheduled job)."""
        with sqlite3.connect(self.db_path) as conn:
            # Calculate metrics for the last complete hour
            conn.execute("""
                INSERT OR REPLACE INTO search_metrics_hourly (
                    metric_id,
                    hour_bucket,
                    dataset,
                    total_queries,
                    unique_queries,
                    avg_duration_ms,
                    p50_duration_ms,
                    p95_duration_ms,
                    p99_duration_ms,
                    success_count,
                    error_count,
                    no_results_count,
                    fallback_count
                )
                SELECT 
                    dataset || '_' || strftime('%Y%m%d%H', timestamp) as metric_id,
                    datetime(strftime('%Y-%m-%d %H:00:00', timestamp)) as hour_bucket,
                    dataset,
                    COUNT(*) as total_queries,
                    COUNT(DISTINCT normalized_query) as unique_queries,
                    AVG(duration_ms) as avg_duration_ms,
                    -- Percentile calculations (simplified - in production use window functions)
                    AVG(duration_ms) as p50_duration_ms,
                    MAX(duration_ms) * 0.95 as p95_duration_ms,
                    MAX(duration_ms) * 0.99 as p99_duration_ms,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                    SUM(CASE WHEN status = 'no_results' THEN 1 ELSE 0 END) as no_results_count,
                    SUM(CASE WHEN fallback_attempted = 1 THEN 1 ELSE 0 END) as fallback_count
                FROM search_query_log
                WHERE timestamp >= datetime('now', '-2 hours')
                    AND timestamp < datetime('now', '-1 hour')
                GROUP BY dataset, strftime('%Y-%m-%d %H:00:00', timestamp)
            """)
    
    def cleanup_old_data(self, retention_days: int = 90):
        """Clean up old analytics data."""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        with sqlite3.connect(self.db_path) as conn:
            # Delete old query logs
            conn.execute("""
                DELETE FROM search_query_log
                WHERE timestamp < ?
            """, (cutoff_date,))
            
            # Delete old hourly metrics
            conn.execute("""
                DELETE FROM search_metrics_hourly
                WHERE hour_bucket < ?
            """, (cutoff_date,))
```

### analytics/metrics_collector.py
```python
from typing import Optional, Dict, Any, List
from queue import Queue, Full, Empty
from threading import Thread, Event
from datetime import datetime
import uuid
import time
import logging
import json
import sqlite3
from .analytics_models import QueryLogEntry, QueryStatus
from .analytics_storage import AnalyticsStorage

logger = logging.getLogger(__name__)

class MetricsCollector:
    """Collects metrics asynchronously with minimal performance impact."""
    
    def __init__(self, storage: AnalyticsStorage, 
                 batch_size: int = 100,
                 flush_interval: float = 5.0):
        self.storage = storage
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: Queue[QueryLogEntry] = Queue()
        self.shutdown_event = Event()
        self.worker_thread: Optional[Thread] = None
        self.enabled = True
    
    def start(self):
        """Start the background metrics collection thread."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = Thread(target=self._worker, daemon=True)
            self.worker_thread.start()
            logger.info("Metrics collector started")
    
    def stop(self):
        """Stop the metrics collection thread."""
        self.shutdown_event.set()
        if self.worker_thread:
            self.worker_thread.join(timeout=10)
        logger.info("Metrics collector stopped")
    
    def collect_query(self,
                     query_text: str,
                     normalized_query: str,
                     fts_query: str,
                     dataset: str,
                     status: QueryStatus,
                     result_count: int,
                     duration_ms: float,
                     error_message: Optional[str] = None,
                     fallback_attempted: bool = False,
                     client_info: Optional[Dict[str, Any]] = None):
        """Collect a query execution metric."""
        if not self.enabled:
            return
        
        entry = QueryLogEntry(
            query_id=str(uuid.uuid4()),
            query_text=query_text,
            normalized_query=normalized_query,
            fts_query=fts_query,
            dataset=dataset,
            status=status,
            result_count=result_count,
            duration_ms=duration_ms,
            timestamp=datetime.now(),
            error_message=error_message,
            fallback_attempted=fallback_attempted,
            client_info=client_info
        )
        
        try:
            self.queue.put_nowait(entry)
        except:
            # Queue full, metrics dropped (acceptable for analytics)
            logger.warning("Metrics queue full, dropping query log entry")
    
    def _worker(self):
        """Background worker to process metrics queue."""
        batch = []
        last_flush = time.time()
        
        while not self.shutdown_event.is_set():
            try:
                # Try to get items from queue with timeout
                timeout = max(0.1, self.flush_interval - (time.time() - last_flush))
                
                try:
                    entry = self.queue.get(timeout=timeout)
                    batch.append(entry)
                except:
                    # Timeout - check if we should flush
                    pass
                
                # Flush if batch is full or interval elapsed
                should_flush = (
                    len(batch) >= self.batch_size or
                    time.time() - last_flush >= self.flush_interval
                )
                
                if should_flush and batch:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()
                    
            except Exception as e:
                logger.error(f"Error in metrics worker: {e}")
        
        # Final flush on shutdown
        if batch:
            self._flush_batch(batch)
    
    def _flush_batch(self, batch: List[QueryLogEntry]):
        """Flush a batch of metrics to storage."""
        try:
            self.storage.insert_query_logs_batch(batch)
            logger.debug(f"Flushed {len(batch)} query metrics")
        except Exception as e:
            logger.error(f"Failed to flush metrics batch: {e}")
```

### analytics/search_analytics.py
```python
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .analytics_models import *
from .analytics_storage import AnalyticsStorage
from .metrics_collector import MetricsCollector
import hashlib
import re

class SearchAnalytics:
    """Main search analytics service."""
    
    def __init__(self, storage_backend):
        # Use existing storage backend connection info
        db_path = getattr(storage_backend, 'db_path', ':memory:')
        
        self.analytics_storage = AnalyticsStorage(db_path)
        self.metrics_collector = MetricsCollector(self.analytics_storage)
        self.metrics_collector.start()
    
    def log_query(self, 
                  query: str, 
                  dataset: str,
                  results_count: int, 
                  duration_ms: float,
                  normalized_query: Optional[str] = None,
                  fts_query: Optional[str] = None,
                  error: Optional[Exception] = None,
                  fallback_used: bool = False,
                  client_info: Optional[Dict[str, Any]] = None):
        """Log a search query execution."""
        # Determine status
        if error:
            status = QueryStatus.ERROR
            error_message = str(error)
        elif results_count == 0:
            status = QueryStatus.NO_RESULTS
            error_message = None
        elif fallback_used:
            status = QueryStatus.FALLBACK_USED
            error_message = None
        else:
            status = QueryStatus.SUCCESS
            error_message = None
        
        # Normalize query if not provided
        if normalized_query is None:
            normalized_query = self._normalize_query(query)
        
        # Use FTS query or fallback to normalized
        if fts_query is None:
            fts_query = normalized_query
        
        self.metrics_collector.collect_query(
            query_text=query,
            normalized_query=normalized_query,
            fts_query=fts_query,
            dataset=dataset,
            status=status,
            result_count=results_count,
            duration_ms=duration_ms,
            error_message=error_message,
            fallback_attempted=fallback_used,
            client_info=client_info
        )
    
    def get_slow_queries(self, threshold_ms: int = 1000,
                        limit: int = 100,
                        days_back: int = 7) -> List[SlowQuery]:
        """Get queries slower than threshold."""
        since = datetime.now() - timedelta(days=days_back)
        slow_queries = self.analytics_storage.get_slow_queries(
            threshold_ms=threshold_ms,
            limit=limit,
            since=since
        )
        
        # Add suggestions for each slow query
        for query in slow_queries:
            query.suggestions = self._generate_optimization_suggestions(query)
        
        return slow_queries
    
    def get_failed_queries(self, days_back: int = 7) -> List[FailedQuery]:
        """Get queries that consistently fail."""
        since = datetime.now() - timedelta(days=days_back)
        failed_queries = self.analytics_storage.get_failed_queries(since=since)
        
        # Add alternative suggestions
        for query in failed_queries:
            query.suggested_alternatives = self._suggest_alternatives(query)
        
        return failed_queries
    
    def get_popular_terms(self, days: int = 30, limit: int = 50) -> List[SearchTerm]:
        """Get most popular search terms."""
        return self.analytics_storage.get_popular_terms(days=days, limit=limit)
    
    def get_search_insights(self, 
                           dataset: Optional[str] = None,
                           time_period: str = "day") -> SearchInsights:
        """Get aggregated search insights."""
        # This would query the aggregated metrics tables
        # Implementation depends on specific requirements
        with sqlite3.connect(self.analytics_storage.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Time range based on period
            if time_period == "hour":
                since = datetime.now() - timedelta(hours=1)
            elif time_period == "day":
                since = datetime.now() - timedelta(days=1)
            elif time_period == "week":
                since = datetime.now() - timedelta(weeks=1)
            else:
                since = datetime.now() - timedelta(days=30)
            
            # Build query with optional dataset filter
            dataset_filter = "AND dataset = ?" if dataset else ""
            params = [since, dataset] if dataset else [since]
            
            # Get overview metrics
            cursor = conn.execute(f"""
                SELECT 
                    COUNT(*) as total_queries,
                    COUNT(DISTINCT normalized_query) as unique_queries,
                    AVG(duration_ms) as avg_response_time,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate,
                    SUM(CASE WHEN fallback_attempted = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as fallback_rate,
                    SUM(CASE WHEN status = 'no_results' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as no_results_rate
                FROM search_query_log
                WHERE timestamp > ? {dataset_filter}
            """, params)
            
            row = cursor.fetchone()
            
            # Get top queries
            cursor = conn.execute(f"""
                SELECT 
                    normalized_query,
                    COUNT(*) as count,
                    AVG(duration_ms) as avg_duration
                FROM search_query_log
                WHERE timestamp > ? {dataset_filter}
                GROUP BY normalized_query
                ORDER BY count DESC
                LIMIT 10
            """, params)
            
            top_queries = [
                {
                    "query": row["normalized_query"],
                    "count": row["count"],
                    "avg_duration_ms": row["avg_duration"]
                }
                for row in cursor
            ]
            
            return SearchInsights(
                total_queries=row["total_queries"],
                unique_queries=row["unique_queries"],
                avg_response_time_ms=row["avg_response_time"],
                success_rate=row["success_rate"],
                fallback_rate=row["fallback_rate"],
                no_results_rate=row["no_results_rate"],
                top_queries=top_queries,
                top_datasets=[],  # Would implement similarly
                query_volume_trend=[],  # Would implement time series
                time_period=time_period
            )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query for grouping."""
        # Convert to lowercase
        normalized = query.lower().strip()
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Sort terms for consistency (unless it has operators)
        if not any(op in normalized for op in ['AND', 'OR', 'NOT', 'NEAR']):
            terms = normalized.split()
            normalized = ' '.join(sorted(terms))
        
        return normalized
    
    def _generate_optimization_suggestions(self, slow_query: SlowQuery) -> List[str]:
        """Generate optimization suggestions for slow queries."""
        suggestions = []
        
        # Check query complexity
        term_count = len(slow_query.query_text.split())
        if term_count > 5:
            suggestions.append("Consider using more specific search terms")
        
        # Check for wildcards
        if '*' in slow_query.query_text:
            suggestions.append("Wildcard searches are slower; try exact terms when possible")
        
        # Check result count
        if slow_query.result_count > 1000:
            suggestions.append("Query returns many results; add more specific terms to narrow down")
        
        # Check for common patterns
        if 'OR' in slow_query.query_text and term_count > 10:
            suggestions.append("Complex OR queries are slow; consider breaking into multiple searches")
        
        return suggestions
    
    def _suggest_alternatives(self, failed_query: FailedQuery) -> List[str]:
        """Suggest alternatives for failed queries."""
        alternatives = []
        query = failed_query.query_text
        
        # Suggest removing special characters
        if any(char in query for char in ['(', ')', '[', ']', '{', '}']):
            cleaned = re.sub(r'[()[\]{}]', '', query)
            alternatives.append(cleaned.strip())
        
        # Suggest splitting camelCase
        if re.search(r'[a-z][A-Z]', query):
            split = re.sub(r'(?<!^)(?=[A-Z])', ' ', query)
            alternatives.append(split.lower())
        
        # Suggest removing underscores
        if '_' in query:
            alternatives.append(query.replace('_', ' '))
        
        # Suggest simpler terms
        if len(query.split()) > 3:
            # Take first two and last terms
            terms = query.split()
            alternatives.append(f"{terms[0]} {terms[-1]}")
        
        return alternatives
    
    def update_metrics(self):
        """Update aggregated metrics (call periodically)."""
        self.analytics_storage.update_hourly_metrics()
    
    def cleanup_old_data(self, retention_days: int = 90):
        """Clean up old analytics data."""
        self.analytics_storage.cleanup_old_data(retention_days)
    
    def shutdown(self):
        """Shutdown analytics service."""
        self.metrics_collector.stop()
```

### Integration with Search Service

**Update** `search/search_service.py`:
```python
from analytics.search_analytics import SearchAnalytics
import time

class SearchService:
    def __init__(self, 
                 storage_backend: StorageBackend,
                 query_builder: FTS5QueryBuilder,
                 executor: SearchExecutor,
                 formatter: ResultFormatter,
                 analytics: Optional[SearchAnalytics] = None):
        self.storage = storage_backend
        self.query_builder = query_builder
        self.executor = executor
        self.formatter = formatter
        self.analytics = analytics
    
    def search_metadata(self, query: str, dataset: str, limit: int,
                       client_info: Optional[Dict[str, Any]] = None) -> SearchResults:
        """Search with analytics tracking."""
        start_time = time.time()
        error = None
        results = None
        fallback_used = False
        
        try:
            # Build primary query
            fts_query = self.query_builder.build_query(query)
            normalized_query = self.query_builder.normalize_query(query)
            
            # Try primary search
            raw_results = self.storage.search_metadata(fts_query, dataset, limit)
            
            # If no results, try fallback
            if not raw_results:
                fallback_query = self.query_builder.build_fallback_query(query)
                raw_results = self.storage.search_metadata(fallback_query, dataset, limit)
                fallback_used = True
                fts_query = fallback_query
            
            results = self.formatter.format_metadata_results(raw_results)
            
        except Exception as e:
            error = e
            results = SearchResults(results=[], total_count=0, query_time_ms=0)
            raise
        
        finally:
            # Log analytics
            duration_ms = (time.time() - start_time) * 1000
            
            if self.analytics:
                self.analytics.log_query(
                    query=query,
                    dataset=dataset,
                    results_count=results.total_count if results else 0,
                    duration_ms=duration_ms,
                    normalized_query=normalized_query,
                    fts_query=fts_query,
                    error=error,
                    fallback_used=fallback_used,
                    client_info=client_info
                )
        
        return results
```

## Testing Plan

### Unit Tests

#### test_analytics_models.py
```python
def test_query_log_entry():
    """Test QueryLogEntry creation."""
    entry = QueryLogEntry(
        query_id="test-123",
        query_text="user authentication",
        normalized_query="authentication user",
        fts_query='"authentication" "user"',
        dataset="myproject",
        status=QueryStatus.SUCCESS,
        result_count=42,
        duration_ms=15.5,
        timestamp=datetime.now()
    )
    assert entry.query_id == "test-123"
    assert entry.status == QueryStatus.SUCCESS

def test_metrics_calculations():
    """Test metrics aggregation logic."""
    # Test percentile calculations
    # Test time bucketing
    # Test aggregation accuracy
```

#### test_metrics_collector.py
```python
def test_async_collection():
    """Test metrics are collected asynchronously."""
    storage = Mock()
    collector = MetricsCollector(storage, batch_size=2, flush_interval=0.1)
    collector.start()
    
    # Send metrics
    collector.collect_query(
        query_text="test",
        normalized_query="test",
        fts_query="test",
        dataset="test",
        status=QueryStatus.SUCCESS,
        result_count=10,
        duration_ms=5.0
    )
    
    # Wait for flush
    time.sleep(0.2)
    
    # Verify batch insert was called
    storage.insert_query_logs_batch.assert_called()

def test_collector_performance():
    """Test collector doesn't block main thread."""
    collector = MetricsCollector(Mock())
    
    start = time.time()
    for _ in range(1000):
        collector.collect_query(...)
    duration = time.time() - start
    
    # Should be very fast (< 10ms for 1000 calls)
    assert duration < 0.01
```

#### test_search_analytics.py
```python
def test_slow_query_detection():
    """Test slow query identification."""
    analytics = SearchAnalytics(Mock())
    
    # Insert test data
    # Query for slow queries
    slow_queries = analytics.get_slow_queries(threshold_ms=100)
    
    assert len(slow_queries) > 0
    assert all(q.duration_ms > 100 for q in slow_queries)
    assert all(len(q.suggestions) > 0 for q in slow_queries)

def test_popular_terms():
    """Test popular term extraction."""
    analytics = SearchAnalytics(Mock())
    
    # Insert queries with various terms
    # Get popular terms
    terms = analytics.get_popular_terms(days=7)
    
    assert len(terms) > 0
    assert terms[0].search_count > terms[-1].search_count
```

### Integration Tests
```python
def test_analytics_integration():
    """Test analytics integrates with search service."""
    # Create full stack with analytics
    storage = SqliteBackend(":memory:")
    analytics = SearchAnalytics(storage)
    search_service = SearchService(
        storage_backend=storage,
        query_builder=FTS5QueryBuilder(),
        executor=SearchExecutor(),
        formatter=ResultFormatter(),
        analytics=analytics
    )
    
    # Perform searches
    search_service.search_metadata("test query", "dataset1", 10)
    
    # Check analytics were recorded
    insights = analytics.get_search_insights(time_period="hour")
    assert insights.total_queries == 1
```

## Performance Considerations

1. **Asynchronous Collection**: Metrics collection never blocks search operations
2. **Batch Writes**: Analytics data is written in batches to minimize I/O
3. **Separate Tables**: Analytics tables are separate from main data tables
4. **Partitioned Data**: Query logs partitioned by date for efficient cleanup
5. **Indexed Queries**: All analytics queries use appropriate indexes
6. **Configurable Retention**: Old data automatically cleaned up
7. **Sampling Option**: Can sample high-volume queries if needed

## Configuration

Add to server configuration:
```python
# Analytics configuration
ANALYTICS_ENABLED = True
ANALYTICS_BATCH_SIZE = 100
ANALYTICS_FLUSH_INTERVAL = 5.0  # seconds
ANALYTICS_RETENTION_DAYS = 90
ANALYTICS_SLOW_QUERY_THRESHOLD_MS = 1000
```

## Migration Strategy

1. Analytics is completely additive - no changes to existing code required
2. Can be enabled/disabled via configuration
3. Historical data not required - starts collecting from enablement
4. Can run in "collect-only" mode initially without querying

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance overhead | Slower searches | Async collection, batching, optional sampling |
| Storage growth | Disk space issues | Automatic retention/cleanup, partitioning |
| Queue overflow | Lost metrics | Bounded queue, monitoring, acceptable loss |
| Privacy concerns | Data exposure | No PII in analytics, configurable collection |

## Success Criteria

1. **Performance Impact**: < 1% overhead on search operations
2. **Data Quality**: 99%+ of queries successfully logged
3. **Insights Value**: Identify top 10 slow queries weekly
4. **Storage Efficiency**: < 10MB per million queries
5. **Query Performance**: Analytics queries < 100ms

## Future Enhancements

1. **Real-time Dashboard**: Live metrics visualization
2. **Alerting**: Notify on performance degradation
3. **A/B Testing**: Compare query strategies
4. **ML Integration**: Predict query performance
5. **User Segmentation**: Track by user groups
6. **Query Recommendations**: Suggest better queries
7. **Export Capabilities**: Analytics data export