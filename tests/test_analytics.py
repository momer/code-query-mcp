"""Unit tests for analytics module."""

import unittest
from unittest.mock import Mock, patch, call
import time
from datetime import datetime, timedelta
from queue import Queue
import sqlite3

from analytics.analytics_models import (
    QueryLogEntry, QueryStatus, SlowQuery, FailedQuery, SearchTerm
)
from analytics.metrics_collector import MetricsCollector
from analytics.analytics_storage import AnalyticsStorage
from analytics.search_analytics import SearchAnalytics


class TestAnalyticsModels(unittest.TestCase):
    """Test analytics data models."""
    
    def test_query_log_entry(self):
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
        self.assertEqual(entry.query_id, "test-123")
        self.assertEqual(entry.status, QueryStatus.SUCCESS)
        self.assertEqual(entry.result_count, 42)
        self.assertIsNone(entry.error_message)
        self.assertFalse(entry.fallback_attempted)
    
    def test_query_status_enum(self):
        """Test QueryStatus enum values."""
        self.assertEqual(QueryStatus.SUCCESS.value, "success")
        self.assertEqual(QueryStatus.NO_RESULTS.value, "no_results")
        self.assertEqual(QueryStatus.ERROR.value, "error")
        self.assertEqual(QueryStatus.FALLBACK_USED.value, "fallback_used")
        self.assertEqual(QueryStatus.TIMEOUT.value, "timeout")
    
    def test_slow_query_model(self):
        """Test SlowQuery model with suggestions."""
        query = SlowQuery(
            query_text="complex OR query WITH many terms",
            dataset="test",
            duration_ms=1500.0,
            result_count=2000,
            timestamp=datetime.now()
        )
        query.suggestions.append("Consider using more specific terms")
        self.assertEqual(len(query.suggestions), 1)
        self.assertGreater(query.duration_ms, 1000)


class TestMetricsCollector(unittest.TestCase):
    """Test metrics collector functionality."""
    
    def test_async_collection(self):
        """Test that metrics are collected asynchronously."""
        storage = Mock(spec=AnalyticsStorage)
        collector = MetricsCollector(storage, batch_size=2, flush_interval=0.1)
        collector.start()
        
        # Collect some metrics
        collector.collect_query(
            query_text="test1",
            normalized_query="test1",
            fts_query="test1",
            dataset="test",
            status=QueryStatus.SUCCESS,
            result_count=10,
            duration_ms=5.0
        )
        
        collector.collect_query(
            query_text="test2",
            normalized_query="test2",
            fts_query="test2",
            dataset="test",
            status=QueryStatus.NO_RESULTS,
            result_count=0,
            duration_ms=3.0
        )
        
        # Wait for flush
        time.sleep(0.2)
        
        # Verify batch insert was called
        storage.insert_query_logs_batch.assert_called()
        
        # Check that 2 entries were batched
        call_args = storage.insert_query_logs_batch.call_args[0][0]
        self.assertEqual(len(call_args), 2)
        self.assertEqual(call_args[0].query_text, "test1")
        self.assertEqual(call_args[1].query_text, "test2")
        
        collector.stop()
    
    def test_collector_performance(self):
        """Test that collector doesn't block main thread."""
        storage = Mock(spec=AnalyticsStorage)
        collector = MetricsCollector(storage)
        collector.start()
        
        start_time = time.time()
        
        # Collect many metrics rapidly
        for i in range(1000):
            collector.collect_query(
                query_text=f"test{i}",
                normalized_query=f"test{i}",
                fts_query=f"test{i}",
                dataset="test",
                status=QueryStatus.SUCCESS,
                result_count=i,
                duration_ms=1.0
            )
        
        duration = time.time() - start_time
        
        # Should be very fast (< 50ms for 1000 calls)
        self.assertLess(duration, 0.05, f"Collection took {duration:.3f}s, expected < 0.05s")
        
        collector.stop()
    
    def test_queue_overflow_handling(self):
        """Test that queue overflow is handled gracefully."""
        storage = Mock(spec=AnalyticsStorage)
        # Create collector with tiny queue
        collector = MetricsCollector(storage)
        collector.queue = Queue(maxsize=2)
        collector.enabled = True
        
        # Fill queue
        for i in range(5):
            collector.collect_query(
                query_text=f"test{i}",
                normalized_query=f"test{i}",
                fts_query=f"test{i}",
                dataset="test",
                status=QueryStatus.SUCCESS,
                result_count=i,
                duration_ms=1.0
            )
        
        # Should not raise exception
        # Queue should have max 2 items
        self.assertEqual(collector.queue.qsize(), 2)


