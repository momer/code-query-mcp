"""Tests for query timeout functionality in SqliteBackend."""

import unittest
import sqlite3
import tempfile
import os
import time
import threading
from unittest.mock import Mock, patch, MagicMock

from storage.sqlite_backend import SqliteBackend
from storage.models import FileDocumentation
from search.search_service import SearchService, SearchConfig


class TestQueryTimeout(unittest.TestCase):
    """Test query timeout handling in SqliteBackend."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary database
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp()
        self.backend = SqliteBackend(self.temp_db_path)
        
        # Create test dataset
        self.backend.create_dataset("test_dataset", "/test/path")
        
        # Insert test data
        for i in range(100):
            doc = FileDocumentation(
                dataset="test_dataset",
                filepath=f"/test/file{i}.py",
                filename=f"file{i}.py",
                overview=f"Test file {i} with lots of content to search through",
                ddd_context=f"Domain context for file {i}",
                functions={"test_func": "Test function"},
                exports=["export1", "export2"],
                imports=["import1", "import2"],
                types_interfaces_classes=["TestClass"],
                constants={"CONST1": "value1"},
                dependencies=["dep1", "dep2"],
                other_notes="Test notes",
                full_content=f"Content for file {i} " * 100,  # Long content
                documented_at_commit="abc123"
            )
            self.backend.insert_documentation(doc)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.backend.close()
        os.close(self.temp_db_fd)
        os.unlink(self.temp_db_path)
    
    def test_timeout_context_manager_no_timeout(self):
        """Test that queries work normally without timeout."""
        with self.backend.connection_pool.get_connection() as conn:
            with self.backend._query_timeout(conn, None):
                cursor = conn.execute("SELECT COUNT(*) FROM files")
                count = cursor.fetchone()[0]
                self.assertEqual(count, 100)
    
    def test_timeout_context_manager_with_timeout(self):
        """Test that timeout interrupts long-running queries."""
        # Test the timeout mechanism with a simulated slow operation
        with self.backend.connection_pool.get_connection() as conn:
            # Test with very short timeout
            with self.assertRaises(TimeoutError) as cm:
                with self.backend._query_timeout(conn, 1):  # 1ms timeout
                    # Simulate a slow operation by sleeping
                    # This will trigger the timeout before query completes
                    time.sleep(0.01)  # Sleep for 10ms
                    
                    # The timeout should fire before we get here
                    cursor = conn.execute("SELECT COUNT(*) FROM files")
                    cursor.fetchone()
            
            self.assertIn("Query exceeded timeout", str(cm.exception))
    
    def test_search_files_with_timeout(self):
        """Test search_files respects timeout parameter."""
        # FTS5 requires manual insert for external content tables
        # Insert into FTS5 first
        with self.backend.connection_pool.get_connection() as conn:
            conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        
        # Test normal operation
        results = self.backend.search_files(
            query="test",
            dataset_id="test_dataset",
            limit=10,
            timeout_ms=5000  # 5 second timeout
        )
        self.assertGreater(len(results), 0)
        
        # Test timeout by mocking a slow query
        with patch.object(self.backend, '_query_timeout') as mock_timeout:
            # Make the timeout context raise TimeoutError
            mock_timeout.side_effect = TimeoutError("Query timeout")
            
            with self.assertRaises(TimeoutError):
                self.backend.search_files(
                    query="test",
                    dataset_id="test_dataset",
                    timeout_ms=100
                )
    
    def test_search_full_content_with_timeout(self):
        """Test search_full_content respects timeout parameter."""
        # FTS5 requires manual insert for external content tables
        # Insert into FTS5 first
        with self.backend.connection_pool.get_connection() as conn:
            conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        
        # Test normal operation
        results = self.backend.search_full_content(
            query="content",
            dataset_id="test_dataset",
            limit=10,
            timeout_ms=5000  # 5 second timeout
        )
        self.assertGreater(len(results), 0)
        
        # Test timeout
        with patch.object(self.backend, '_query_timeout') as mock_timeout:
            mock_timeout.side_effect = TimeoutError("Query timeout")
            
            with self.assertRaises(TimeoutError):
                self.backend.search_full_content(
                    query="content",
                    dataset_id="test_dataset",
                    timeout_ms=100
                )
    
    def test_search_service_timeout_propagation(self):
        """Test that SearchService properly propagates timeout to backend."""
        # Create search service
        search_service = SearchService(self.backend)
        
        # Configure with timeout
        config = SearchConfig(
            query_timeout_ms=1000,
            enable_fallback=False,  # Disable to simplify test
            enable_progressive_search=False
        )
        
        # Mock the backend methods to verify timeout is passed
        with patch.object(self.backend, 'search_files', wraps=self.backend.search_files) as mock_search:
            # Perform metadata search
            search_service.search_metadata("test", "test_dataset", config)
            
            # Verify timeout was passed
            mock_search.assert_called_once()
            call_kwargs = mock_search.call_args[1]
            self.assertEqual(call_kwargs.get('timeout_ms'), 1000)
        
        # Test content search
        with patch.object(self.backend, 'search_full_content', wraps=self.backend.search_full_content) as mock_search:
            # Perform content search
            search_service.search_content("test", "test_dataset", config)
            
            # Verify timeout was passed
            mock_search.assert_called_once()
            call_kwargs = mock_search.call_args[1]
            self.assertEqual(call_kwargs.get('timeout_ms'), 1000)
    
    def test_timeout_cleanup(self):
        """Test that timeout timer is properly cleaned up."""
        with self.backend.connection_pool.get_connection() as conn:
            # Track active threads before
            threads_before = threading.active_count()
            
            # Execute query with timeout
            with self.backend._query_timeout(conn, 5000):  # 5 second timeout
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
            
            # Give timer thread time to clean up
            time.sleep(0.1)
            
            # Verify no lingering threads
            threads_after = threading.active_count()
            self.assertEqual(threads_before, threads_after, "Timer thread not cleaned up")
    
    def test_concurrent_timeouts(self):
        """Test multiple concurrent queries with timeouts."""
        results = []
        errors = []
        
        def run_query(timeout_ms):
            try:
                result = self.backend.search_files(
                    query="test",
                    dataset_id="test_dataset",
                    limit=5,
                    timeout_ms=timeout_ms
                )
                results.append(len(result))
            except TimeoutError as e:
                errors.append(str(e))
        
        # Run multiple queries concurrently
        threads = []
        for i in range(5):
            # Mix of different timeouts
            timeout = 5000 if i % 2 == 0 else 100
            t = threading.Thread(target=run_query, args=(timeout,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have some successful results
        self.assertGreater(len(results), 0)


if __name__ == '__main__':
    unittest.main()