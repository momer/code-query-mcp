"""Transaction management utilities for Code Query MCP Server."""

import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional, Generator, Any, Callable
from threading import local

logger = logging.getLogger(__name__)


class TransactionManager:
    """Manages database transactions with support for nesting via savepoints.
    
    SQLite doesn't support true nested transactions, but we can simulate them
    using savepoints. This allows for more flexible transaction management
    in complex operations.
    """
    
    def __init__(self, connection: sqlite3.Connection):
        """Initialize transaction manager.
        
        Args:
            connection: SQLite database connection
        """
        self.connection = connection
        self._savepoint_counter = 0
        self._active_savepoints = []
        
    @contextmanager
    def transaction(self, name: Optional[str] = None) -> Generator[None, None, None]:
        """Create a transaction context.
        
        If already in a transaction, creates a savepoint instead.
        
        Args:
            name: Optional name for the transaction/savepoint
            
        Yields:
            None
        """
        in_transaction = self.connection.in_transaction
        
        if not in_transaction:
            # Start a new transaction
            logger.debug(f"Starting transaction{f' ({name})' if name else ''}")
            self.connection.execute("BEGIN")
            try:
                yield
                self.connection.commit()
                logger.debug(f"Committed transaction{f' ({name})' if name else ''}")
            except Exception as e:
                logger.error(f"Rolling back transaction{f' ({name})' if name else ''}: {e}")
                self.connection.rollback()
                raise
        else:
            # Create a savepoint for nested transaction
            savepoint_name = name or f"sp_{self._savepoint_counter}"
            self._savepoint_counter += 1
            self._active_savepoints.append(savepoint_name)
            
            logger.debug(f"Creating savepoint: {savepoint_name}")
            self.connection.execute(f"SAVEPOINT {savepoint_name}")
            
            try:
                yield
                # Release savepoint on success
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                logger.debug(f"Released savepoint: {savepoint_name}")
            except Exception as e:
                # Rollback to savepoint on error
                logger.error(f"Rolling back to savepoint {savepoint_name}: {e}")
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                raise
            finally:
                self._active_savepoints.remove(savepoint_name)


class TransactionContext:
    """Thread-local transaction context for managing transaction state.
    
    This allows different parts of the application to participate in the
    same transaction without explicitly passing connection objects around.
    """
    
    def __init__(self):
        """Initialize thread-local storage."""
        self._local = local()
        
    @property
    def connection(self) -> Optional[sqlite3.Connection]:
        """Get current thread's connection if in transaction."""
        return getattr(self._local, 'connection', None)
        
    @property
    def transaction_manager(self) -> Optional[TransactionManager]:
        """Get current thread's transaction manager."""
        return getattr(self._local, 'manager', None)
        
    @contextmanager
    def begin(self, connection: sqlite3.Connection, name: Optional[str] = None):
        """Begin a transaction on the given connection.
        
        Args:
            connection: Database connection to use
            name: Optional transaction name
            
        Yields:
            TransactionManager: The transaction manager for this transaction
        """
        if self.connection is not None:
            # Already in a transaction, use nested transaction
            with self.transaction_manager.transaction(name):
                yield self.transaction_manager
        else:
            # New transaction
            self._local.connection = connection
            self._local.manager = TransactionManager(connection)
            
            try:
                with self._local.manager.transaction(name):
                    yield self._local.manager
            finally:
                # Clean up thread-local state
                self._local.connection = None
                self._local.manager = None


# Global transaction context
_transaction_context = TransactionContext()


def get_transaction_context() -> TransactionContext:
    """Get the global transaction context."""
    return _transaction_context


@contextmanager
def atomic(connection: sqlite3.Connection, name: Optional[str] = None):
    """Decorator/context manager for atomic operations.
    
    Usage:
        with atomic(conn):
            # All operations here are in a transaction
            perform_operation1()
            perform_operation2()
    
    Or as a decorator:
        @atomic(conn)
        def my_function():
            # Function body runs in transaction
            pass
    
    Args:
        connection: Database connection
        name: Optional transaction name
        
    Yields:
        None
    """
    ctx = get_transaction_context()
    with ctx.begin(connection, name):
        yield


def transactional(connection_getter: Callable[[], sqlite3.Connection]):
    """Decorator for making methods transactional.
    
    The decorated method will run inside a transaction. If already in a
    transaction, it participates in the existing one via savepoints.
    
    Args:
        connection_getter: Function that returns a database connection
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            ctx = get_transaction_context()
            
            if ctx.connection:
                # Already in transaction, just run the function
                return func(*args, **kwargs)
            else:
                # Start new transaction
                conn = connection_getter()
                with atomic(conn, name=func.__name__):
                    return func(*args, **kwargs)
                    
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
        
    return decorator


class BatchTransaction:
    """Helper for efficient batch operations within a transaction.
    
    Provides utilities for chunking large batches and progress tracking.
    """
    
    def __init__(self, connection: sqlite3.Connection, batch_size: int = 1000):
        """Initialize batch transaction helper.
        
        Args:
            connection: Database connection
            batch_size: Size of each batch for chunking
        """
        self.connection = connection
        self.batch_size = batch_size
        self.total_processed = 0
        
    def execute_batch(self, query: str, data: list, 
                     progress_callback: Optional[Callable[[int, int], None]] = None):
        """Execute a batch operation with optional progress tracking.
        
        Args:
            query: SQL query with placeholders
            data: List of tuples/dicts for the query
            progress_callback: Optional callback(processed, total) for progress
            
        Returns:
            Number of rows affected
        """
        total = len(data)
        affected = 0
        
        with TransactionManager(self.connection).transaction("batch_operation"):
            # Process in chunks
            for i in range(0, total, self.batch_size):
                chunk = data[i:i + self.batch_size]
                cursor = self.connection.executemany(query, chunk)
                affected += cursor.rowcount
                
                self.total_processed += len(chunk)
                
                if progress_callback:
                    progress_callback(self.total_processed, total)
                    
        return affected