class TestAnalyticsStorage(unittest.TestCase):
    """Test analytics storage operations."""
    
    def setUp(self):
        """Set up test database."""
        import tempfile
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='.db')
        self.storage = AnalyticsStorage(self.test_db_path)
    
    def tearDown(self):
        """Clean up test database."""
        import os
        os.close(self.test_db_fd)
        os.unlink(self.test_db_path)
    
    def test_insert_and_retrieve_query_logs(self):
        """Test inserting and retrieving query logs."""
        # Insert test entries
        entries = []
        base_time = datetime.now()
        
        for i in range(5):
            entry = QueryLogEntry(
                query_id=f"test-{i}",
                query_text=f"query {i}",
                normalized_query=f"query {i}",
                fts_query=f"query {i}",
                dataset="test",
                status=QueryStatus.SUCCESS if i < 3 else QueryStatus.ERROR,
                result_count=i * 10,
                duration_ms=100.0 * (i + 1),
                timestamp=base_time - timedelta(hours=i),
                error_message="Test error" if i >= 3 else None
            )
            entries.append(entry)
        
        # Batch insert
        self.storage.insert_query_logs_batch(entries)
        
        # Test slow query retrieval
        slow_queries = self.storage.get_slow_queries(
            threshold_ms=200,
            limit=10,
            since=base_time - timedelta(days=1)
        )
        
        # Should find queries with duration > 200ms
        self.assertEqual(len(slow_queries), 1)  # Only successful queries
        self.assertEqual(slow_queries[0].query_text, "query 2")
        self.assertGreater(slow_queries[0].duration_ms, 200)
    
    def test_failed_query_aggregation(self):
        """Test aggregation of failed queries."""
        base_time = datetime.now()
        
        # Insert multiple failures of same query
        for i in range(5):
            entry = QueryLogEntry(
                query_id=f"fail-{i}",
                query_text="failing query",
                normalized_query="failing query",
                fts_query="failing query",
                dataset="test",
                status=QueryStatus.ERROR,
                result_count=0,
                duration_ms=10.0,
                timestamp=base_time - timedelta(minutes=i),
                error_message="Parse error"
            )
            self.storage.insert_query_log(entry)
        
        # Get failed queries
        failed_queries = self.storage.get_failed_queries(
            since=base_time - timedelta(hours=1)
        )
        
        self.assertEqual(len(failed_queries), 1)
        self.assertEqual(failed_queries[0].failure_count, 5)
        self.assertEqual(failed_queries[0].query_text, "failing query")
    
    def test_popular_terms_extraction(self):
        """Test extraction of popular search terms."""
        base_time = datetime.now()
        
        # Insert queries with various terms
        terms = ["authentication", "login", "user", "authentication", "login", "authentication"]
        
        for i, term in enumerate(terms):
            entry = QueryLogEntry(
                query_id=f"popular-{i}",
                query_text=term,
                normalized_query=term.lower(),
                fts_query=term,
                dataset="test",
                status=QueryStatus.SUCCESS,
                result_count=10,
                duration_ms=5.0,
                timestamp=base_time - timedelta(minutes=i)
            )
            self.storage.insert_query_log(entry)
        
        # Get popular terms
        popular = self.storage.get_popular_terms(days=1, limit=10)
        
        self.assertGreater(len(popular), 0)
        # Most popular should be "authentication" (3 times)
        self.assertEqual(popular[0].term, "authentication")
        self.assertEqual(popular[0].search_count, 3)


