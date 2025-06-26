"""SQLite storage functions and CodeQueryServer class for Code Query MCP Server."""

import os
import json
import sqlite3
import glob
import logging
import fnmatch
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional
from helpers.git_helper import get_actual_git_dir


# Global database connection
_db_connection = None


def get_db_connection(db_path: str):
    """
    Establishes and returns a SQLite connection with WAL mode enabled.
    Uses a global-like pattern to reuse the connection within the server process.
    """
    global _db_connection
    # This simple singleton pattern is okay for a single-process server.
    # For multi-process/threaded servers, you'd need thread-local storage.
    if _db_connection is None:
        try:
            # The DB_PATH is now dynamically set based on our logic above
            conn = sqlite3.connect(db_path, check_same_thread=False)  # check_same_thread for web servers
            
            # Enable WAL mode for better concurrency. This is the key change.
            conn.execute("PRAGMA journal_mode=WAL;")
            
            # Use Row factory for dict-like access to results
            conn.row_factory = sqlite3.Row
            
            _db_connection = conn
            logging.info("Database connection established with WAL mode.")
        except sqlite3.Error as e:
            logging.error(f"Database connection failed: {e}")
            raise
            
    return _db_connection


class CodeQueryServer:
    def __init__(self, db_path: str, db_dir: str):
        self.db = None
        self.cwd = os.getcwd()
        self.db_path = db_path
        self.db_dir = db_dir
        # Ensure database directory exists
        os.makedirs(db_dir, exist_ok=True)
        
    def setup_database(self):
        """Connect to persistent SQLite database."""
        self.db = get_db_connection(self.db_path)
        
        # Enable FTS5 if available
        self.db.execute("PRAGMA compile_options")
        
        # Check if schema exists
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files'
        """)
        
        if not cursor.fetchone():
            self._create_schema()
            logging.info(f"Created database schema at {self.db_path}")
        else:
            # Check if we need to migrate to newer schema
            self._migrate_schema()
            logging.info(f"Connected to existing database at {self.db_path}")
    
    def _get_actual_git_dir(self) -> Optional[str]:
        """Determines the actual .git directory path, handling worktrees."""
        return get_actual_git_dir(self.cwd)
    
    def _create_schema(self):
        """Create database schema with dataset support and FTS5."""
        # Main files table with dataset_id
        self.db.execute("""
            CREATE TABLE files (
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
                PRIMARY KEY (dataset_id, filepath)
            )
        """)
        
        # Index for efficient queries
        self.db.execute("""
            CREATE INDEX idx_dataset_filepath ON files(dataset_id, filepath)
        """)
        
        # Create dataset metadata table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS dataset_metadata (
                dataset_id TEXT PRIMARY KEY,
                source_dir TEXT,
                files_count INTEGER,
                loaded_at TIMESTAMP
            )
        """)
        
        # Try to create FTS5 virtual table
        try:
            self.db.execute("""
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
                    content='files',
                    content_rowid='rowid'
                )
            """)
            
            # Create triggers to keep FTS in sync
            self.db.execute("""
                CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes, constants, 
                        dependencies, other_notes)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes);
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes, 
                        constants, dependencies, other_notes)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes);
                END
            """)
            
            logging.info("Created FTS5 virtual table for full-text search")
        except sqlite3.OperationalError as e:
            logging.warning(f"Could not create FTS5 table: {e}")
        
        self.db.commit()
    
    def _migrate_schema(self):
        """Migrate schema to support datasets if needed."""
        # Check if dataset_id column exists
        cursor = self.db.execute("PRAGMA table_info(files)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'dataset_id' not in columns:
            logging.info("Migrating schema to support datasets...")
            
            # Create new table with dataset support
            self.db.execute("""
                CREATE TABLE files_new (
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
                    PRIMARY KEY (dataset_id, filepath)
                )
            """)
            
            # Copy existing data with default dataset name
            self.db.execute("""
                INSERT INTO files_new 
                SELECT 'default', * FROM files
            """)
            
            # Drop old table and rename new one
            self.db.execute("DROP TABLE files")
            self.db.execute("ALTER TABLE files_new RENAME TO files")
            
            # Recreate index
            self.db.execute("""
                CREATE INDEX idx_dataset_filepath ON files(dataset_id, filepath)
            """)
            
            # Recreate FTS if it existed
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files_fts'
            """)
            if cursor.fetchone():
                # Drop and recreate FTS
                self.db.execute("DROP TABLE files_fts")
                self._create_fts_table()
            
            self.db.commit()
            logging.info("Schema migration completed")
        
        # Ensure dataset_metadata table exists
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='dataset_metadata'
        """)
        
        if not cursor.fetchone():
            self.db.execute("""
                CREATE TABLE dataset_metadata (
                    dataset_id TEXT PRIMARY KEY,
                    source_dir TEXT,
                    files_count INTEGER,
                    loaded_at TIMESTAMP
                )
            """)
            self.db.commit()
    
    def _create_fts_table(self):
        """Helper to create FTS table and triggers."""
        try:
            self.db.execute("""
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
                    content='files',
                    content_rowid='rowid'
                )
            """)
            
            # Create triggers
            self.db.execute("""
                CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes, constants, 
                        dependencies, other_notes)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes);
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes, 
                        constants, dependencies, other_notes)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes);
                END
            """)
            
        except sqlite3.OperationalError as e:
            logging.warning(f"Could not create FTS5 table: {e}")
        
        # Check and migrate dataset_metadata table to add parent tracking
        cursor = self.db.execute("PRAGMA table_info(dataset_metadata)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'parent_dataset_id' not in columns:
            logging.info("Migrating dataset_metadata schema to support parent tracking...")
            
            # Add new columns for worktree tracking
            try:
                self.db.execute("""
                    ALTER TABLE dataset_metadata 
                    ADD COLUMN parent_dataset_id TEXT
                """)
                
                self.db.execute("""
                    ALTER TABLE dataset_metadata 
                    ADD COLUMN source_branch TEXT
                """)
                
                # No foreign key constraints can be added via ALTER TABLE in SQLite
                # But we've documented the relationship in the schema
                
                logging.info("Successfully added parent tracking columns to dataset_metadata")
            except sqlite3.OperationalError as e:
                logging.warning(f"Could not add parent tracking columns: {e}")
    
    def import_data(self, dataset_name: str, directory: str, replace: bool = False) -> Dict[str, Any]:
        """Import JSON files from directory into named dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Check if dataset already exists
        cursor = self.db.execute("""
            SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
        """, (dataset_name,))
        existing_count = cursor.fetchone()['count']
        
        if existing_count > 0 and not replace:
            return {
                "success": False,
                "message": f"Dataset '{dataset_name}' already exists with {existing_count} files. Use replace=true to overwrite."
            }
        
        # Clear existing data if replacing
        if replace and existing_count > 0:
            self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
            self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
            self.db.commit()
        
        # Find JSON files
        json_files = glob.glob(os.path.join(directory, "*.json"))
        if not json_files:
            return {"success": False, "message": f"No JSON files found in {directory}"}
        
        imported = 0
        errors = []
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Insert into database
                self.db.execute("""
                    INSERT OR REPLACE INTO files (
                        dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dataset_name,
                    data.get('filepath', ''),
                    data.get('filename', ''),
                    data.get('overview', ''),
                    data.get('ddd_context', ''),
                    json.dumps(data.get('functions', {})),
                    json.dumps(data.get('exports', {})),
                    json.dumps(data.get('imports', {})),
                    json.dumps(data.get('types_interfaces_classes', {})),
                    json.dumps(data.get('constants', {})),
                    json.dumps(data.get('dependencies', [])),
                    json.dumps(data.get('other_notes', []))
                ))
                imported += 1
            except Exception as e:
                errors.append(f"{json_file}: {str(e)}")
        
        # Update dataset metadata
        self.db.execute("""
            INSERT OR REPLACE INTO dataset_metadata 
            (dataset_id, source_dir, files_count, loaded_at)
            VALUES (?, ?, ?, ?)
        """, (dataset_name, directory, imported, datetime.now()))
        
        self.db.commit()
        
        # Rebuild FTS index for this dataset
        self.rebuild_fts_index(dataset_name)
        
        return {
            "success": True,
            "dataset_name": dataset_name,
            "imported": imported,
            "total_files": len(json_files),
            "errors": errors if errors else None
        }
    
    def search_files(self, query: str, dataset_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search files in dataset using FTS5 or fallback to LIKE."""
        if not self.db:
            return []
        
        results = []
        
        # Check if FTS5 is available
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        
        if cursor.fetchone():
            # Use FTS5 for search
            cursor = self.db.execute("""
                SELECT DISTINCT f.filepath, f.filename, f.overview, f.ddd_context,
                       snippet(files_fts, 2, '[MATCH]', '[/MATCH]', '...', 64) as match_snippet
                FROM files f
                JOIN files_fts ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ?
                AND f.dataset_id = ?
                ORDER BY rank
                LIMIT ?
            """, (query, dataset_name, limit))
        else:
            # Fallback to LIKE search
            like_query = f"%{query}%"
            cursor = self.db.execute("""
                SELECT filepath, filename, overview, ddd_context, 
                       overview as match_snippet
                FROM files
                WHERE dataset_id = ?
                AND (
                    filepath LIKE ? OR
                    filename LIKE ? OR
                    overview LIKE ? OR
                    ddd_context LIKE ? OR
                    functions LIKE ? OR
                    exports LIKE ? OR
                    imports LIKE ? OR
                    types_interfaces_classes LIKE ? OR
                    constants LIKE ?
                )
                LIMIT ?
            """, (dataset_name, like_query, like_query, like_query, like_query, 
                  like_query, like_query, like_query, like_query, like_query, limit))
        
        for row in cursor:
            results.append({
                "filepath": row["filepath"],
                "filename": row["filename"],
                "overview": row["overview"],
                "ddd_context": row["ddd_context"],
                "match_snippet": row["match_snippet"]
            })
        
        return results
    
    def populate_spellfix_vocabulary(self, dataset_name: str):
        """Populate spellfix vocabulary from dataset for better search suggestions."""
        if not self.db:
            return
        
        try:
            # Check if spellfix1 extension is available
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS spellfix_terms USING spellfix1")
            
            # Extract words from all text fields for this dataset
            cursor = self.db.execute("""
                SELECT filepath, filename, overview, ddd_context, functions, exports, 
                       imports, types_interfaces_classes, constants
                FROM files
                WHERE dataset_id = ?
            """, (dataset_name,))
            
            vocabulary = set()
            
            for row in cursor:
                # Extract words from each field
                for field in ['filepath', 'filename', 'overview', 'ddd_context']:
                    if row[field]:
                        # Simple word extraction (could be improved)
                        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', row[field])
                        vocabulary.update(word.lower() for word in words)
                
                # Extract from JSON fields
                for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants']:
                    if row[field]:
                        try:
                            data = json.loads(row[field])
                            if isinstance(data, dict):
                                vocabulary.update(key.lower() for key in data.keys())
                        except:
                            pass
            
            # Insert vocabulary into spellfix1
            for word in vocabulary:
                try:
                    self.db.execute("INSERT OR IGNORE INTO spellfix_terms(word) VALUES (?)", (word,))
                except Exception:
                    pass  # Ignore individual word insertion errors
            
            self.db.commit()
            logging.info(f"Added {len(vocabulary)} words to spellfix vocabulary for dataset '{dataset_name}'")
            
        except Exception as e:
            logging.debug(f"Failed to populate spellfix vocabulary: {e}")
    
    def rebuild_fts_index(self, dataset_name: str = None):
        """Rebuild FTS5 index for better performance after bulk operations."""
        try:
            # Check if FTS5 is available
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files_fts'
            """)
            
            if not cursor.fetchone():
                return {"success": False, "message": "FTS5 not available"}
            
            if dataset_name:
                # Rebuild for specific dataset
                self.db.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
            else:
                # Optimize the entire FTS index
                self.db.execute("INSERT INTO files_fts(files_fts) VALUES('optimize')")
            
            self.db.commit()
            return {"success": True, "message": "FTS5 index rebuilt successfully"}
            
        except Exception as e:
            return {"success": False, "message": f"Failed to rebuild FTS5 index: {e}"}
    
    def get_file(self, filepath: str, dataset_name: str, limit: int = 10) -> Optional[Dict[str, Any] | List[Dict[str, Any]]]:
        """Get complete details for a specific file in dataset.
        
        Supports partial matching - if filepath doesn't contain %, it will be wrapped with % for LIKE query.
        Returns single file dict if exact match, list of files if multiple matches.
        """
        if not self.db:
            return None
        
        # If filepath doesn't contain wildcards, wrap with % for flexible matching
        if '%' not in filepath:
            # Try exact match first
            cursor = self.db.execute("""
                SELECT * FROM files 
                WHERE dataset_id = ? AND filepath = ?
            """, (dataset_name, filepath))
            
            row = cursor.fetchone()
            if row:
                # Exact match found, return single result
                result = dict(row)
                for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants', 'dependencies', 'other_notes']:
                    if result.get(field):
                        try:
                            result[field] = json.loads(result[field])
                        except (json.JSONDecodeError, TypeError):
                            logging.warning(f"Could not parse JSON for field '{field}' in file '{filepath}'. Using default value.")
                            result[field] = {} if field not in ['dependencies', 'other_notes'] else []
                result.pop('dataset_id', None)
                return result
            
            # No exact match, try partial matching
            filepath = f'%{filepath}%'
        
        # Use LIKE query for partial matching
        cursor = self.db.execute("""
            SELECT * FROM files 
            WHERE dataset_id = ? AND filepath LIKE ?
            LIMIT ?
        """, (dataset_name, filepath, limit))
        
        rows = cursor.fetchall()
        if not rows:
            return None
        
        # Convert rows to list of dicts and parse JSON fields
        results = []
        for row in rows:
            result = dict(row)
            for field in ['functions', 'exports', 'imports', 'types_interfaces_classes', 'constants', 'dependencies', 'other_notes']:
                if result.get(field):
                    try:
                        result[field] = json.loads(result[field])
                    except (json.JSONDecodeError, TypeError):
                        logging.warning(f"Could not parse JSON for field '{field}' in file '{result['filepath']}'. Using default value.")
                        result[field] = {} if field not in ['dependencies', 'other_notes'] else []
            result.pop('dataset_id', None)
            results.append(result)
        
        # If only one result, return it directly for backward compatibility
        if len(results) == 1:
            return results[0]
        return results
    
    def list_domains(self, dataset_name: str) -> List[str]:
        """List unique DDD context domains in dataset."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT DISTINCT ddd_context 
            FROM files 
            WHERE dataset_id = ?
            AND ddd_context IS NOT NULL 
            AND ddd_context != ''
            ORDER BY ddd_context
        """, (dataset_name,))
        
        return [row['ddd_context'] for row in cursor]
    
    def list_datasets(self) -> List[Dict[str, Any]]:
        """List all loaded datasets with metadata."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT d.dataset_id as name, d.source_dir, d.files_count, d.loaded_at,
                   COUNT(f.filepath) as current_files
            FROM dataset_metadata d
            LEFT JOIN files f ON d.dataset_id = f.dataset_id
            GROUP BY d.dataset_id, d.source_dir, d.files_count, d.loaded_at
            ORDER BY d.loaded_at DESC
        """)
        
        datasets = []
        for row in cursor:
            datasets.append({
                "name": row['name'],
                "source_dir": row['source_dir'],
                "files_count": row['current_files'],  # Use actual count
                "loaded_at": row['loaded_at']
            })
        
        return datasets
    
    def get_status(self) -> Dict[str, Any]:
        """Get database status information."""
        if not self.db:
            return {"connected": False}
        
        try:
            # Get table information
            cursor = self.db.execute("""
                SELECT COUNT(DISTINCT dataset_id) as dataset_count,
                       COUNT(*) as total_files
                FROM files
            """)
            row = cursor.fetchone()
            
            # Check for FTS5
            fts_cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files_fts'
            """)
            has_fts = fts_cursor.fetchone() is not None
            
            # Get datasets list
            datasets = self.list_datasets()
            
            return {
                "connected": True,
                "database_path": self.db_path,
                "dataset_count": row['dataset_count'],
                "total_files": row['total_files'],
                "fts5_enabled": has_fts,
                "datasets": datasets
            }
        except Exception as e:
            return {
                "connected": True,
                "error": str(e)
            }
    
    def clear_dataset(self, dataset_name: str) -> Dict[str, Any]:
        """Clear all data for a specific dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        try:
            # Check if dataset exists
            cursor = self.db.execute("""
                SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
            """, (dataset_name,))
            count = cursor.fetchone()['count']
            
            if count == 0:
                return {"success": False, "message": f"Dataset '{dataset_name}' not found"}
            
            # Delete files
            self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
            
            # Delete metadata
            self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
            
            self.db.commit()
            
            return {
                "success": True,
                "message": f"Cleared dataset '{dataset_name}'",
                "files_removed": count
            }
        except Exception as e:
            return {"success": False, "message": f"Error clearing dataset: {str(e)}"}
    
    def document_directory(self, dataset_name: str, directory: str, exclude_patterns: List[str] = None, batch_size: int = 20) -> Dict[str, Any]:
        """Generate orchestration instructions for documenting directory."""
        if exclude_patterns is None:
            exclude_patterns = []
        
        # Default exclusions
        default_excludes = [
            'node_modules/*', 'dist/*', 'build/*', '.git/*', '*.pyc', '__pycache__/*',
            'venv/*', '.env', '*.log', '*.tmp', '.DS_Store', 'coverage/*', '.pytest_cache/*'
        ]
        exclude_patterns.extend(default_excludes)
        
        # Find all code files
        code_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.cpp', '.c', '.h', 
                          '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.jl']
        
        all_files = []
        for ext in code_extensions:
            pattern = os.path.join(directory, f"**/*{ext}")
            files = glob.glob(pattern, recursive=True)
            
            # Filter out excluded patterns
            filtered_files = []
            for file in files:
                rel_path = os.path.relpath(file, directory)
                if not any(fnmatch.fnmatch(rel_path, pattern) for pattern in exclude_patterns):
                    filtered_files.append(file)
            
            all_files.extend(filtered_files)
        
        if not all_files:
            return {
                "success": False,
                "message": f"No code files found in {directory}"
            }
        
        # Create batches
        batches = [all_files[i:i+batch_size] for i in range(0, len(all_files), batch_size)]
        
        return {
            "success": True,
            "dataset_name": dataset_name,
            "directory": directory,
            "total_files": len(all_files),
            "batch_count": len(batches),
            "batch_size": batch_size,
            "orchestration_prompt": f"""
Please help document the codebase for the '{dataset_name}' dataset. 
I'll need you to analyze {len(all_files)} files in {len(batches)} batches.

For each batch, please:
1. Read and analyze each file
2. Extract key information (functions, imports, exports, etc.)
3. Use the insert_file_documentation tool to save the analysis

Would you like me to provide the file batches for you to process?
""",
            "batches": batches
        }
    
    def insert_file_documentation(self, dataset_name: str, filepath: str, filename: str, 
                                 overview: str, functions: Dict = None, exports: Dict = None,
                                 imports: Dict = None, types_interfaces_classes: Dict = None,
                                 constants: Dict = None, ddd_context: str = "",
                                 dependencies: List = None, other_notes: List = None) -> Dict[str, Any]:
        """Insert file documentation into dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        try:
            self.db.execute("""
                INSERT OR REPLACE INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dataset_name,
                filepath,
                filename,
                overview,
                ddd_context,
                json.dumps(functions or {}),
                json.dumps(exports or {}),
                json.dumps(imports or {}),
                json.dumps(types_interfaces_classes or {}),
                json.dumps(constants or {}),
                json.dumps(dependencies or []),
                json.dumps(other_notes or [])
            ))
            
            # Update dataset metadata file count
            self.db.execute("""
                UPDATE dataset_metadata 
                SET files_count = (
                    SELECT COUNT(*) FROM files WHERE dataset_id = ?
                )
                WHERE dataset_id = ?
            """, (dataset_name, dataset_name))
            
            # Create metadata entry if it doesn't exist
            self.db.execute("""
                INSERT OR IGNORE INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, 1, ?)
            """, (dataset_name, os.path.dirname(filepath), datetime.now()))
            
            self.db.commit()
            
            return {
                "success": True,
                "message": f"Documentation saved for {filename}",
                "dataset": dataset_name,
                "filepath": filepath
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error saving documentation: {str(e)}"
            }
    
    def update_file_documentation(self, dataset_name: str, filepath: str, **kwargs) -> Dict[str, Any]:
        """Update existing file documentation with only provided fields."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Check if file exists
        cursor = self.db.execute("""
            SELECT * FROM files WHERE dataset_id = ? AND filepath = ?
        """, (dataset_name, filepath))
        
        existing = cursor.fetchone()
        if not existing:
            return {
                "success": False,
                "message": f"File '{filepath}' not found in dataset '{dataset_name}'"
            }
        
        # Build update query dynamically
        update_fields = []
        update_values = []
        
        field_mapping = {
            'filename': 'filename',
            'overview': 'overview',
            'ddd_context': 'ddd_context',
            'functions': 'functions',
            'exports': 'exports', 
            'imports': 'imports',
            'types_interfaces_classes': 'types_interfaces_classes',
            'constants': 'constants',
            'dependencies': 'dependencies',
            'other_notes': 'other_notes'
        }
        
        for key, db_field in field_mapping.items():
            if key in kwargs and kwargs[key] is not None:
                update_fields.append(f"{db_field} = ?")
                # JSON serialize dict/list fields
                if key in ['functions', 'exports', 'imports', 'types_interfaces_classes', 
                          'constants', 'dependencies', 'other_notes']:
                    update_values.append(json.dumps(kwargs[key]))
                else:
                    update_values.append(kwargs[key])
        
        if not update_fields:
            return {
                "success": False,
                "message": "No fields to update"
            }
        
        # Add WHERE clause values
        update_values.extend([dataset_name, filepath])
        
        try:
            query = f"""
                UPDATE files 
                SET {', '.join(update_fields)}
                WHERE dataset_id = ? AND filepath = ?
            """
            self.db.execute(query, update_values)
            self.db.commit()
            
            return {
                "success": True,
                "message": f"Updated documentation for {filepath}",
                "dataset": dataset_name,
                "updated_fields": list(kwargs.keys())
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error updating documentation: {str(e)}"
            }
    
    def get_project_config(self) -> Dict[str, Any]:
        """Get comprehensive project configuration and status."""
        try:
            config_path = os.path.join(self.cwd, ".code-query", "config.json")
            config_exists = os.path.exists(config_path)
            config_data = None
            
            if config_exists:
                try:
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)
                except Exception as e:
                    logging.warning(f"Could not read config file: {e}")
            
            # Check git status
            actual_git_dir = self._get_actual_git_dir()
            git_exists = actual_git_dir is not None
            
            # Check git hooks
            pre_commit_exists = False
            post_merge_exists = False
            if git_exists:
                hooks_dir = os.path.join(actual_git_dir, "hooks")
                pre_commit_exists = os.path.exists(os.path.join(hooks_dir, "pre-commit"))
                post_merge_exists = os.path.exists(os.path.join(hooks_dir, "post-merge"))
            
            # Get database status
            db_status = self.get_status()
            
            # Build comprehensive config
            return {
                "success": True,
                "project_root": self.cwd,
                "config_file": {
                    "exists": config_exists,
                    "path": config_path if config_exists else None,
                    "content": config_data
                },
                "git": {
                    "is_repository": git_exists,
                    "git_dir": actual_git_dir,
                    "hooks": {
                        "pre_commit": pre_commit_exists,
                        "post_merge": post_merge_exists
                    }
                },
                "database": db_status,
                "setup_complete": config_exists and (db_status.get('dataset_count', 0) > 0)
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error getting project config: {str(e)}"
            }
    
    def create_project_config(self, dataset_name: str, exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """Create or update project configuration file."""
        try:
            config_dir = os.path.join(self.cwd, ".code-query")
            os.makedirs(config_dir, exist_ok=True)
            
            config_path = os.path.join(config_dir, "config.json")
            
            # Default exclude patterns if not provided
            if exclude_patterns is None:
                exclude_patterns = [
                    "node_modules/*",
                    "dist/*",
                    "build/*",
                    ".git/*",
                    "*.pyc",
                    "__pycache__/*",
                    "venv/*",
                    ".env",
                    "*.log",
                    "*.tmp",
                    ".DS_Store",
                    "coverage/*",
                    ".pytest_cache/*"
                ]
            
            config_data = {
                "mainDatasetName": dataset_name,
                "excludePatterns": exclude_patterns,
                "createdAt": datetime.now().isoformat(),
                "version": "1.1.0"
            }
            
            # Write config file
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            return {
                "success": True,
                "message": f"Created project configuration for dataset '{dataset_name}'",
                "config_path": config_path,
                "config": config_data
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error creating project config: {str(e)}"
            }
    
    def fork_dataset(self, source_dataset: str, target_dataset: str) -> Dict[str, Any]:
        """Fork (copy) a dataset to a new name."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        try:
            # Check if source exists
            cursor = self.db.execute("""
                SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
            """, (source_dataset,))
            source_count = cursor.fetchone()['count']
            
            if source_count == 0:
                return {
                    "success": False,
                    "message": f"Source dataset '{source_dataset}' not found"
                }
            
            # Check if target already exists
            cursor = self.db.execute("""
                SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
            """, (target_dataset,))
            target_count = cursor.fetchone()['count']
            
            if target_count > 0:
                return {
                    "success": False,
                    "message": f"Target dataset '{target_dataset}' already exists with {target_count} files"
                }
            
            # Get source metadata
            cursor = self.db.execute("""
                SELECT * FROM dataset_metadata WHERE dataset_id = ?
            """, (source_dataset,))
            source_metadata = cursor.fetchone()
            
            # Copy all files
            self.db.execute("""
                INSERT INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes
                )
                SELECT 
                    ?, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes
                FROM files
                WHERE dataset_id = ?
            """, (target_dataset, source_dataset))
            
            files_copied = self.db.total_changes
            
            # Detect if this is a worktree dataset by naming convention
            is_worktree_dataset = "__wt_" in target_dataset
            
            # Get current branch if this is a worktree fork
            source_branch = None
            if is_worktree_dataset:
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=self.cwd,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=5
                    )
                    source_branch = result.stdout.strip()
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    pass
            
            # Create metadata entry for target dataset
            self.db.execute("""
                INSERT INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at, parent_dataset_id, source_branch)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                target_dataset,
                f"{source_metadata['source_dir']} (forked from {source_dataset})",
                files_copied,
                datetime.now(),
                source_dataset if is_worktree_dataset else None,
                source_branch
            ))
            
            self.db.commit()
            
            return {
                "success": True,
                "message": f"Successfully forked dataset '{source_dataset}' to '{target_dataset}'",
                "files_copied": files_copied,
                "source_dataset": source_dataset,
                "target_dataset": target_dataset
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error forking dataset: {str(e)}"
            }
    
    def install_pre_commit_hook(self, dataset_name: str, mode: str = "queue") -> Dict[str, Any]:
        """Install pre-commit hook for automatic documentation updates."""
        try:
            # Check if jq is installed
            try:
                subprocess.run(["jq", "--version"], capture_output=True, check=True, timeout=5)
            except (FileNotFoundError, subprocess.CalledProcessError):
                return {
                    "success": False,
                    "message": "The 'jq' command-line JSON processor is required but not installed.",
                    "install_instructions": {
                        "macOS": "brew install jq",
                        "Ubuntu/Debian": "sudo apt-get install jq",
                        "RHEL/CentOS": "sudo yum install jq",
                        "Windows": "winget install stedolan.jq",
                        "manual": "Visit https://stedolan.github.io/jq/download/"
                    },
                    "next_steps": [
                        "Install jq using one of the commands above",
                        "Then re-run this command to install the pre-commit hook"
                    ]
                }
            
            # Check if we're in a git repository
            actual_git_dir = self._get_actual_git_dir()
            if not actual_git_dir:
                return {
                    "success": False,
                    "message": "Not in a git repository. Please initialize git first with 'git init'."
                }
            
            # Check if configuration exists
            config_path = os.path.join(self.cwd, ".code-query", "config.json")
            if not os.path.exists(config_path):
                return {
                    "success": False,
                    "message": "No .code-query/config.json found. Please run create_project_config first."
                }
            
            # Get the install script path
            scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
            install_script = os.path.join(scripts_dir, "install-pre-commit-hook.sh")
            
            if not os.path.exists(install_script):
                return {
                    "success": False,
                    "message": f"Installation script not found at {install_script}"
                }
            
            # Run the install script
            try:
                result = subprocess.run(
                    ["bash", install_script, dataset_name],
                    cwd=self.cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30
                )
                
                return {
                    "success": True,
                    "message": f"Successfully installed pre-commit hook for dataset '{dataset_name}'",
                    "details": result.stdout,
                    "hook_path": os.path.join(actual_git_dir, "hooks", "pre-commit"),
                    "next_steps": [
                        "The pre-commit hook will now queue changed files for documentation updates",
                        "Use 'git doc-update' to process the queue and update documentation"
                    ]
                }
                
            except subprocess.CalledProcessError as e:
                return {
                    "success": False,
                    "message": f"Failed to install pre-commit hook: {e.stderr}"
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "message": "Installation script timed out after 30 seconds"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Error installing pre-commit hook: {str(e)}"
            }
    
    def install_post_merge_hook(self, main_dataset: str = None) -> Dict[str, Any]:
        """Install post-merge hook for syncing worktree changes back to main dataset."""
        try:
            # Check if we're in a git repository
            actual_git_dir = self._get_actual_git_dir()
            if not actual_git_dir:
                return {
                    "success": False,
                    "message": "Not in a git repository. Please initialize git first with 'git init'."
                }
            
            # Get main dataset from config if not provided
            if not main_dataset:
                config_path = os.path.join(self.cwd, ".code-query", "config.json")
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r') as f:
                            config_data = json.load(f)
                            main_dataset = config_data.get("datasetName")
                    except Exception:
                        pass
                
                if not main_dataset:
                    return {
                        "success": False,
                        "message": "No main dataset specified and couldn't find one in config."
                    }
            
            # Create post-merge hook script
            post_merge_hook = f"""#!/bin/bash
# Code Query MCP Post-merge Hook
# This hook syncs documentation from worktree datasets back to main

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "⚠️  Code Query: 'jq' is required but not installed."
    echo "   Please install jq to enable automatic documentation syncing."
    exit 0
fi

# Get the main branch name
MAIN_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main")

# Get current dataset from config
CONFIG_FILE=".code-query/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    exit 0
fi

CURRENT_DATASET=$(jq -r '.datasetName // empty' "$CONFIG_FILE" 2>/dev/null)
if [ -z "$CURRENT_DATASET" ]; then
    exit 0
fi

# Main dataset for this repository
MAIN_DATASET="{main_dataset}"

# Skip if we're already on the main dataset
if [ "$CURRENT_DATASET" = "$MAIN_DATASET" ]; then
    exit 0
fi

# Check if we just merged from the main branch
MERGED_FROM=$(git reflog -1 | grep -o "merge [^:]*" | cut -d' ' -f2)
if [ -n "$MERGED_FROM" ] && [[ "$MERGED_FROM" == *"$MAIN_BRANCH"* ]]; then
    echo "📄 Code Query: Detected merge from main branch ($MAIN_BRANCH)"
    echo "   Syncing documentation from worktree dataset '$CURRENT_DATASET' to main dataset '$MAIN_DATASET'"
    
    # Get list of changed files in the merge
    CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD)
    
    if [ -n "$CHANGED_FILES" ]; then
        # Build a JSON array of files to prevent prompt injection
        FILE_LIST_JSON=$(echo "$CHANGED_FILES" | jq -R . | jq -s .)

        if [ -z "$FILE_LIST_JSON" ] || [ "$FILE_LIST_JSON" = "[]" ]; then
            echo "   No valid files to sync."
            exit 0
        fi

        echo "   Files to sync: $FILE_LIST_JSON"
        echo ""
        
        # Use Claude to sync the files
        claude --print "Use code-query MCP to copy documentation for files in the JSON array $FILE_LIST_JSON from dataset '$CURRENT_DATASET' to dataset '$MAIN_DATASET'"
    fi
