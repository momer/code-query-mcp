"""SQLite implementation of the storage backend interface."""

import json
import sqlite3
import os
import dataclasses
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from .backend import StorageBackend
from .models import SearchResult, FileDocumentation, DatasetMetadata, BatchOperationResult
from .connection_pool import ConnectionPool
from .transaction import BatchTransaction
from .migrations import SchemaMigrator

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
    
    def __init__(self, db_path: str, max_connections: int = 5):
        """Initialize SQLite backend.
        
        Args:
            db_path: Path to the SQLite database file
            max_connections: Maximum number of connections in pool
        """
        self.db_path = db_path
        self.connection_pool = ConnectionPool(db_path, max_connections=max_connections)
        
        # Ensure database directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        # Initialize schema
        self.ensure_schema()
        
    def _build_fts5_query(self, query: str) -> str:
        """Build a properly formatted FTS5 query from user input."""
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
        
    # Search Operations
    def search_metadata(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against indexed metadata fields (excluding full_content)."""
        clean_query = self._build_fts5_query(fts_query)
        
        # Build a query that searches specific metadata columns
        # Exclude full_content from metadata search
        metadata_columns = [
            'filepath', 'filename', 'overview', 'ddd_context',
            'functions', 'exports', 'imports', 'types_interfaces_classes',
            'constants', 'dependencies', 'other_notes'
        ]
        
        # Create column-specific search query
        column_queries = [f'{col}:({clean_query})' for col in metadata_columns]
        combined_query = ' OR '.join(column_queries)
        
        with self.connection_pool.get_connection() as conn:
            cursor = conn.execute("""
                SELECT DISTINCT 
                    f.filepath,
                    f.filename,
                    f.dataset_id as dataset,
                    f.overview,
                    f.ddd_context,
                    snippet(files_fts, -1, '[MATCH]', '[/MATCH]', '...', 64) as snippet,
                    rank as score
                FROM files f
                JOIN files_fts ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ?
                AND f.dataset_id = ?
                ORDER BY rank
                LIMIT ?
            """, (combined_query, dataset, limit))
            
            return [self._row_to_search_result(row) for row in cursor]
            
    def search_content(self, fts_query: str, dataset: str, limit: int = 10) -> List[SearchResult]:
        """Search against full file content."""
        clean_query = self._build_fts5_query(fts_query)
        
        with self.connection_pool.get_connection() as conn:
            # Use a more sophisticated query that checks for content matches
            # by verifying the search term appears in full_content
            cursor = conn.execute("""
                WITH matches AS (
                    SELECT 
                        f.filepath,
                        f.filename,
                        f.dataset_id as dataset,
                        f.overview,
                        f.ddd_context,
                        f.full_content,
                        snippet(files_fts, 12, '[MATCH]', '[/MATCH]', '...', 128) as snippet,
                        rank as score
                    FROM files f
                    JOIN files_fts ON f.rowid = files_fts.rowid
                    WHERE files_fts MATCH ?
                    AND f.dataset_id = ?
                )
                SELECT 
                    filepath, filename, dataset, overview, ddd_context, snippet, score
                FROM matches
                WHERE LOWER(full_content) LIKE '%' || LOWER(?) || '%'
                ORDER BY score
                LIMIT ?
            """, (clean_query, dataset, clean_query, limit))
            
            return [self._row_to_search_result(row) for row in cursor]
            
    def search_unified(self, fts_query: str, dataset: str, limit: int = 10) -> Tuple[List[SearchResult], List[SearchResult], Dict[str, int]]:
        """Performs both metadata and content search with deduplication."""
        # Get results from both search types
        metadata_results = self.search_metadata(fts_query, dataset, limit)
        content_results = self.search_content(fts_query, dataset, limit)
        
        # Track which files we've seen in metadata results
        metadata_files = {r.filepath for r in metadata_results}
        
        # Filter content results to only include files not in metadata results
        content_only_results = [
            r for r in content_results 
            if r.filepath not in metadata_files
        ]
        
        # Compile statistics
        stats = {
            'total_metadata_matches': len(metadata_results),
            'total_content_matches': len(content_results),
            'unique_files': len(metadata_files) + len(content_only_results),
            'duplicate_matches': len(content_results) - len(content_only_results)
        }
        
        return metadata_results, content_only_results, stats
        
    # Document Operations
    def get_file_documentation(self, filepath: str, dataset: str, include_content: bool = False) -> Optional[FileDocumentation]:
        """Retrieve file documentation."""
        # Handle partial path matching
        filepath_pattern = f"%{filepath}" if not filepath.startswith('/') else filepath
        
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
                WHERE filepath LIKE ?
                AND dataset_id = ?
                LIMIT 1
            """, (filepath_pattern, dataset))
            
            row = cursor.fetchone()
            if not row:
                return None
                
            # Use helper method to convert row to DTO
            return self._row_to_doc(row)
            
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
                
                # Sync FTS table
                conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                
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
                
                # Sync FTS table after batch insert
                conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                
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
        
        # Handle JSON fields
        for field, value in updates.items():
            if field in self._DOC_JSON_FIELDS and value is not None:
                params[field] = json.dumps(value)
            else:
                params[field] = value
                
            set_clauses.append(f"{field} = :{field}")
            
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
                if cursor.rowcount > 0:
                    # Sync FTS table
                    conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                    return True
                return False
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
                
                if cursor.rowcount > 0:
                    # Sync FTS table
                    conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
                    return True
                return False
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
            
            # Populate FTS table with existing data
            conn.execute("""
                INSERT INTO files_fts(files_fts) VALUES('rebuild')
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
        
    def close(self):
        """Close the backend and clean up resources."""
        self.connection_pool.close()