class TestSearchAnalytics(unittest.TestCase):
    """Test main analytics service."""
    
    def setUp(self):
        """Set up analytics service."""
        import tempfile
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='.db')
        self.analytics = SearchAnalytics(self.test_db_path)
    
    def tearDown(self):
        """Clean up analytics service."""
        self.analytics.shutdown()
        import os
        os.close(self.test_db_fd)
        os.unlink(self.test_db_path)
    
    def test_query_logging(self):
        """Test query logging with different statuses."""
        # Success case
        self.analytics.log_query(
            query="test query",
            dataset="test",
            results_count=10,
            duration_ms=15.5,
            error=None
        )
        
        # No results case
        self.analytics.log_query(
            query="no results",
            dataset="test",
            results_count=0,
            duration_ms=5.0,
            error=None
        )
        
        # Error case
        self.analytics.log_query(
            query="error query",
            dataset="test",
            results_count=0,
            duration_ms=2.0,
            error=ValueError("Test error")
        )
        
        # Fallback case
        self.analytics.log_query(
            query="fallback query",
            dataset="test",
            results_count=5,
            duration_ms=20.0,
            fallback_used=True
        )
        
        # Wait for collector to process
        time.sleep(0.5)  # Give more time for processing
        
        # Stop the collector to ensure all items are flushed
        self.analytics.metrics_collector.stop()
        
        # Verify queries were written to database
        with sqlite3.connect(self.test_db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM search_query_log")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 4)
        
        # Restart collector for tearDown
        self.analytics.metrics_collector.start()
    
    def test_query_normalization(self):
        """Test query normalization for grouping."""
        # Create a mock query builder with normalization
        from search.query_builder import FTS5QueryBuilder
        query_builder = FTS5QueryBuilder()
        
        # Test basic normalization
        normalized = query_builder.normalize_query("  Test  Query  ")
        self.assertEqual(normalized, "query test")  # lowercased, trimmed, sorted
        
        # Test with operators (should not sort)
        normalized = query_builder.normalize_query("term1 AND term2")
        self.assertEqual(normalized, "term1 and term2")
    
    def test_optimization_suggestions(self):
        """Test generation of optimization suggestions."""
        # Test slow query with many terms
        slow_query = SlowQuery(
            query_text="term1 term2 term3 term4 term5 term6",
            dataset="test",
            duration_ms=2000,
            result_count=100,
            timestamp=datetime.now()
        )
        
        suggestions = self.analytics._generate_optimization_suggestions(slow_query)
        self.assertIn("Consider using more specific search terms", suggestions)
        
        # Test query with wildcards
        slow_query.query_text = "user* auth*"
        suggestions = self.analytics._generate_optimization_suggestions(slow_query)
        self.assertIn("Wildcard searches are slower; try exact terms when possible", suggestions)
        
        # Test query with many results
        slow_query.query_text = "common"
        slow_query.result_count = 5000
        suggestions = self.analytics._generate_optimization_suggestions(slow_query)
        self.assertIn("Query returns many results; add more specific terms to narrow down", suggestions)
    
    def test_percentile_calculations(self):
        """Test that hourly metrics calculate percentiles correctly."""
        # Insert test data directly using SQLite datetime for consistency
        with sqlite3.connect(self.test_db_path) as conn:
            # Insert 100 queries with known distribution
            for i in range(1, 101):
                conn.execute("""
                    INSERT INTO search_query_log (
                        query_id, query_text, normalized_query, fts_query,
                        dataset, status, result_count, duration_ms,
                        timestamp, error_message, fallback_attempted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-90 minutes'), NULL, 0)
                """, (
                    f"perc-{i}",
                    f"query {i}",
                    f"query {i}", 
                    f"query {i}",
                    "test",
                    "success",
                    10,
                    float(i)  # 1ms to 100ms for easy percentile verification
                ))
            conn.commit()
        
        # Update hourly metrics
        self.analytics.analytics_storage.update_hourly_metrics()
        
        # Verify percentiles
        with sqlite3.connect(self.test_db_path) as conn:
            cursor = conn.execute("""
                SELECT p50_duration_ms, p95_duration_ms, p99_duration_ms
                FROM search_metrics_hourly
                WHERE dataset = 'test'
            """)
            row = cursor.fetchone()
            
            self.assertIsNotNone(row, "Should have hourly metrics")
            p50, p95, p99 = row
            
            # Verify percentiles are in expected ranges
            self.assertAlmostEqual(p50, 50.0, delta=5.0)
            self.assertAlmostEqual(p95, 95.0, delta=5.0)
            self.assertAlmostEqual(p99, 99.0, delta=5.0)
    
    def test_alternative_suggestions(self):
        """Test generation of alternative query suggestions."""
        failed_query = FailedQuery(
            query_text="getUserAuth()",
            dataset="test",
            error_type="parse_error",
            error_message="Invalid syntax",
            failure_count=5,
            first_seen=datetime.now(),
            last_seen=datetime.now()
        )
        
        alternatives = self.analytics._suggest_alternatives(failed_query)
        
        # Should suggest removing parentheses
        self.assertIn("getUserAuth", alternatives)
        
        # Test with camelCase
        failed_query.query_text = "getUserAuthentication"
        alternatives = self.analytics._suggest_alternatives(failed_query)
        self.assertIn("get user authentication", alternatives)
        
        # Test with underscores
        failed_query.query_text = "get_user_auth"
        alternatives = self.analytics._suggest_alternatives(failed_query)
        self.assertIn("get user auth", alternatives)


    def test_aggregation_fallback(self):
        """Test that get_insights_data falls back to raw logs when no aggregated data."""
        # Don't run hourly aggregation, so we only have raw logs
        base_time = datetime.now()
        
        # Insert some test queries
        for i in range(10):
            entry = QueryLogEntry(
                query_id=f"fallback-{i}",
                query_text=f"test query {i}",
                normalized_query=f"query test {i}",
                fts_query=f"test query {i}",
                dataset="fallback_test",
                status=QueryStatus.SUCCESS if i < 8 else QueryStatus.NO_RESULTS,
                result_count=i * 10,
                duration_ms=float(i * 5),
                timestamp=base_time,
                fallback_attempted=(i % 3 == 0)
            )
            self.analytics.analytics_storage.insert_query_log(entry)
        
        # Get insights without aggregated data
        insights_data = self.analytics.analytics_storage.get_insights_data(
            since=base_time - timedelta(hours=1),
            dataset="fallback_test"
        )
        
        # Verify we got data from raw logs
        overview = insights_data["overview"]
        self.assertEqual(overview["total_queries"], 10)
        self.assertEqual(overview["unique_queries"], 10)
        self.assertEqual(overview["success_rate"], 80.0)  # 8/10 success
        self.assertEqual(overview["no_results_rate"], 20.0)  # 2/10 no results
        self.assertEqual(overview["fallback_rate"], 40.0)  # 4/10 fallback (0,3,6,9)
        
        # Verify top queries
        top_queries = insights_data["top_queries"]
        self.assertEqual(len(top_queries), 10)
    
    def test_aggregation_with_metrics(self):
        """Test that get_insights_data uses aggregated metrics when available."""
        # Insert data in the past (2 hours ago) so it gets aggregated
        base_time = datetime.now()
        
        # Use direct SQL to insert data exactly 90 minutes ago
        import sqlite3
        with sqlite3.connect(self.test_db_path) as conn:
            for i in range(20):
                conn.execute("""
                    INSERT INTO search_query_log (
                        query_id, query_text, normalized_query, fts_query,
                        dataset, status, result_count, duration_ms,
                        timestamp, error_message, fallback_attempted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-90 minutes'), NULL, ?)
                """, (
                    f"agg-{i}",
                    f"query {i % 5}",  # Only 5 unique queries
                    f"query {i % 5}",
                    f"query {i % 5}",
                    "agg_test",
                    "success",
                    i,
                    float(i * 2),
                    (i % 4 == 0)  # 25% fallback
                ))
            conn.commit()
        
        # Run aggregation
        self.analytics.analytics_storage.update_hourly_metrics()
        
        # Get insights - should use aggregated data
        insights_data = self.analytics.analytics_storage.get_insights_data(
            since=base_time - timedelta(hours=2),
            dataset="agg_test"
        )
        
        # Verify aggregated data
        overview = insights_data["overview"]
        self.assertEqual(overview["total_queries"], 20)
        self.assertEqual(overview["unique_queries"], 5)  # Only 5 unique normalized queries
        self.assertEqual(overview["success_rate"], 100.0)
        self.assertEqual(overview["fallback_rate"], 25.0)  # 5/20 = 25%


if __name__ == "__main__":
    unittest.main()