"""Concurrency tests for analytics module."""

import unittest
import threading
import time
import tempfile
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from analytics.search_analytics import SearchAnalytics
from analytics.analytics_storage import AnalyticsStorage
from analytics.metrics_collector import MetricsCollector
from analytics.analytics_models import QueryLogEntry, QueryStatus


class TestAnalyticsConcurrency(unittest.TestCase):
    """Test concurrent access to analytics components."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_db_fd, self.test_db_path = tempfile.mkstemp(suffix='.db')
        self.analytics = SearchAnalytics(self.test_db_path)
        
    def tearDown(self):
        """Clean up test environment."""
        self.analytics.shutdown()
        os.close(self.test_db_fd)
        os.unlink(self.test_db_path)
    
    def test_concurrent_log_queries(self):
        """Test concurrent query logging from multiple threads."""
        num_threads = 10
        queries_per_thread = 50
        
        def log_queries(thread_id):
            """Log queries from a single thread."""
            for i in range(queries_per_thread):
                self.analytics.log_query(
                    query=f"test query {thread_id}-{i}",
                    dataset="test_concurrent",
                    results_count=i,
                    duration_ms=10.0 + i,
                    client_info={"thread_id": thread_id}
                )
                # Small delay to increase chance of contention
                time.sleep(0.001)
            return thread_id
        
        # Run concurrent logging
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(log_queries, i) for i in range(num_threads)]
            completed_threads = [f.result() for f in as_completed(futures)]
        
        # Ensure all threads completed
        self.assertEqual(len(completed_threads), num_threads)
        
        # Wait for collector to flush
        time.sleep(1.0)
        self.analytics.metrics_collector.stop()
        
        # Verify all queries were logged
        storage = self.analytics.analytics_storage
        import sqlite3
        with sqlite3.connect(storage.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM search_query_log")
            count = cursor.fetchone()[0]
        
        expected_count = num_threads * queries_per_thread
        self.assertEqual(count, expected_count, 
                        f"Expected {expected_count} queries, got {count}")
    
    def test_concurrent_storage_operations(self):
        """Test concurrent read/write operations on analytics storage."""
        storage = AnalyticsStorage(self.test_db_path)
        num_operations = 100
        
        def mixed_operations(op_id):
            """Perform mixed read/write operations."""
            if op_id % 3 == 0:
                # Write operation
                entry = QueryLogEntry(
                    query_id=f"concurrent-{op_id}",
                    query_text=f"query {op_id}",
                    normalized_query=f"query {op_id}",
                    fts_query=f"query {op_id}",
                    dataset="concurrent_test",
                    status=QueryStatus.SUCCESS,
                    result_count=op_id,
                    duration_ms=float(op_id),
                    timestamp=datetime.now()
                )
                storage.insert_query_log(entry)
            elif op_id % 3 == 1:
                # Read slow queries
                storage.get_slow_queries(threshold_ms=50)
            else:
                # Read popular terms
                storage.get_popular_terms(days=1)
            
            return op_id
        
        # Run concurrent operations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(mixed_operations, i) 
                      for i in range(num_operations)]
            completed = [f.result() for f in as_completed(futures)]
        
        self.assertEqual(len(completed), num_operations)
    
    def test_metrics_collector_queue_concurrency(self):
        """Test that metrics collector handles concurrent submissions safely."""
        storage = AnalyticsStorage(self.test_db_path)
        collector = MetricsCollector(storage, batch_size=10, flush_interval=0.5)
        collector.start()
        
        num_threads = 5
        entries_per_thread = 100
        
        def submit_entries(thread_id):
            """Submit entries from a thread."""
            for i in range(entries_per_thread):
                collector.collect_query(
                    query_text=f"thread{thread_id} query{i}",
                    normalized_query=f"query{i} thread{thread_id}",
                    fts_query=f"query{i}",
                    dataset=f"dataset{thread_id}",
                    status=QueryStatus.SUCCESS,
                    result_count=i,
                    duration_ms=float(i)
                )
            return thread_id
        
        # Submit from multiple threads
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(submit_entries, i) for i in range(num_threads)]
            completed = [f.result() for f in as_completed(futures)]
        
        self.assertEqual(len(completed), num_threads)
        
        # Let collector process
        time.sleep(1.0)
        collector.stop()
        
        # Verify entries
        import sqlite3
        with sqlite3.connect(storage.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM search_query_log")
            count = cursor.fetchone()[0]
        
        expected = num_threads * entries_per_thread
        self.assertEqual(count, expected)
    
    def test_hourly_metrics_update_concurrency(self):
        """Test concurrent hourly metrics updates."""
        storage = AnalyticsStorage(self.test_db_path)
        
        # Insert test data
        base_time = datetime.now()
        for i in range(100):
            entry = QueryLogEntry(
                query_id=f"metric-test-{i}",
                query_text=f"query {i}",
                normalized_query=f"query {i}",
                fts_query=f"query {i}",
                dataset="metrics_test",
                status=QueryStatus.SUCCESS,
                result_count=i,
                duration_ms=float(i),
                timestamp=base_time
            )
            storage.insert_query_log(entry)
        
        # Simulate concurrent metric updates
        def update_metrics():
            storage.update_hourly_metrics()
            return True
        
        # Run multiple concurrent updates
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_metrics) for _ in range(5)]
            results = [f.result() for f in as_completed(futures)]
        
        self.assertEqual(len(results), 5)
        
        # Verify metrics were updated correctly (should not have duplicates)
        import sqlite3
        with sqlite3.connect(storage.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) 
                FROM search_metrics_hourly 
                WHERE dataset = 'metrics_test'
            """)
            count = cursor.fetchone()[0]
        
        # Should have at most 1 entry per hour bucket
        self.assertLessEqual(count, 2)  # Allow for edge case of hour boundary
    
    def test_database_connection_safety(self):
        """Test that database connections are properly isolated between threads."""
        storage = AnalyticsStorage(self.test_db_path)
        errors = []
        lock = threading.Lock()
        
        def perform_db_operation(op_id):
            """Perform database operation from a thread."""
            try:
                import sqlite3
                # Each thread creates its own connection
                conn = sqlite3.connect(storage.db_path)
                
                # Insert a record
                cursor = conn.execute("""
                    INSERT INTO search_query_log (
                        query_id, query_text, normalized_query, fts_query,
                        dataset, status, result_count, duration_ms,
                        timestamp, error_message, fallback_attempted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), NULL, 0)
                """, (
                    f"thread-safety-{op_id}",
                    f"query {op_id}",
                    f"query {op_id}",
                    f"query {op_id}",
                    "safety_test",
                    "success",
                    op_id,
                    float(op_id)
                ))
                
                # Read back
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM search_query_log 
                    WHERE query_id = ?
                """, (f"thread-safety-{op_id}",))
                
                count = cursor.fetchone()[0]
                conn.commit()
                conn.close()
                
                return count == 1
            except Exception as e:
                with lock:
                    errors.append(str(e))
                return False
        
        # Run operations from multiple threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(perform_db_operation, i) for i in range(20)]
            results = [f.result() for f in as_completed(futures)]
        
        # All operations should succeed
        self.assertTrue(all(results), f"Some operations failed. Errors: {errors}")
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()