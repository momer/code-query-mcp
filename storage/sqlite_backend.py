"""SQLite implementation of the storage backend interface."""

import json
import sqlite3
import os
import dataclasses
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging
import threading
import signal
from contextlib import contextmanager

from .backend import StorageBackend
from .models import SearchResult, FileDocumentation, DatasetMetadata, BatchOperationResult
from .connection_pool import ConnectionPool
from .transaction import BatchTransaction
from .migrations import SchemaMigrator
from search.search_service import SearchService, SearchConfig, SearchMode
from search.models import FileMetadata as SearchFileMetadata, SearchResult as SearchServiceResult

logger = logging.getLogger(__name__)


class SqliteBackend(StorageBackend):
    """SQLite implementation of storage backend.
    
    This implementation uses FTS5 for full-text search and maintains
    backward compatibility with the existing schema.
    """
    
    # JSON fields in the file documentation
    _DOC_JSON_FIELDS = {
        'functions', 'exports', 'imports', 'types_interfaces_classes',
        'constants', 'dependencies', 'other_notes'
    }
    
    # Whitelist of updatable fields for security
    _UPDATABLE_DOC_FIELDS = {
        'filename', 'overview', 'ddd_context', 'functions', 'exports', 
        'imports', 'types_interfaces_classes', 'constants', 'dependencies', 
        'other_notes', 'full_content', 'documented_at_commit'
    }
    
    def __init__(self, db_path: str, max_connections: int = 5, search_service: Optional[SearchService] = None):
        """Initialize SQLite backend.
        
        Args:
            db_path: Path to the SQLite database file
            max_connections: Maximum number of connections in pool
            search_service: Optional SearchService instance for search operations
        """
        self.db_path = db_path
        self.connection_pool = ConnectionPool(db_path, max_connections=max_connections)
        
        # Ensure database directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        # Initialize schema
        self.ensure_schema()
        
        # Initialize search service with self as the storage backend
        self.search_service = search_service or SearchService(storage_backend=self)
        
    def _build_fts5_query(self, query: str) -> str:
        """Build a properly formatted FTS5 query from user input.
        
        NOTE: This method is deprecated in favor of SearchService.
        It's kept for backward compatibility but delegates to SearchService.
        """
        # Basic query sanitization and formatting
        # This is a simplified version - you may want to expand this
        import re
        
        # Remove potentially problematic characters while preserving FTS5 syntax
        # Keep: alphanumeric, spaces, quotes, operators (AND, OR, NOT), wildcards (*)
        cleaned = re.sub(r'[^\w\s"*\-+()]', ' ', query)
        
        # Collapse multiple spaces
        cleaned = ' '.join(cleaned.split())
        
        return cleaned
        
    def _row_to_search_result(self, row: sqlite3.Row) -> SearchResult:
        """Convert a database row from a search query to a SearchResult DTO."""
        return SearchResult(
            filepath=row['filepath'],
            filename=row['filename'],
            dataset=row['dataset'],
            score=-row['score'],  # Convert FTS5 rank to score (lower rank = better)
            snippet=row['snippet'],
            overview=row['overview'],
            ddd_context=row['ddd_context']
        )
        
    def _search_service_result_to_storage_result(self, result: SearchServiceResult) -> SearchResult:
        """Convert SearchService result to storage SearchResult."""
        # Extract metadata fields if available
        overview = None
        ddd_context = None
        filename = result.file_path.split('/')[-1] if result.file_path else ''
        
        if result.metadata:
            overview = result.metadata.overview
            ddd_context = result.metadata.ddd_context if hasattr(result.metadata, 'ddd_context') else None
            filename = result.metadata.file_name
        
        return SearchResult(
            filepath=result.file_path,
            filename=filename,
            dataset=result.dataset_id,
            score=result.relevance_score,
            snippet=result.snippet or result.match_content,
            overview=overview,
            ddd_context=ddd_context
        )
        
    def _row_to_search_file_metadata(self, row: sqlite3.Row) -> SearchFileMetadata:
        """Convert a database row to SearchFileMetadata for SearchService."""
        # Convert Row to dict for easier access
        row_dict = dict(row)
        
        # Parse JSON fields
        functions = []
        exports = []
        
        if row_dict.get('functions'):
            try:
                functions_data = json.loads(row_dict['functions'])
                if isinstance(functions_data, dict):
                    functions = list(functions_data.keys())
                elif isinstance(functions_data, list):
                    functions = functions_data
            except (json.JSONDecodeError, TypeError):
                pass
                
        if row_dict.get('exports'):
            try:
                exports_data = json.loads(row_dict['exports'])
                if isinstance(exports_data, dict):
                    exports = list(exports_data.keys())
                elif isinstance(exports_data, list):
                    exports = exports_data
            except (json.JSONDecodeError, TypeError):
                pass
        
        return SearchFileMetadata(
            file_id=row_dict.get('rowid', 0),
            file_path=row_dict['filepath'],
            file_name=row_dict['filename'],
            file_extension=os.path.splitext(row_dict['filename'])[1] if row_dict.get('filename') else '',
            file_size=0,  # Not stored in current schema
            last_modified=row_dict.get('documented_at', ''),
            content_hash='',  # Not stored in current schema
            dataset_id=row_dict.get('dataset_id', row_dict.get('dataset', '')),
            overview=row_dict.get('overview', ''),
            language='',  # Not stored in current schema - could be inferred from extension
            functions=functions,
            exports=exports
        )
        
    @contextmanager
    def _query_timeout(self, conn: sqlite3.Connection, timeout_ms: Optional[int] = None):
        """Context manager for query timeout handling.
        
        Uses SQLite's interrupt mechanism to cancel long-running queries.
        
        Args:
            conn: SQLite connection to monitor
            timeout_ms: Timeout in milliseconds (None = no timeout)
            
        Yields:
            The connection for query execution
        """
        if not timeout_ms or timeout_ms <= 0:
            # No timeout requested
            yield conn
            return
            
        timer = None
        interrupted = threading.Event()
        
        def interrupt_query():
            """Interrupt the SQLite query after timeout."""
            logger.warning(f"Query timeout after {timeout_ms}ms, interrupting...")
            interrupted.set()
            try:
                conn.interrupt()
            except Exception as e:
                logger.error(f"Failed to interrupt query: {e}")
        
        try:
            # Schedule the interrupt
            timer = threading.Timer(timeout_ms / 1000.0, interrupt_query)
            timer.start()
            
            yield conn
            
        finally:
            # Cancel timer if query completed before timeout
            if timer and timer.is_alive():
                timer.cancel()
                
            # Check if we were interrupted
            if interrupted.is_set():
                raise TimeoutError(f"Query exceeded timeout of {timeout_ms}ms")
        
    def _doc_to_sql_params(self, doc: FileDocumentation) -> Dict[str, Any]:
        """Convert a FileDocumentation DTO to a dict for SQL operations."""
        data = dataclasses.asdict(doc)
        
        # Convert JSON fields to strings
        for field_name in self._DOC_JSON_FIELDS:
            if data.get(field_name) is not None:
                data[field_name] = json.dumps(data[field_name])
                
        return data
        
    def _row_to_doc(self, row: sqlite3.Row) -> FileDocumentation:
        """Convert a SQL row to a FileDocumentation DTO."""
        data = dict(row)
        
        # Map dataset_id to dataset if needed
        if 'dataset_id' in data:
            data['dataset'] = data.pop('dataset_id')
            
        # Parse JSON fields
        for field_name in self._DOC_JSON_FIELDS:
            if field_name in data and data[field_name]:
                try:
                    data[field_name] = json.loads(data[field_name])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse JSON for field {field_name}")
                    
        return FileDocumentation(**data)
        
    # Search Operations - Now delegating to SearchService
    def search_metadata(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against indexed metadata fields (excluding full_content)."""
        # Configure search for metadata only
        config = SearchConfig(
            search_mode=SearchMode.METADATA_ONLY,
            max_results=limit,
            enable_query_sanitization=True,
            enable_fallback=True
        )
        
        # Use SearchService
        results = self.search_service.search(fts_query, dataset, config)
        
        # Convert SearchService results to storage SearchResults
        return [self._search_service_result_to_storage_result(r) for r in results]
            
    def search_content(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against full file content."""
        # Configure search for content only
        config = SearchConfig(
            search_mode=SearchMode.CONTENT_ONLY,
            max_results=limit,
            enable_query_sanitization=True,
            enable_fallback=True
        )
        
        # Use SearchService
        results = self.search_service.search(fts_query, dataset, config)
        
        # Convert SearchService results to storage SearchResults
        return [self._search_service_result_to_storage_result(r) for r in results]
            
    def search_unified(self, fts_query: str, dataset: str, limit: int = 10) -> Tuple[List[SearchResult], List[SearchResult], Dict[str, int]]:
        """Performs both metadata and content search with deduplication."""
        # Configure unified search
        config = SearchConfig(
            search_mode=SearchMode.UNIFIED,
            max_results=limit,
            enable_query_sanitization=True,
            enable_fallback=True,
            deduplicate_results=True
        )
        
        # Use SearchService for unified search
        results = self.search_service.search(fts_query, dataset, config)
        
        # Separate results by type
        metadata_results = []
        content_results = []
        
        for result in results:
            storage_result = self._search_service_result_to_storage_result(result)
            if result.match_type == 'metadata':
                metadata_results.append(storage_result)
            else:
                content_results.append(storage_result)
        
        # Compile statistics
        stats = {
            'total_metadata_matches': len(metadata_results),
            'total_content_matches': len(content_results),
            'unique_files': len(results),
            'duplicate_matches': 0  # SearchService handles deduplication
        }
        
        return metadata_results, content_results, stats
        
    # SearchService integration methods
    def search_files(self, query: str, dataset_id: str, limit: int = 50, timeout_ms: Optional[int] = None, **kwargs) -> List[SearchFileMetadata]:
        """Search files using FTS5 - called by SearchService.
        
        This method is used by SearchService for metadata searches.
        
        Args:
            query: FTS5 search query
            dataset_id: Dataset to search in
            limit: Maximum results to return
            timeout_ms: Query timeout in milliseconds
            **kwargs: Additional parameters for future extensibility
        """
        with self.connection_pool.get_connection() as conn:
            with self._query_timeout(conn, timeout_ms):
                cursor = conn.execute("""
                    SELECT 
                        f.rowid,
                        f.filepath,
                        f.filename,
                        f.dataset_id,
                        f.overview,
                        f.ddd_context,
                        f.functions,
                        f.exports,
                        f.imports,
                        f.types_interfaces_classes,
                        f.constants,
                        f.dependencies,
                        f.other_notes,
                        f.documented_at,
                        snippet(files_fts, -1, '[MATCH]', '[/MATCH]', '...', 64) as snippet,
                        rank as score
                    FROM files f
                    JOIN files_fts ON f.rowid = files_fts.rowid
                    WHERE files_fts MATCH ?
                    AND f.dataset_id = ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, dataset_id, limit))
                
                return [self._row_to_search_file_metadata(row) for row in cursor]
            
    def search_full_content(self, query: str, dataset_id: str, limit: int = 50, include_snippets: bool = True, timeout_ms: Optional[int] = None, **kwargs) -> List[SearchServiceResult]:
        """Search full content using FTS5 - called by SearchService.
        
        This method is used by SearchService for content searches.
        
        Args:
            query: FTS5 search query
            dataset_id: Dataset to search in
            limit: Maximum results to return
            include_snippets: Whether to generate snippets
            timeout_ms: Query timeout in milliseconds
            **kwargs: Additional parameters for future extensibility
        """
        with self.connection_pool.get_connection() as conn:
            with self._query_timeout(conn, timeout_ms):
                if include_snippets:
                    sql = """
                        SELECT 
                            f.rowid,
                            f.filepath,
                            f.filename,
                            f.dataset_id,
                            f.overview,
                            f.ddd_context,
                            f.functions,
                            f.exports,
                            f.full_content,
                            f.documented_at,
                            snippet(files_fts, 12, '[MATCH]', '[/MATCH]', '...', 128) as snippet,
                            rank as score
                        FROM files f
                        JOIN files_fts ON f.rowid = files_fts.rowid
                        WHERE files_fts MATCH ?
                        AND f.dataset_id = ?
                        ORDER BY rank
                        LIMIT ?
                    """
                else:
                    sql = """
                        SELECT 
                            f.rowid,
                            f.filepath,
                            f.filename,
                            f.dataset_id,
                            f.overview,
                            f.ddd_context,
                            f.functions,
                            f.exports,
                            f.full_content,
                            f.documented_at,
                            '' as snippet,
                            rank as score
                        FROM files f
                        JOIN files_fts ON f.rowid = files_fts.rowid
                        WHERE files_fts MATCH ?
                        AND f.dataset_id = ?
                        ORDER BY rank
                        LIMIT ?
                    """
                
                cursor = conn.execute(sql, (query, dataset_id, limit))
                
                results = []
                for row in cursor:
                    # Convert row to metadata
                    metadata = self._row_to_search_file_metadata(row)
                    
                    # Create SearchServiceResult
                    result = SearchServiceResult(
                        file_path=row['filepath'],
                        dataset_id=row['dataset_id'],
                        match_content=row['full_content'][:200] if row['full_content'] else '',
                        match_type='content',
                        relevance_score=-row['score'],  # Convert rank to score
                        snippet=row['snippet'] if include_snippets else None,
                        metadata=metadata
                    )
                    results.append(result)
                    
                return results
        
    # Document Operations
    def get_file_documentation(self, filepath: str, dataset: str, include_content: bool = False) -> Optional[FileDocumentation]:
        """Retrieve file documentation."""
        with self.connection_pool.get_connection() as conn:
            # Build query based on whether we need content
            select_fields = """
                filepath, filename, dataset_id, overview, ddd_context,
                functions, exports, imports, types_interfaces_classes,
                constants, dependencies, other_notes,
                documented_at_commit, documented_at
            """
            
            if include_content:
                select_fields += ", full_content"
                
            cursor = conn.execute(f"""
                SELECT {select_fields}
                FROM files
                WHERE filepath = ?
                AND dataset_id = ?
            """, (filepath, dataset))
            
            row = cursor.fetchone()
            if not row:
                return None
                
            # Use helper method to convert row to DTO
            return self._row_to_doc(row)
    
    def get_file_documentation_batch(self, dataset: str, filepaths: List[str], include_content: bool = False) -> Dict[str, FileDocumentation]:
        """Retrieve documentation for multiple files in a single query."""
        if not filepaths:
            return {}
            
        with self.connection_pool.get_connection() as conn:
            # Build query based on whether we need content
            select_fields = """
                filepath, filename, dataset_id, overview, ddd_context,
                functions, exports, imports, types_interfaces_classes,
                constants, dependencies, other_notes,
                documented_at_commit, documented_at
            """
            
            if include_content:
                select_fields += ", full_content"
                
            # Create placeholders for SQL IN clause
            placeholders = ','.join(['?' for _ in filepaths])
            
            # Prepare parameters: dataset_id followed by all filepaths
            params = [dataset] + filepaths
            
            cursor = conn.execute(f"""
                SELECT {select_fields}
                FROM files
                WHERE dataset_id = ?
                AND filepath IN ({placeholders})
            """, params)
            
            # Build result dictionary
            result = {}
            for row in cursor:
                doc = self._row_to_doc(row)
                result[doc.filepath] = doc
                
            return result
            
    def insert_documentation(self, doc: FileDocumentation) -> bool:
        """Insert or update file documentation."""
        try:
            sql_data = self._doc_to_sql_params(doc)
            
            with self.connection_pool.transaction() as conn:
                conn.execute("""
                    INSERT INTO files (
                        dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes, full_content,
                        documented_at_commit, documented_at
                    ) VALUES (
                        :dataset, :filepath, :filename, :overview, :ddd_context,
                        :functions, :exports, :imports, :types_interfaces_classes,
                        :constants, :dependencies, :other_notes, :full_content,
                        :documented_at_commit, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT(dataset_id, filepath) DO UPDATE SET
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
                """, sql_data)
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to insert documentation: {e}")
            return False
            
    def insert_documentation_batch(self, docs: List[FileDocumentation]) -> BatchOperationResult:
        """Insert or update multiple file documentations efficiently."""
        result = BatchOperationResult(
            total_items=len(docs),
            successful=0,
            failed=0
        )
        
        if not docs:
            return result
            
        # Prepare data for batch insert
        batch_data = []
        for doc in docs:
            try:
                batch_data.append(self._doc_to_sql_params(doc))
            except Exception as e:
                result.failed += 1
                result.add_error(doc.filepath, str(e))
                
        if not batch_data:
            return result
            
        # Use batch transaction for efficiency
        with self.connection_pool.transaction() as conn:
            batch_tx = BatchTransaction(conn, batch_size=500)
            
            query = """
                INSERT INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, full_content,
                    documented_at_commit, documented_at
                ) VALUES (
                    :dataset, :filepath, :filename, :overview, :ddd_context,
                    :functions, :exports, :imports, :types_interfaces_classes,
                    :constants, :dependencies, :other_notes, :full_content,
                    :documented_at_commit, CURRENT_TIMESTAMP
                )
                ON CONFLICT(dataset_id, filepath) DO UPDATE SET
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
            
            try:
                affected = batch_tx.execute_batch(query, batch_data)
                result.successful = len(batch_data)
                
            except Exception as e:
                logger.error(f"Batch insert failed: {e}")
                result.failed = len(batch_data)
                result.add_error("batch_operation", str(e))
                raise
                
        return result
        
    def update_documentation(self, filepath: str, dataset: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of existing documentation."""
        if not updates:
            return True
            
        # Build UPDATE query dynamically
        set_clauses = []
        params = {}
        
        # Validate and filter fields for security
        for field, value in updates.items():
            # Only allow whitelisted fields
            if field not in self._UPDATABLE_DOC_FIELDS:
                logger.warning(f"Attempted to update non-permitted field: {field}")
                continue
                
            if field in self._DOC_JSON_FIELDS and value is not None:
                params[field] = json.dumps(value)
            else:
                params[field] = value
                
            set_clauses.append(f"{field} = :{field}")
            
        # If no valid fields to update, return early
        if not set_clauses:
            logger.warning("No valid fields to update")
            return False
            
        # Add update timestamp
        set_clauses.append("documented_at = CURRENT_TIMESTAMP")
        
        # Add filepath and dataset to params
        params['filepath'] = filepath
        params['dataset'] = dataset
        
        query = f"""
            UPDATE files
            SET {', '.join(set_clauses)}
            WHERE filepath = :filepath
            AND dataset_id = :dataset
        """
        
        try:
            with self.connection_pool.transaction() as conn:
                cursor = conn.execute(query, params)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update documentation: {e}")
            return False
            
    def delete_documentation(self, filepath: str, dataset: str) -> bool:
        """Remove a file's documentation from the index."""
        try:
            with self.connection_pool.transaction() as conn:
                cursor = conn.execute("""
                    DELETE FROM files
                    WHERE filepath = ?
                    AND dataset_id = ?
                """, (filepath, dataset))
                
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete documentation: {e}")
            return False
            
    # Dataset Operations
    def get_dataset_metadata(self, dataset_id: str) -> Optional[DatasetMetadata]:
        """Retrieve dataset metadata."""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute("""
                SELECT dataset_id, source_dir, files_count, loaded_at,
                       dataset_type, parent_dataset_id, source_branch
                FROM dataset_metadata
                WHERE dataset_id = ?
            """, (dataset_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
                
            return DatasetMetadata(**dict(row))
            
    def list_datasets(self) -> List[DatasetMetadata]:
        """List all datasets with metadata."""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute("""
                SELECT dataset_id, source_dir, files_count, loaded_at,
                       dataset_type, parent_dataset_id, source_branch
                FROM dataset_metadata
                ORDER BY loaded_at DESC
            """)
            
            return [DatasetMetadata(**dict(row)) for row in cursor]
            
    def create_dataset(self, dataset_id: str, source_dir: str,
                      dataset_type: str = 'main', parent_id: Optional[str] = None,
                      source_branch: Optional[str] = None) -> bool:
        """Create a new dataset."""
        try:
            with self.connection_pool.transaction() as conn:
                conn.execute("""
                    INSERT INTO dataset_metadata (
                        dataset_id, source_dir, files_count, loaded_at,
                        dataset_type, parent_dataset_id, source_branch
                    ) VALUES (?, ?, 0, CURRENT_TIMESTAMP, ?, ?, ?)
                """, (dataset_id, source_dir, dataset_type, parent_id, source_branch))
                
            return True
        except sqlite3.IntegrityError:
            logger.error(f"Dataset {dataset_id} already exists")
            return False
        except Exception as e:
            logger.error(f"Failed to create dataset: {e}")
            return False
            
    def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset and all associated data."""
        try:
            with self.connection_pool.transaction() as conn:
                # Delete all files in the dataset
                conn.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_id,))
                
                # Delete dataset metadata
                cursor = conn.execute(
                    "DELETE FROM dataset_metadata WHERE dataset_id = ?",
                    (dataset_id,)
                )
                
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete dataset: {e}")
            return False
            
    def get_dataset_files(self, dataset_id: str, limit: Optional[int] = None) -> List[str]:
        """Get all file paths in a dataset."""
        query = "SELECT filepath FROM files WHERE dataset_id = ?"
        params = [dataset_id]
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
            
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute(query, params)
            return [row['filepath'] for row in cursor]
            
    def get_dataset_file_count(self, dataset_id: str) -> int:
        """Get count of files in a dataset."""
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?",
                (dataset_id,)
            )
            return cursor.fetchone()['count']
            
    # Schema Operations
    def get_schema_version(self) -> Optional[str]:
        """Get current schema version."""
        try:
            with self.connection_pool.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return row['version'] if row else None
        except sqlite3.OperationalError:
            # Table doesn't exist
            return None
            
    def _create_schema(self, conn: sqlite3.Connection):
        """Create initial database schema."""
        # Main files table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                dataset_id TEXT NOT NULL,
                filepath TEXT NOT NULL,
                filename TEXT,
                overview TEXT,
                ddd_context TEXT,
                functions TEXT,
                exports TEXT,
                imports TEXT,
                types_interfaces_classes TEXT,
                constants TEXT,
                dependencies TEXT,
                other_notes TEXT,
                documented_at_commit TEXT,
                documented_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                full_content TEXT,
                PRIMARY KEY (dataset_id, filepath)
            )
        """)
        
        # Index for efficient queries
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_filepath ON files(dataset_id, filepath)
        """)
        
        # Dataset metadata table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dataset_metadata (
                dataset_id TEXT PRIMARY KEY,
                source_dir TEXT,
                files_count INTEGER,
                loaded_at TIMESTAMP,
                dataset_type TEXT DEFAULT 'main',
                parent_dataset_id TEXT,
                source_branch TEXT,
                FOREIGN KEY(parent_dataset_id) REFERENCES dataset_metadata(dataset_id) ON DELETE SET NULL
            )
        """)
        
        # Create FTS5 virtual table only if it doesn't exist
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        
        if not cursor.fetchone():
            conn.execute("""
                CREATE VIRTUAL TABLE files_fts USING fts5(
                    dataset_id UNINDEXED,
                    filepath,
                    filename,
                    overview,
                    ddd_context,
                    functions,
                    exports,
                    imports,
                    types_interfaces_classes,
                    constants,
                    dependencies,
                    other_notes,
                    full_content,
                    content='files',
                    content_rowid='rowid',
                    tokenize = 'unicode61 tokenchars ''._$@->:#'''
                )
            """)
            
            # Create triggers to keep FTS5 in sync with files table
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_insert AFTER INSERT ON files
                BEGIN
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview,
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
            
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_delete AFTER DELETE ON files
                BEGIN
                    DELETE FROM files_fts WHERE rowid = old.rowid;
                END
            """)
            
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_update AFTER UPDATE ON files
                BEGIN
                    DELETE FROM files_fts WHERE rowid = old.rowid;
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview,
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
        
        # Schema version table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
    def ensure_schema(self) -> bool:
        """Ensure database schema is properly initialized."""
        try:
            with self.connection_pool.get_connection() as conn:
                # Check if schema exists
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='files'
                """)
                
                if not cursor.fetchone():
                    # Create initial schema
                    self._create_schema(conn)
                    logger.info("Created initial database schema")
                
                # Run migrations
                migrator = SchemaMigrator(conn)
                migrator.migrate_to_current_version()
                
            return True
        except Exception as e:
            logger.error(f"Failed to ensure schema: {e}")
            return False
            
    # Health and Maintenance
    def vacuum(self) -> bool:
        """Optimize database storage."""
        try:
            with self.connection_pool.get_connection() as conn:
                conn.execute("VACUUM")
            return True
        except Exception as e:
            logger.error(f"Failed to vacuum database: {e}")
            return False
            
    def get_storage_info(self) -> Dict[str, Any]:
        """Get storage statistics and health information."""
        info = {
            'db_path': self.db_path,
            'db_size_bytes': 0,
            'total_files': 0,
            'total_datasets': 0,
            'schema_version': self.get_schema_version(),
            'connection_pool_stats': self.connection_pool.get_pool_stats()
        }
        
        try:
            # Get file size
            if os.path.exists(self.db_path):
                info['db_size_bytes'] = os.path.getsize(self.db_path)
                
            with self.connection_pool.get_connection() as conn:
                # Count files
                cursor = conn.execute("SELECT COUNT(*) as count FROM files")
                info['total_files'] = cursor.fetchone()['count']
                
                # Count datasets
                cursor = conn.execute("SELECT COUNT(*) as count FROM dataset_metadata")
                info['total_datasets'] = cursor.fetchone()['count']
                
                # Get page stats
                cursor = conn.execute("PRAGMA page_count")
                page_count = cursor.fetchone()[0]
                
                cursor = conn.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                
                info['page_count'] = page_count
                info['page_size'] = page_size
                
        except Exception as e:
            logger.error(f"Error getting storage info: {e}")
            
        return info
        
    # Additional Dataset Operations for DatasetService
    def delete_all_documentation(self, dataset_id: str) -> int:
        """Delete all documentation for a dataset."""
        try:
            with self.connection_pool.get_connection() as conn:
                # Count files to be deleted
                cursor = conn.execute(
                    "SELECT COUNT(*) as count FROM files WHERE dataset_id = ?",
                    (dataset_id,)
                )
                count = cursor.fetchone()['count']
                
                # Delete all files for the dataset
                conn.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_id,))
                conn.commit()
                
                logger.info(f"Deleted {count} files from dataset '{dataset_id}'")
                return count
                
        except Exception as e:
            logger.error(f"Failed to delete all documentation for dataset '{dataset_id}': {e}")
            return 0
            
    def get_dataset_statistics(self, dataset_id: str) -> "DatasetStats":
        """Calculate and return statistics for a dataset efficiently."""
        from dataset.dataset_models import DatasetStats
        from datetime import datetime
        
        try:
            with self.connection_pool.get_connection() as conn:
                # Get basic counts and stats
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_files,
                        SUM(LENGTH(full_content)) as total_size,
                        MAX(documented_at) as last_updated
                    FROM files 
                    WHERE dataset_id = ?
                """, (dataset_id,))
                
                row = cursor.fetchone()
                total_files = row['total_files'] or 0
                total_size = row['total_size'] or 0
                last_updated = row['last_updated'] or datetime.now().isoformat()
                
                # Get file type distribution by extracting extension from filename
                cursor = conn.execute("""
                    SELECT 
                        CASE 
                            WHEN INSTR(filename, '.') > 0 
                            THEN LOWER(SUBSTR(filename, INSTR(filename, '.') + 1))
                            ELSE ''
                        END as file_extension,
                        COUNT(*) as count
                    FROM files
                    WHERE dataset_id = ?
                    GROUP BY file_extension
                    ORDER BY count DESC
                """, (dataset_id,))
                
                file_types = {}
                for row in cursor:
                    ext = row['file_extension']
                    if ext:  # Only include files with extensions
                        file_types[f'.{ext}'] = row['count']
                
                # Get largest files by content length
                cursor = conn.execute("""
                    SELECT 
                        filepath,
                        LENGTH(full_content) as file_size
                    FROM files
                    WHERE dataset_id = ?
                    AND full_content IS NOT NULL
                    ORDER BY file_size DESC
                    LIMIT 10
                """, (dataset_id,))
                
                largest_files = [(row['filepath'], row['file_size']) for row in cursor]
                
                return DatasetStats(
                    dataset_id=dataset_id,
                    total_files=total_files,
                    total_size_bytes=total_size,
                    last_updated=datetime.fromisoformat(last_updated) if isinstance(last_updated, str) else last_updated,
                    file_types=file_types,
                    largest_files=largest_files
                )
                
        except Exception as e:
            logger.error(f"Failed to get statistics for dataset '{dataset_id}': {e}")
            # Return empty stats on error
            return DatasetStats(
                dataset_id=dataset_id,
                total_files=0,
                total_size_bytes=0,
                last_updated=datetime.now(),
                file_types={},
                largest_files=[]
            )
            
    def transaction(self):
        """Context manager for transactional operations."""
        return TransactionalSqliteBackend(self)
        
    def close(self):
        """Close the backend and clean up resources."""
        self.connection_pool.close()


class TransactionalSqliteBackend:
    """Wrapper for SqliteBackend that provides transaction support.
    
    This is a simplified implementation that creates a new SqliteBackend instance
    with a single connection for transaction support.
    """
    
    def __init__(self, parent_backend: SqliteBackend):
        self.parent = parent_backend
        self.backend = None
        self._conn_context = None
        
    def __enter__(self):
        """Begin transaction."""
        # Get a connection from the pool
        self._conn_context = self.parent.connection_pool.get_connection()
        conn = self._conn_context.__enter__()
        
        # Start transaction
        conn.execute("BEGIN IMMEDIATE")
        
        # Create a new backend that uses this single connection
        # This is a temporary backend just for this transaction
        self.backend = SqliteBackend(self.parent.db_path)
        
        # Override the backend's connection pool to use our single connection
        # This is a bit of a hack, but it ensures all operations use the same connection
        class SingleConnectionPool:
            def __init__(self, connection):
                self.conn = connection
                
            def get_connection(self):
                # Return a context manager that yields the connection
                class ConnectionContext:
                    def __init__(self, conn):
                        self.conn = conn
                    def __enter__(self):
                        return self.conn
                    def __exit__(self, *args):
                        pass  # Don't close the connection
                return ConnectionContext(self.conn)
                
            def close(self):
                pass  # Don't close, parent will handle it
                
        self.backend.connection_pool = SingleConnectionPool(conn)
        return self.backend
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit or rollback transaction."""
        if self._conn_context:
            conn = self._conn_context.__enter__()  # Get the actual connection
            try:
                if exc_type is None:
                    conn.commit()
                else:
                    conn.rollback()
            finally:
                # Clean up
                self._conn_context.__exit__(None, None, None)
                self._conn_context = None
                self.backend = None
        return False