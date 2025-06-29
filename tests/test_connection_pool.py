"""Tests for connection pool functionality."""

import unittest
import tempfile
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from storage.connection_pool import ConnectionPool


class TestConnectionPool(unittest.TestCase):
    """Test ConnectionPool functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_connection_pool_creation(self):
        """Test creating a connection pool."""
        pool = ConnectionPool(self.db_path, max_connections=3)
        
        self.assertEqual(pool.db_path, self.db_path)
        self.assertEqual(pool.max_connections, 3)
        self.assertFalse(pool._closed)
        
        pool.close()
        
    def test_get_connection(self):
        """Test getting a connection from pool."""
        pool = ConnectionPool(self.db_path, max_connections=2)
        
        with pool.get_connection() as conn:
            self.assertIsInstance(conn, sqlite3.Connection)
            
            # Test that connection works
            cursor = conn.execute("SELECT 1")
            result = cursor.fetchone()
            self.assertEqual(result[0], 1)
            
        pool.close()
        
    def test_connection_reuse(self):
        """Test that connections are reused."""
        pool = ConnectionPool(self.db_path, max_connections=1)
        
        # Get connection twice
        with pool.get_connection() as conn1:
            conn1_id = id(conn1)
            
        with pool.get_connection() as conn2:
            conn2_id = id(conn2)
            
        # Should be the same connection object
        self.assertEqual(conn1_id, conn2_id)
        
        pool.close()
        
    def test_max_connections_limit(self):
        """Test that pool respects max connections limit."""
        pool = ConnectionPool(self.db_path, max_connections=2, timeout=1)
        
        connections = []
        
        # Get two connections (max limit)
        conn1 = pool.get_connection().__enter__()
        connections.append(conn1)
        
        conn2 = pool.get_connection().__enter__()
        connections.append(conn2)
        
        # Try to get a third connection - should timeout
        start_time = time.time()
        with self.assertRaises(TimeoutError):
            with pool.get_connection() as conn3:
                pass
                
        elapsed = time.time() - start_time
        self.assertGreaterEqual(elapsed, 1.0)  # Should wait at least timeout seconds
        
        # Clean up
        for conn in connections:
            pool.get_connection().__exit__(None, None, None)
            
        pool.close()
        
    def test_concurrent_access(self):
        """Test thread-safe concurrent access."""
        pool = ConnectionPool(self.db_path, max_connections=5)
        
        # Create a table for testing
        with pool.get_connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.commit()
            
        def worker(worker_id):
            """Worker function that uses the pool."""
            for i in range(5):
                with pool.get_connection() as conn:
                    conn.execute(
                        "INSERT INTO test (value) VALUES (?)",
                        (f"worker_{worker_id}_item_{i}",)
                    )
                    conn.commit()
                    
        # Run workers concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            for future in futures:
                future.result()
                
        # Verify all inserts succeeded
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 50)  # 10 workers * 5 items each
            
        pool.close()
        
    def test_transaction_context_manager(self):
        """Test transaction context manager."""
        pool = ConnectionPool(self.db_path)
        
        # Create test table
        with pool.get_connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.commit()
            
        # Test successful transaction
        with pool.transaction() as conn:
            conn.execute("INSERT INTO test (value) VALUES ('test1')")
            conn.execute("INSERT INTO test (value) VALUES ('test2')")
            # Auto-commit on success
            
        # Verify data was committed
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            self.assertEqual(cursor.fetchone()[0], 2)
            
        # Test failed transaction (rollback)
        try:
            with pool.transaction() as conn:
                conn.execute("INSERT INTO test (value) VALUES ('test3')")
                # Force an error
                conn.execute("INVALID SQL")
        except sqlite3.OperationalError:
            pass
            
        # Verify rollback
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            self.assertEqual(cursor.fetchone()[0], 2)  # Still 2, not 3
            
        pool.close()
        
    def test_execute_convenience_method(self):
        """Test execute convenience method."""
        pool = ConnectionPool(self.db_path)
        
        # Create table
        pool.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
        
        # Insert with parameters
        pool.execute("INSERT INTO test (value) VALUES (?)", ("test_value",))
        
        # Query
        cursor = pool.execute("SELECT value FROM test WHERE id = 1")
        result = cursor.fetchone()
        self.assertEqual(result[0], "test_value")
        
        pool.close()
        
    def test_pool_stats(self):
        """Test connection pool statistics."""
        pool = ConnectionPool(self.db_path, max_connections=3)
        
        # Initial stats
        stats = pool.get_pool_stats()
        self.assertEqual(stats['max_connections'], 3)
        self.assertEqual(stats['created_connections'], 0)
        self.assertEqual(stats['available_connections'], 0)
        self.assertEqual(stats['in_use_connections'], 0)
        self.assertFalse(stats['is_closed'])
        
        # Get a connection
        ctx1 = pool.get_connection()
        conn1 = ctx1.__enter__()
        
        stats = pool.get_pool_stats()
        self.assertEqual(stats['created_connections'], 1)
        self.assertEqual(stats['in_use_connections'], 1)
        
        # Return connection
        ctx1.__exit__(None, None, None)
        
        stats = pool.get_pool_stats()
        self.assertEqual(stats['available_connections'], 1)
        self.assertEqual(stats['in_use_connections'], 0)
        
        pool.close()
        
        stats = pool.get_pool_stats()
        self.assertTrue(stats['is_closed'])
        
    def test_connection_validation(self):
        """Test that invalid connections are recreated."""
        pool = ConnectionPool(self.db_path, max_connections=1)
        
        # Get and close a connection manually
        with pool.get_connection() as conn:
            conn_id = id(conn)
            
        # Manually close the connection (simulating connection loss)
        with pool.get_connection() as conn:
            conn.close()
            
        # Next get should create a new connection
        with pool.get_connection() as conn:
            new_conn_id = id(conn)
            # Should be a different connection
            self.assertNotEqual(conn_id, new_conn_id)
            
            # Should still work
            cursor = conn.execute("SELECT 1")
            self.assertEqual(cursor.fetchone()[0], 1)
            
        pool.close()
        
    def test_context_manager_support(self):
        """Test using pool as context manager."""
        with ConnectionPool(self.db_path) as pool:
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                self.assertEqual(cursor.fetchone()[0], 1)
                
        # Pool should be closed after with block
        self.assertTrue(pool._closed)
        
    def test_closed_pool_error(self):
        """Test that closed pool raises error."""
        pool = ConnectionPool(self.db_path)
        pool.close()
        
        with self.assertRaises(RuntimeError) as ctx:
            with pool.get_connection() as conn:
                pass
                
        self.assertIn("closed", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()