fi

exit 0
"""
            
            # Write post-merge hook
            hooks_dir = os.path.join(actual_git_dir, "hooks")
            os.makedirs(hooks_dir, exist_ok=True)  # Ensure hooks directory exists
            hook_path = os.path.join(hooks_dir, "post-merge")
            
            # Check if hook already exists
            if os.path.exists(hook_path):
                with open(hook_path, 'r') as f:
                    existing_content = f.read()
                    if "Code Query MCP Post-merge Hook" not in existing_content:
                        return {
                            "success": False,
                            "message": "A post-merge hook already exists. Please manually integrate or remove it first."
                        }
            
            # Write the hook
            with open(hook_path, 'w') as f:
                f.write(post_merge_hook)
            
            # Make hook executable
            os.chmod(hook_path, 0o755)
            
            return {
                "success": True,
                "message": f"Successfully installed post-merge hook for main dataset '{main_dataset}'",
                "details": {
                    "hook_path": hook_path,
                    "main_dataset": main_dataset
                },
                "next_steps": [
                    "The post-merge hook will sync changes from worktree datasets back to main",
                    "This happens automatically when merging from main/master branches"
                ]
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error installing post-merge hook: {str(e)}"
            }
    
    def sync_dataset(self, source_dataset: str, target_dataset: str, source_ref: str, target_ref: str) -> Dict[str, Any]:
        """Syncs file records between datasets based on git diff."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        try:
            # 1. Get changed files using git diff
            # Use target_ref...source_ref to find changes introduced by source
            diff_command = ["git", "diff", "--name-only", f"{target_ref}...{source_ref}"]
            result = subprocess.run(diff_command, capture_output=True, text=True, check=True, cwd=self.cwd)
            changed_files = result.stdout.strip().split('\n')
            
            if not any(changed_files):
                return {"success": True, "message": "No changes to sync"}
            
            # 2. Sync in transaction for atomicity
            synced_count = 0
            with self.db:  # Transaction context
                for filepath in changed_files:
                    if not filepath: 
                        continue
                        
                    # 3. Fetch record from source dataset
                    cursor = self.db.execute(
                        "SELECT * FROM files WHERE dataset_id = ? AND filepath = ?",
                        (source_dataset, filepath)
                    )
                    source_record = cursor.fetchone()
                    
                    if source_record:
                        # 4. Insert or replace in target dataset
                        columns = [key for key in source_record.keys() if key != 'dataset_id']
                        placeholders = ', '.join(['?'] * (len(columns) + 1))
                        values = [target_dataset] + [source_record[col] for col in columns]
                        
                        self.db.execute(f"""
                            INSERT OR REPLACE INTO files (dataset_id, {', '.join(columns)})
                            VALUES ({placeholders})
                        """, tuple(values))
                        synced_count += 1
            
            return {
                "success": True,
                "message": f"Synced {synced_count} files from '{source_dataset}' to '{target_dataset}'",
                "files_checked": len(changed_files),
                "files_synced": synced_count
            }
            
        except subprocess.CalledProcessError as e:
            return {"success": False, "message": f"Git diff failed: {e.stderr}"}
        except Exception as e:
            return {"success": False, "message": f"Sync failed: {str(e)}"}
    
    def cleanup_datasets(self, dry_run: bool = True) -> Dict[str, Any]:
        """Find and remove orphaned datasets."""
        try:
            # 1. Get all active git branches (local and remote)
            branches_raw = subprocess.check_output(
                ["git", "branch", "-a"], 
                text=True, 
                cwd=self.cwd
            ).strip()
            
            # Parse and sanitize branch names
            active_branches = set()
            for line in branches_raw.split('\n'):
                branch = line.strip().replace('* ', '')
                if '->' in branch:  # Skip symbolic refs
                    continue
                if branch.startswith('remotes/origin/'):
                    branch = branch[len('remotes/origin/'):]
                # Sanitize branch name same way as dataset naming
                sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', branch)
                active_branches.add(sanitized)
            
            # 2. Find worktree datasets (by naming pattern or metadata)
            # First try new metadata approach
            cursor = self.db.execute("""
                SELECT dataset_id, source_branch 
                FROM dataset_metadata 
                WHERE source_branch IS NOT NULL
            """)
            metadata_datasets = cursor.fetchall()
            
            # Also check naming convention for backward compatibility
            cursor = self.db.execute("""
                SELECT dataset_id 
                FROM dataset_metadata 
                WHERE dataset_id LIKE '%__wt_%'
            """)
            pattern_datasets = cursor.fetchall()
            
            # 3. Identify orphans
            orphans = []
            
            # Check metadata-based datasets
            for row in metadata_datasets:
                dataset_id = row['dataset_id']
                source_branch = row['source_branch']
                sanitized_branch = re.sub(r'[^a-zA-Z0-9_]', '_', source_branch)
                if sanitized_branch not in active_branches:
                    orphans.append({
                        'dataset_id': dataset_id,
                        'source_branch': source_branch,
                        'detection_method': 'metadata'
                    })
            
            # Check pattern-based datasets
            for row in pattern_datasets:
                dataset_id = row['dataset_id']
                # Extract branch from naming pattern
                match = re.search(r'__wt_(.+)$', dataset_id)
                if match:
                    branch_part = match.group(1)
                    if branch_part not in active_branches:
                        # Avoid duplicates
                        if not any(o['dataset_id'] == dataset_id for o in orphans):
                            orphans.append({
                                'dataset_id': dataset_id,
                                'inferred_branch': branch_part,
                                'detection_method': 'pattern'
                            })
            
            if not orphans:
                return {
                    "success": True,
                    "message": "No orphaned datasets found",
                    "orphans": []
                }
            
            if dry_run:
                return {
                    "success": True,
                    "message": f"Found {len(orphans)} orphaned datasets (dry run)",
                    "orphans": orphans,
                    "recommendation": "Run 'git fetch --prune' first to update remote branch info"
                }
            
            # 4. Delete orphans
            deleted_count = 0
            errors = []
            
            with self.db:  # Transaction
                for orphan in orphans:
                    dataset_id = orphan['dataset_id']
                    try:
                        # Delete from files table
                        self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_id,))
                        # Delete from metadata
                        self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_id,))
                        deleted_count += 1
                    except Exception as e:
                        errors.append({
                            'dataset_id': dataset_id,
                            'error': str(e)
                        })
            
            if errors:
                return {
                    "success": False,
                    "message": f"Deleted {deleted_count} of {len(orphans)} datasets",
                    "errors": errors
                }
            
            return {
                "success": True,
                "message": f"Successfully deleted {deleted_count} orphaned datasets",
                "deleted": orphans
            }
            
        except subprocess.CalledProcessError as e:
            return {
                "success": False,
                "message": f"Git command failed: {e.stderr}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Cleanup failed: {str(e)}"
            }
    
    def recommend_setup(self, project_name: str = None, source_directory: str = None) -> Dict[str, Any]:
        """Recommend complete setup process for a new project."""
        try:
            # Check current state
            config_exists = os.path.exists(os.path.join(self.cwd, ".code-query", "config.json"))
            actual_git_dir = self._get_actual_git_dir()
            git_exists = actual_git_dir is not None
            
            # Check if any datasets exist
            existing_datasets = self.list_datasets()
            has_datasets = len(existing_datasets) > 0
            
            # Try to determine the dataset name from existing configuration
            dataset_name_to_use = None
            config_data = None
            
            # First priority: check config file for dataset name
            if config_exists:
                try:
                    with open(os.path.join(self.cwd, ".code-query", "config.json"), 'r') as f:
                        config_data = json.load(f)
                        if config_data.get("datasetName"):
                            dataset_name_to_use = config_data["datasetName"]
                except Exception:
                    pass
            
            # Second priority: if we have existing datasets and no config, use the first one
            if not dataset_name_to_use and has_datasets and len(existing_datasets) > 0:
                dataset_name_to_use = existing_datasets[0]["name"]
            
            # Generate project name suggestion if not provided
            if not project_name:
                # Try to get from git remote or directory name
                project_name = os.path.basename(self.cwd)
                if git_exists:
                    try:
                        import subprocess
                        remote_url = subprocess.check_output(
                            ["git", "config", "--get", "remote.origin.url"],
                            cwd=self.cwd, text=True
                        ).strip()
                        if remote_url:
                            # Extract repo name from URL
                            repo_name = remote_url.split("/")[-1].replace(".git", "")
                            if repo_name:
                                project_name = repo_name
                    except:
                        pass
            
            # Use discovered dataset name or fall back to project name
            final_dataset_name = dataset_name_to_use or project_name
            
            # Default source directory
            if not source_directory:
                # Check common patterns
                for common_dir in ["src", "lib", "app", "."]:
                    if os.path.exists(os.path.join(self.cwd, common_dir)):
                        source_directory = common_dir
                        break
                else:
                    source_directory = "."
            
            # Build recommendations
            setup_steps = []
            recommended_commands = []
            
            # Step 1: Document or import data
            if not has_datasets:
                setup_steps.append({
                    "step": 1,
                    "action": "Document your codebase",
                    "reason": "No datasets found. Need to analyze and document your code.",
                    "command": f"document_directory('{project_name}', '{source_directory}')"
                })
                recommended_commands.append(
                    f"Use code-query MCP to document directory '{source_directory}' as '{project_name}'"
                )
            else:
                setup_steps.append({
                    "step": 1,
                    "action": "Use existing dataset",
                    "reason": f"Found {len(existing_datasets)} existing dataset(s)",
                    "datasets": existing_datasets,
                    "selected_dataset": dataset_name_to_use
                })
            
            # Step 2: Create configuration
            if not config_exists:
                setup_steps.append({
                    "step": 2,
                    "action": "Create project configuration",
                    "reason": "No .code-query/config.json found",
                    "command": f"create_project_config('{final_dataset_name}')"
                })
                recommended_commands.append(
                    f"Use code-query MCP to create project config for '{final_dataset_name}'"
                )
            
            # Step 3: Install git hooks
            if git_exists:
                hooks_dir = os.path.join(actual_git_dir, "hooks")
                pre_commit_exists = os.path.exists(os.path.join(hooks_dir, "pre-commit"))
                post_merge_exists = os.path.exists(os.path.join(hooks_dir, "post-merge"))
                
                if not pre_commit_exists:
                    setup_steps.append({
                        "step": 3,
                        "action": "Install pre-commit hook",
                        "reason": "Automatically queue changed files for documentation updates",
                        "command": f"install_pre_commit_hook('{final_dataset_name}')"
                    })
                    recommended_commands.append(
                        f"Use code-query MCP to install pre-commit hook for '{final_dataset_name}'"
                    )
                
                if not post_merge_exists:
                    setup_steps.append({
                        "step": 4,
                        "action": "Install post-merge hook",
                        "reason": "Sync documentation from git worktrees back to main",
                        "command": f"install_post_merge_hook('{final_dataset_name}')"
                    })
                    recommended_commands.append(
                        f"Use code-query MCP to install post-merge hook for '{final_dataset_name}'"
                    )
            
            # Build response
            response = {
                "success": True,
                "project_name": project_name,
                "dataset_name": final_dataset_name,
                "source_directory": source_directory,
                "current_state": {
                    "config_exists": config_exists,
                    "git_repository": git_exists,
                    "has_datasets": has_datasets,
                    "dataset_count": len(existing_datasets),
                    "existing_datasets": existing_datasets if has_datasets else [],
                    "config_dataset_name": config_data.get("datasetName") if config_data else None
                },
                "setup_needed": len(setup_steps) > 0,
                "setup_steps": setup_steps
            }
            
            if recommended_commands:
                # Separate optional git hook commands from required commands
                required_commands = [cmd for cmd in recommended_commands if "git hook" not in cmd.lower()]
                optional_commands = [cmd for cmd in recommended_commands if "git hook" in cmd.lower()]
                
                if required_commands and optional_commands:
                    response["recommendation"] = (
                        f"To complete the Code Query MCP setup for '{final_dataset_name}', "
                        f"here are the recommended steps:\n\n" +
                        "**Required:**\n" +
                        "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(required_commands)) +
                        "\n\n**Optional (Git Hooks):**\n" +
                        "\n".join(f"{len(required_commands)+i+1}. {cmd}" for i, cmd in enumerate(optional_commands)) +
                        "\n\nWould you like me to run these commands? You can choose to run all of them, "
                        "just the required ones, or handle them individually."
                    )
                elif optional_commands and not required_commands:
                    # Include info about existing dataset if config-based
                    dataset_info = ""
                    if dataset_name_to_use and config_data:
                        dataset_info = f"\n\n💡 Using existing dataset '{dataset_name_to_use}' from your project configuration."
                    
                    response["recommendation"] = (
                        f"Your Code Query MCP setup for '{final_dataset_name}' is mostly complete! "
                        f"The only missing components are optional git hooks:\n\n" +
                        "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(optional_commands)) +
                        "\n\nThese git hooks are optional but recommended for automatic documentation updates. "
                        "Would you like me to install them?" +
                        dataset_info
                    )
                else:
                    # Include info about existing dataset if config-based
                    dataset_info = ""
                    if dataset_name_to_use and config_data:
                        dataset_info = f"\n\n💡 Using existing dataset '{dataset_name_to_use}' from your project configuration."
                    
                    response["recommendation"] = (
                        f"To complete the Code Query MCP setup for '{final_dataset_name}', "
                        f"I recommend running these {len(recommended_commands)} commands:\n\n" +
                        "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(recommended_commands)) +
                        "\n\nWould you like me to run these setup commands now?" +
                        dataset_info
                    )
                response["commands_to_run"] = recommended_commands
            else:
                response["recommendation"] = (
                    "Your project is already fully set up with Code Query MCP! "
                    "You can start using the search and documentation features."
                )
            
            return response
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error analyzing setup requirements: {str(e)}"
            }