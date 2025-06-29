"""Thread-safe SQLite connection pool for Code Query MCP Server."""

import sqlite3
import threading
from queue import Queue, Empty
from contextlib import contextmanager
import logging
from typing import Optional, Generator

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe SQLite connection pool.
    
    Manages a pool of SQLite connections to avoid the overhead of creating
    new connections for each operation. Particularly useful for web servers
    and concurrent access scenarios.
    
    Note: SQLite has limitations with concurrent writes, but this pool helps
    manage connections efficiently for read-heavy workloads.
    """
    
    def __init__(self, db_path: str, max_connections: int = 5, timeout: int = 10):
        """Initialize connection pool.
        
        Args:
            db_path: Path to the SQLite database file
            max_connections: Maximum number of connections to maintain
            timeout: Timeout in seconds when waiting for a connection
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: Queue = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False
        
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper configuration."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        
        # Use WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode = WAL")
        
        # Set busy timeout to handle concurrent access
        conn.execute("PRAGMA busy_timeout = 5000")  # 5 seconds
        
        return conn
        
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool.
        
        This is a context manager that automatically returns the connection
        to the pool when done.
        
        Yields:
            sqlite3.Connection: A database connection
            
        Raises:
            RuntimeError: If pool is closed
            TimeoutError: If no connection available within timeout
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")
            
        conn = None
        try:
            # Try to get from pool
            try:
                conn = self._pool.get_nowait()
            except Empty:
                # Create new connection if under limit
                with self._lock:
                    if self._created < self.max_connections:
                        conn = self._create_connection()
                        self._created += 1
                        logger.debug(f"Created new connection ({self._created}/{self.max_connections})")
                    else:
                        # Wait for available connection
                        logger.debug(f"Connection pool exhausted. Waiting up to {self.timeout}s...")
                        try:
                            conn = self._pool.get(timeout=self.timeout)
                        except Empty:
                            raise TimeoutError(
                                f"No connection available after {self.timeout}s. "
                                f"Consider increasing max_connections (currently {self.max_connections})"
                            )
            
            # Test connection is still valid
            try:
                conn.execute("SELECT 1")
            except sqlite3.Error:
                logger.warning("Connection was invalid, creating new one")
                conn.close()
                conn = self._create_connection()
            
            yield conn
            
        except Exception:
            # On any error, don't return connection to pool
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created -= 1
            raise
        else:
            # Return connection to pool on success
            if conn and not self._closed:
                self._pool.put(conn)
                
    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Execute operations in a transaction.
        
        Automatically commits on success or rolls back on error.
        
        Yields:
            sqlite3.Connection: A database connection in a transaction
        """
        with self.get_connection() as conn:
            try:
                # Start explicit transaction
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
                
    def execute(self, query: str, params: Optional[tuple] = None) -> sqlite3.Cursor:
        """Execute a single query and return cursor.
        
        Convenience method for simple queries.
        
        Args:
            query: SQL query to execute
            params: Optional query parameters
            
        Returns:
            sqlite3.Cursor: Query results cursor
        """
        with self.get_connection() as conn:
            if params:
                return conn.execute(query, params)
            else:
                return conn.execute(query)
                
    def close(self):
        """Close all connections in the pool.
        
        Should be called when shutting down the application.
        """
        self._closed = True
        
        # Close all connections in pool
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
                
        logger.info(f"Connection pool closed. Had {self._created} connections.")
        
    def get_pool_stats(self) -> dict:
        """Get statistics about the connection pool.
        
        Returns:
            dict: Pool statistics including size, available connections, etc.
        """
        return {
            'max_connections': self.max_connections,
            'created_connections': self._created,
            'available_connections': self._pool.qsize(),
            'in_use_connections': self._created - self._pool.qsize(),
            'is_closed': self._closed
        }
        
    def __enter__(self):
        """Context manager support."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        self.close()