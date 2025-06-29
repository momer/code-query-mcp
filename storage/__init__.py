"""Storage module for Code Query MCP Server.

This module provides the storage backend interface and implementations.
"""

from .backend import StorageBackend
from .models import (
    SearchResult,
    FileDocumentation,
    DatasetMetadata,
    BatchOperationResult
)
from .sqlite_backend import SqliteBackend
from .connection_pool import ConnectionPool
from .transaction import (
    TransactionManager,
    TransactionContext,
    get_transaction_context,
    atomic,
    transactional,
    BatchTransaction
)

__all__ = [
    # Backend interface
    'StorageBackend',
    
    # Data models
    'SearchResult',
    'FileDocumentation', 
    'DatasetMetadata',
    'BatchOperationResult',
    
    # Implementations
    'SqliteBackend',
    
    # Utilities
    'ConnectionPool',
    'TransactionManager',
    'TransactionContext',
    'get_transaction_context',
    'atomic',
    'transactional',
    'BatchTransaction'
]