# PR 2: Extract Storage Backend Interface with DTOs

## Overview
This PR establishes a clean domain-oriented storage interface with Data Transfer Objects (DTOs), laying the foundation for future refactoring. It introduces an abstract storage backend that hides SQL implementation details from the rest of the application.

**Size**: Large | **Risk**: Medium | **Value**: High

## Dependencies
- PR 1 must be completed first (tokenizer fixes)
- This PR blocks PR 4 (Search Service) and PR 5 (Dataset Service)

## Objectives
1. Create abstract storage interface with domain-oriented methods
2. Define DTOs for all data structures crossing domain boundaries
3. Implement SQLite backend using existing functionality
4. Introduce batch operations for performance
5. Maintain backward compatibility during transition

## Implementation Steps

### Step 1: Create Directory Structure
Create new module structure:
```
storage/
├── __init__.py           # Export main interfaces
├── backend.py            # Abstract storage interface
├── models.py             # Data Transfer Objects (DTOs)
├── sqlite_backend.py     # SQLite implementation
├── connection_pool.py    # Connection management
├── transaction.py        # Transaction handling
└── sqlite_storage.py     # Existing (will adapt to use new backend)
```

### Step 2: Define Data Transfer Objects
**File**: `storage/models.py`
- Create dataclasses for all domain objects
- Include type hints and documentation
- Design for forward compatibility
- Consider serialization needs

### Step 3: Define Storage Backend Interface
**File**: `storage/backend.py`
- Abstract base class with domain-oriented methods
- No SQL knowledge exposed
- Clear method signatures with DTOs
- Include batch operations

### Step 4: Implement Connection Management
**File**: `storage/connection_pool.py`
- Thread-safe connection pooling
- Handle SQLite's threading limitations
- Connection lifecycle management
- Error recovery

### Step 5: Implement Transaction Support
**File**: `storage/transaction.py`
- Context manager for transactions
- Nested transaction support
- Automatic rollback on errors
- Clear transaction boundaries

### Step 6: Implement SQLite Backend
**File**: `storage/sqlite_backend.py`
- Implement all abstract methods
- Move SQL logic from sqlite_storage.py
- Use existing tested SQL queries
- Add batch operation optimizations

### Step 7: Update Existing Storage
**File**: `storage/sqlite_storage.py`
- Create internal SqliteBackend instance
- Delegate operations to backend
- Maintain existing public API
- Gradual migration approach

## Detailed Implementation

### storage/models.py
```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class SearchResult:
    """Result from a search operation."""
    filepath: str
    filename: str
    dataset: str
    score: float
    snippet: str
    overview: Optional[str] = None
    ddd_context: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'filepath': self.filepath,
            'filename': self.filename,
            'dataset': self.dataset,
            'score': self.score,
            'snippet': self.snippet,
            'overview': self.overview,
            'ddd_context': self.ddd_context
        }

@dataclass
class FileDocumentation:
    """Complete documentation for a file."""
    filepath: str
    filename: str
    overview: str
    dataset: str
    ddd_context: Optional[str] = None
    functions: Optional[Dict[str, Any]] = None
    exports: Optional[Dict[str, Any]] = None
    imports: Optional[Dict[str, Any]] = None
    types_interfaces_classes: Optional[Dict[str, Any]] = None
    constants: Optional[Dict[str, Any]] = None
    dependencies: Optional[List[str]] = None
    other_notes: Optional[List[str]] = None
    full_content: Optional[str] = None
    documented_at_commit: Optional[str] = None
    documented_at: Optional[datetime] = None
    
    def to_sql_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for SQL insertion."""
        import dataclasses
        import json
        
        JSON_FIELDS = {
            'functions', 'exports', 'imports', 'types_interfaces_classes', 
            'constants', 'dependencies', 'other_notes'
        }
        
        data = dataclasses.asdict(self)
        
        for field_name in JSON_FIELDS:
            if data.get(field_name) is not None:
                data[field_name] = json.dumps(data[field_name])
                
        return data
    
    def to_sql_tuple(self) -> tuple:
        """Convert to tuple for executemany operations."""
        sql_dict = self.to_sql_dict()
        # Return fields in the order expected by the INSERT statement
        return (
            sql_dict['filepath'], sql_dict['filename'], sql_dict['dataset'],
            sql_dict['overview'], sql_dict.get('ddd_context'),
            sql_dict.get('functions'), sql_dict.get('exports'), 
            sql_dict.get('imports'), sql_dict.get('types_interfaces_classes'),
            sql_dict.get('constants'), sql_dict.get('dependencies'),
            sql_dict.get('other_notes'), sql_dict.get('full_content'),
            sql_dict.get('documented_at_commit')
        )

@dataclass
class DatasetMetadata:
    """Metadata for a dataset."""
    dataset_id: str
    source_dir: str
    files_count: int
    loaded_at: datetime
    dataset_type: str = 'main'
    parent_dataset_id: Optional[str] = None
    source_branch: Optional[str] = None
    
@dataclass
class BatchOperationResult:
    """Result of a batch operation."""
    total_items: int
    successful: int
    failed: int
    error_details: List[Dict[str, Any]] = field(default_factory=list)
```

