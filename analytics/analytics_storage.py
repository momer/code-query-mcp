"""Storage backend for analytics data."""

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
                    first_seen=datetime.fromisoformat(row['first_seen']),
                    last_seen=datetime.fromisoformat(row['last_seen'])
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
                    first_seen=datetime.fromisoformat(row['first_seen']),
                    last_seen=datetime.fromisoformat(row['last_seen'])
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