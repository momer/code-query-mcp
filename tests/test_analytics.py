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
        self.mock_storage = Mock()
        self.mock_storage.db_path = self.test_db_path
        self.analytics = SearchAnalytics(self.mock_storage)
    
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
        # Test basic normalization
        normalized = self.analytics._normalize_query("  Test  Query  ")
        self.assertEqual(normalized, "query test")  # lowercased, trimmed, sorted
        
        # Test with operators (should not sort)
        normalized = self.analytics._normalize_query("term1 AND term2")
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


if __name__ == "__main__":
    unittest.main()