### storage/backend.py
```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from .models import SearchResult, FileDocumentation, DatasetMetadata, BatchOperationResult

class StorageBackend(ABC):
    """Domain-oriented storage interface."""
    
    # Search Operations
    @abstractmethod
    def search_metadata(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against indexed metadata fields."""
        
    @abstractmethod
    def search_content(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against full file content."""
        
    @abstractmethod
    def search_unified(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """
        Performs both metadata and content search, returning a single,
        deduplicated and ranked list of results.
        """
        
    # Document Operations    
    @abstractmethod
    def get_file_documentation(self, filepath: str, dataset: str, include_content: bool = False) -> Optional[FileDocumentation]:
        """
        Retrieve file documentation.
        Args:
            filepath: The path to the file.
            dataset: The dataset the file belongs to.
            include_content: If True, populates the 'full_content' field. Defaults to False.
        """
        
    @abstractmethod
    def insert_documentation(self, doc: FileDocumentation) -> bool:
        """Insert or update file documentation."""
        
    @abstractmethod
    def insert_documentation_batch(self, docs: List[FileDocumentation]) -> BatchOperationResult:
        """Insert or update multiple file documentations efficiently."""
        
    @abstractmethod
    def update_documentation(self, filepath: str, dataset: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of existing documentation."""
        
    @abstractmethod
    def delete_documentation(self, filepath: str, dataset: str) -> bool:
        """Remove a file's documentation from the index."""
        
    # Dataset Operations
    @abstractmethod
    def get_dataset_metadata(self, dataset_id: str) -> Optional[DatasetMetadata]:
        """Retrieve dataset metadata."""
        
    @abstractmethod
    def list_datasets(self) -> List[DatasetMetadata]:
        """List all datasets with metadata."""
        
    @abstractmethod
    def create_dataset(self, dataset_id: str, source_dir: str, 
                      dataset_type: str = 'main', parent_id: Optional[str] = None) -> bool:
        """Create a new dataset."""
        
    @abstractmethod
    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset and all associated data."""
        
    @abstractmethod
    def get_dataset_files(self, dataset_id: str) -> List[str]:
        """Get all file paths in a dataset."""
```

### storage/connection_pool.py
```python
import sqlite3
import threading
from queue import Queue, Empty
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class ConnectionPool:
    """Thread-safe SQLite connection pool."""
    
    def __init__(self, db_path: str, max_connections: int = 5, timeout: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout  # Configurable timeout
        self._pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created = 0
        
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
        
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
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
                    else:
                        # Wait for available connection
                        logger.warning(f"Connection pool exhausted. Waiting for up to {self.timeout}s.")
                        conn = self._pool.get(timeout=self.timeout)
            
            yield conn
            
        finally:
            # Return connection to pool
            if conn:
                self._pool.put(conn)
                
    @contextmanager
    def transaction(self):
        """Execute operations in a transaction."""
        with self.get_connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
```

### storage/sqlite_backend.py (partial)
```python
import json
import sqlite3
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from .backend import StorageBackend
from .models import SearchResult, FileDocumentation, DatasetMetadata, BatchOperationResult
from .connection_pool import ConnectionPool

logger = logging.getLogger(__name__)

class SqliteBackend(StorageBackend):
    """SQLite implementation of storage backend."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection_pool = ConnectionPool(db_path)
        
    def search_metadata(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Implements FTS5 metadata search."""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    f.filepath,
                    f.filename,
                    f.dataset,
                    snippet(files_fts, 3, '<b>', '</b>', '...', 15) as snippet,
                    f.overview,
                    f.ddd_context,
                    rank as score
                FROM files_fts
                JOIN files f ON files_fts.rowid = f.id
                WHERE files_fts MATCH ? AND f.dataset = ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, dataset, limit))
            
            results = []
            for row in cursor:
                results.append(SearchResult(
                    filepath=row['filepath'],
                    filename=row['filename'],
                    dataset=row['dataset'],
                    score=-row['score'],  # Convert rank to score
                    snippet=row['snippet'],
                    overview=row['overview'],
                    ddd_context=row['ddd_context']
                ))
            
            return results
            
    def insert_documentation_batch(self, docs: List[FileDocumentation]) -> BatchOperationResult:
        """Batch insert/update with transaction for efficiency using UPSERT."""
        result = BatchOperationResult(total_items=len(docs), successful=0, failed=0)
        
        # Prepare data for batch insert
        data_to_insert = [doc.to_sql_tuple() for doc in docs]

        sql = """
            INSERT INTO files (
                filepath, filename, dataset, overview, ddd_context, functions, 
                exports, imports, types_interfaces_classes, constants, dependencies, 
                other_notes, full_content, documented_at_commit, documented_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(filepath, dataset) DO UPDATE SET
                filename=excluded.filename,
                overview=excluded.overview,
                ddd_context=excluded.ddd_context,
                functions=excluded.functions,
                exports=excluded.exports,
                imports=excluded.imports,
                types_interfaces_classes=excluded.types_interfaces_classes,
                constants=excluded.constants,
                dependencies=excluded.dependencies,
                other_notes=excluded.other_notes,
                full_content=excluded.full_content,
                documented_at_commit=excluded.documented_at_commit,
                documented_at=CURRENT_TIMESTAMP
        """

        with self.connection_pool.transaction() as conn:
            try:
                cursor = conn.cursor()
                cursor.executemany(sql, data_to_insert)
                # Note: executemany typically succeeds or fails as a whole.
                # This trades per-row error reporting for significant performance gains.
                result.successful = len(docs)
            except sqlite3.Error as e:
                result.failed = len(docs)
                result.error_details.append({'error': f"Batch failed: {e}"})
                logger.error(f"Batch insert failed: {e}")
                raise  # The transaction context manager will handle rollback
                
        return result
```

## Testing Plan

### Unit Tests

#### test_models.py
```python
def test_search_result_serialization():
    """Test SearchResult to_dict method."""
    
def test_file_documentation_sql_conversion():
    """Test FileDocumentation to_sql_dict method."""
    
def test_dataclass_defaults():
    """Test optional fields have correct defaults."""
```

#### test_connection_pool.py
```python
def test_connection_pool_thread_safety():
    """Test concurrent access to connection pool."""
    
def test_connection_pool_limits():
    """Test max connection enforcement."""
    
def test_transaction_rollback():
    """Test automatic rollback on error."""
```

#### test_sqlite_backend.py
```python
def test_search_metadata_returns_dtos():
    """Test search returns proper SearchResult objects."""
    
def test_batch_insert_performance():
    """Test batch insert is faster than individual inserts."""
    
def test_batch_insert_partial_failure():
    """Test batch continues on individual failures."""
    
def test_dto_round_trip():
    """Test insert and retrieve maintains data integrity."""
```

### Integration Tests
```python
def test_backend_interface_compliance():
    """Test SqliteBackend implements all abstract methods."""
    
def test_existing_storage_compatibility():
    """Test sqlite_storage.py works with new backend."""
    
def test_migration_from_direct_sql():
    """Test gradual migration approach works."""
```

## Migration Strategy

### Phase 1: Parallel Implementation (This PR)
1. Create new backend infrastructure alongside existing code
2. Implement SqliteBackend using existing SQL from sqlite_storage.py
3. No breaking changes to public API

### Phase 2: Internal Migration
1. Update sqlite_storage.py to use SqliteBackend internally
2. Maintain all existing public methods
3. Gradual method-by-method migration

### Phase 3: Service Migration (Future PRs)
1. New services use StorageBackend interface directly
2. Old code continues using sqlite_storage.py
3. No flag days or breaking changes

## Performance Considerations

### Batch Operations
- Use `executemany()` with UPSERT for bulk inserts
- Single transaction for entire batch (all-or-nothing behavior)
- Trade-off: Per-row error reporting sacrificed for 5-10x performance gains
- Consider chunking very large batches to limit transaction size
- Progress callbacks for long-running operations

### Connection Pooling
- Reuse connections to avoid overhead
- Thread-local storage for connection affinity
- Configurable pool size
- Connection health checks

### DTO Overhead
- Minimal object creation overhead
- Lazy loading for expensive fields
- Efficient serialization/deserialization
- Consider slots for memory efficiency

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| DTO/SQL mismatch | Data loss or errors | Comprehensive round-trip tests |
| Performance regression | Slower operations | Benchmark before/after, optimize hot paths |
| Thread safety issues | Data corruption | Thorough concurrent testing |
| Migration complexity | Development delays | Gradual migration, maintain compatibility |
| Memory overhead | Higher resource usage | Monitor memory, use slots if needed |

## Success Criteria

1. **Interface Completeness**:
   - All storage operations expressible through interface
   - No SQL knowledge needed by consumers
   - Clear domain boundaries

2. **Performance**:
   - Batch operations 5-10x faster than individual
   - No regression in single operation performance
   - Connection pool reduces overhead

3. **Code Quality**:
   - 100% test coverage on new code
   - Type hints on all public methods
   - Clear documentation and examples

4. **Migration Safety**:
   - Existing code continues working unchanged
   - No data migration required
   - Gradual adoption possible

## Documentation Updates

1. Add docstrings to all new classes and methods
2. Create migration guide for using new backend
3. Document batch operation best practices
4. Add performance tuning guide

## Review Checklist

- [ ] All abstract methods implemented
- [ ] DTOs cover all data structures
- [ ] Batch operations properly optimized
- [ ] Connection pool thread-safe
- [ ] Transaction boundaries correct
- [ ] Tests comprehensive
- [ ] Performance benchmarked
- [ ] Documentation complete