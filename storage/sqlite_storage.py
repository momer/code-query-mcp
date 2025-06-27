"""SQLite storage functions and CodeQueryServer class for Code Query MCP Server."""

import os
import json
import sqlite3
import glob
import logging
import fnmatch
import subprocess
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from helpers.git_helper import get_actual_git_dir, get_current_commit, get_changed_files_since_commit
from storage.migrations import SchemaMigrator


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
            migrator = SchemaMigrator(self.db)
            migrator.migrate_to_current_version()
            # Recreate FTS if needed after migration
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files_fts'
            """)
            if not cursor.fetchone():
                self._create_fts_table()
            logging.info(f"Connected to existing database at {self.db_path}")
    
    def _get_actual_git_dir(self) -> Optional[str]:
        """Determines the actual .git directory path, handling worktrees."""
        return get_actual_git_dir(self.cwd)
    
    def _is_valid_dataset_name(self, dataset_name: str) -> bool:
        """Validates a dataset name against security and naming rules."""
        # Prevent path traversal
        if dataset_name in ('.', '..'):
            return False
        # Ensure it doesn't contain path separators or other dangerous chars
        if '/' in dataset_name or '\\' in dataset_name:
            return False
        # Only allow safe characters
        return bool(re.match(r'^[a-zA-Z0-9_.-]+$', dataset_name))
    
    def _prompt_for_model_selection(self) -> str:
        """Prompt user to select a model for code analysis."""
        print("\n=== Model Selection ===")
        print("Please select a model for code analysis:")
        print("1. Opus (latest)")
        print("2. Sonnet (latest)")
        print("3. Specify other model name")
        
        models = {
            "1": "opus",
            "2": "sonnet"
        }
        
        while True:
            try:
                choice = input("\nSelect option (1-3) [default: 2]: ").strip()
                if not choice:
                    choice = "2"
                
                if choice in models:
                    return models[choice]
                elif choice == "3":
                    custom_model = input("Enter model name: ").strip()
                    if custom_model:
                        return custom_model
                    else:
                        print("Please enter a valid model name.")
                else:
                    print("Please enter a valid option (1-3).")
            except (EOFError, KeyboardInterrupt):
                print("\nUsing default model: sonnet")
                return "sonnet"
    
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
                documented_at_commit TEXT,
                documented_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                full_content TEXT,
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
                loaded_at TIMESTAMP,
                dataset_type TEXT DEFAULT 'main',
                parent_dataset_id TEXT,
                source_branch TEXT,
                FOREIGN KEY(parent_dataset_id) REFERENCES dataset_metadata(dataset_id) ON DELETE SET NULL
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
                    full_content,
                    content='files',
                    content_rowid='rowid'
                )
            """)
            
            # Create triggers to keep FTS in sync
            self.db.execute("""
                CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes, constants, 
                        dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes, full_content)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes, old.full_content);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes, full_content)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes, old.full_content);
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes, 
                        constants, dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
            
            logging.info("Created FTS5 virtual table for full-text search")
        except sqlite3.OperationalError as e:
            logging.warning(f"Could not create FTS5 table: {e}")
        
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
                    full_content,
                    content='files',
                    content_rowid='rowid'
                )
            """)
            
            # Create triggers
            self.db.execute("""
                CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes, constants, 
                        dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes, full_content)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes, old.full_content);
                END
            """)
            
            self.db.execute("""
                CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
                    INSERT INTO files_fts(files_fts, rowid, dataset_id, filepath, filename, 
                        overview, ddd_context, functions, exports, imports, 
                        types_interfaces_classes, constants, dependencies, other_notes, full_content)
                    VALUES ('delete', old.rowid, old.dataset_id, old.filepath, old.filename, 
                        old.overview, old.ddd_context, old.functions, old.exports, 
                        old.imports, old.types_interfaces_classes, old.constants, 
                        old.dependencies, old.other_notes, old.full_content);
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes, 
                        constants, dependencies, other_notes, full_content)
                    VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview, 
                        new.ddd_context, new.functions, new.exports, new.imports, 
                        new.types_interfaces_classes, new.constants, new.dependencies, 
                        new.other_notes, new.full_content);
                END
            """)
            
        except sqlite3.OperationalError as e:
            logging.warning(f"Could not create FTS5 table: {e}")
        
    
    def import_data(self, dataset_name: str, directory: str, replace: bool = False) -> Dict[str, Any]:
        """Import JSON files from directory into named dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
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
                
                # Read full file content if filepath exists and is readable
                full_content = None
                filepath = data.get('filepath', '')
                if filepath and os.path.isfile(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='replace') as source_file:
                            full_content = source_file.read()
                    except Exception as read_error:
                        logging.warning(f"Could not read source file {filepath}: {read_error}")
                        full_content = f"[Error reading file: {read_error}]"
                
                # Insert into database
                self.db.execute("""
                    INSERT OR REPLACE INTO files (
                        dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes, full_content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dataset_name,
                    filepath,
                    data.get('filename', ''),
                    data.get('overview', ''),
                    data.get('ddd_context', ''),
                    json.dumps(data.get('functions', {})),
                    json.dumps(data.get('exports', {})),
                    json.dumps(data.get('imports', {})),
                    json.dumps(data.get('types_interfaces_classes', {})),
                    json.dumps(data.get('constants', {})),
                    json.dumps(data.get('dependencies', [])),
                    json.dumps(data.get('other_notes', [])),
                    full_content
                ))
                imported += 1
            except Exception as e:
                errors.append(f"{json_file}: {str(e)}")
        
        # Update dataset metadata
        self.db.execute("""
            INSERT OR REPLACE INTO dataset_metadata 
            (dataset_id, source_dir, files_count, loaded_at, dataset_type)
            VALUES (?, ?, ?, ?, ?)
        """, (dataset_name, directory, imported, datetime.now(), 'main'))
        
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
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return []  # Return empty list for invalid dataset names
        
        results = []
        
        # Check if FTS5 is available
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        
        if cursor.fetchone():
            # Use FTS5 for search
            # Sanitize query for FTS5 by escaping special characters
            import re
            # Remove potentially problematic characters and escape quotes
            fts_query = re.sub(r'[^\w\s".-]', ' ', query)
            fts_query = fts_query.replace('"', '""')  # Escape quotes
            fts_query = fts_query.strip()
            
            cursor = self.db.execute("""
                SELECT DISTINCT f.filepath, f.filename, f.overview, f.ddd_context,
                       snippet(files_fts, 2, '[MATCH]', '[/MATCH]', '...', 64) as match_snippet
                FROM files f
                JOIN files_fts ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ?
                AND f.dataset_id = ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, dataset_name, limit))
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
    
    def search_full_content(self, query: str, dataset_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search full file contents using FTS5 for comprehensive code search."""
        if not self.db:
            return []
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return []
        
        results = []
        
        # Check if FTS5 is available
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        
        if cursor.fetchone():
            # Use FTS5 for search with focus on full_content
            # Sanitize query for FTS5 by escaping special characters
            import re
            # Remove potentially problematic characters and escape quotes
            fts_query = re.sub(r'[^\w\s".-]', ' ', query)
            fts_query = fts_query.replace('"', '""')  # Escape quotes
            fts_query = fts_query.strip()
            
            cursor = self.db.execute("""
                SELECT f.filepath, f.filename, f.overview, f.ddd_context,
                       snippet(files_fts, 12, '[MATCH]', '[/MATCH]', '...', 128) as content_snippet,
                       rank
                FROM files f
                JOIN files_fts ON f.rowid = files_fts.rowid
                WHERE files_fts MATCH ('full_content:' || ?)
                AND f.dataset_id = ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, dataset_name, limit))
            
            for row in cursor:
                results.append({
                    "filepath": row["filepath"],
                    "filename": row["filename"],
                    "overview": row["overview"],
                    "ddd_context": row["ddd_context"],
                    "content_snippet": row["content_snippet"],
                    "search_type": "full_content",
                    "rank": row["rank"]
                })
        else:
            # Fallback to LIKE search on full_content
            like_query = f"%{query}%"
            cursor = self.db.execute("""
                SELECT filepath, filename, overview, ddd_context,
                       SUBSTR(full_content, 
                              CASE WHEN INSTR(LOWER(full_content), LOWER(?)) > 64 
                                   THEN INSTR(LOWER(full_content), LOWER(?)) - 64 
                                   ELSE 1 END, 
                              256) as content_snippet
                FROM files
                WHERE dataset_id = ? AND full_content LIKE ?
                LIMIT ?
            """, (query, query, dataset_name, like_query, limit))
            
            for row in cursor:
                results.append({
                    "filepath": row["filepath"],
                    "filename": row["filename"],
                    "overview": row["overview"],
                    "ddd_context": row["ddd_context"],
                    "content_snippet": row["content_snippet"],
                    "search_type": "full_content_fallback",
                    "warning": "FTS5 is not available; used slower fallback search."
                })
        
        return results
    
    def search(self, query: str, dataset_name: str, limit: int = 10) -> Dict[str, Any]:
        """
        Unified search that combines metadata search and full-content search results.
        Returns both types of results for comprehensive code discovery.
        """
        if not self.db:
            return {"metadata_results": [], "content_results": [], "total_results": 0}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {"error": "Invalid dataset name", "metadata_results": [], "content_results": [], "total_results": 0}
        
        # Get metadata search results
        metadata_results = self.search_files(query, dataset_name, limit)
        
        # Get full-content search results
        content_results = self.search_full_content(query, dataset_name, limit)
        
        # Combine and deduplicate results by filepath
        seen_files = set()
        combined_metadata = []
        combined_content = []
        
        # Process metadata results
        for result in metadata_results:
            filepath = result["filepath"]
            if filepath not in seen_files:
                seen_files.add(filepath)
                combined_metadata.append(result)
        
        # Process content results, avoiding duplicates
        for result in content_results:
            filepath = result["filepath"]
            if filepath not in seen_files:
                seen_files.add(filepath)
                combined_content.append(result)
            else:
                # File already found in metadata search, add content snippet to existing result
                for meta_result in combined_metadata:
                    if meta_result["filepath"] == filepath:
                        meta_result["content_snippet"] = result.get("content_snippet", "")
                        meta_result["search_type"] = "both"
                        break
        
        total_results = len(combined_metadata) + len(combined_content)
        
        return {
            "query": query,
            "dataset_name": dataset_name,
            "metadata_results": combined_metadata,
            "content_results": combined_content,
            "total_results": total_results,
            "search_summary": {
                "metadata_matches": len(combined_metadata),
                "content_only_matches": len(combined_content),
                "total_unique_files": total_results
            }
        }
    
    def populate_spellfix_vocabulary(self, dataset_name: str):
        """Populate spellfix vocabulary from dataset for better search suggestions."""
        if not self.db:
            return
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
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
            MAX_FIELD_LENGTH = 100_000  # Limit field length to prevent DoS
            
            for row in cursor:
                # Extract words from each field
                for field in ['filepath', 'filename', 'overview', 'ddd_context']:
                    if row[field]:
                        # Truncate field to prevent DoS on large inputs
                        content = row[field][:MAX_FIELD_LENGTH]
                        # Simple word extraction (could be improved)
                        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', content)
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
        # Validate dataset name if provided
        if dataset_name and not self._is_valid_dataset_name(dataset_name):
            return {"success": False, "message": "Invalid dataset_name."}
        
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
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return None
        
        # If filepath doesn't contain wildcards, wrap with % for flexible matching
        if '%' not in filepath:
            # Try exact match first - exclude full_content to return only metadata
            cursor = self.db.execute("""
                SELECT filepath, filename, overview, ddd_context, functions, exports, imports, 
                       types_interfaces_classes, constants, dependencies, other_notes, 
                       documented_at_commit, documented_at
                FROM files 
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
            # Prevent overly broad searches that could cause performance issues
            if len(filepath) < 3:
                return None  # Query too broad for partial matching
            filepath = f'%{filepath}%'
        
        # Use LIKE query for partial matching - exclude full_content to return only metadata
        cursor = self.db.execute("""
            SELECT filepath, filename, overview, ddd_context, functions, exports, imports, 
                   types_interfaces_classes, constants, dependencies, other_notes, 
                   documented_at_commit, documented_at
            FROM files 
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
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
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
            
            # Check if we're in a worktree and get current dataset info
            from helpers.git_helper import get_worktree_info
            wt_info = get_worktree_info(self.cwd)
            current_dataset_info = None
            
            if wt_info and wt_info['is_worktree']:
                # Try to get the current dataset from config
                config_path = os.path.join(self.cwd, ".code-query", "config.json")
                if os.path.exists(config_path):
                    try:
                        with open(config_path, 'r') as f:
                            config_data = json.load(f)
                            dataset_name = config_data.get('mainDatasetName')
                            if dataset_name:
                                current_dataset_info = {
                                    "name": dataset_name,
                                    "type": "worktree",
                                    "branch": wt_info['branch'],
                                    "note": f"This is a git worktree using dataset '{dataset_name}' (isolated from main)"
                                }
                    except Exception:
                        pass
            
            status_data = {
                "connected": True,
                "database_path": self.db_path,
                "dataset_count": row['dataset_count'],
                "total_files": row['total_files'],
                "fts5_enabled": has_fts,
                "datasets": datasets
            }
            
            if current_dataset_info:
                status_data["current_dataset"] = current_dataset_info
            
            return status_data
        except Exception as e:
            return {
                "connected": True,
                "error": str(e)
            }
    
    def clear_dataset(self, dataset_name: str) -> Dict[str, Any]:
        """Clear all data for a specific dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
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
        
        # Find all code files - prefer git-tracked files when available
        code_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.cpp', '.c', '.h', 
                          '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.r', '.jl']
        
        all_files = []
        
        # Try to use git ls-files if we're in a git repository
        try:
            result = subprocess.run(
                ["git", "ls-files", "--", directory],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Filter git-tracked files by extension and exclusion patterns
            git_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
            for file_path in git_files:
                if not file_path:  # Skip empty lines
                    continue
                    
                # Check if it's a code file
                _, ext = os.path.splitext(file_path.lower())
                if ext in code_extensions:
                    # Apply exclusion patterns
                    if not any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns):
                        full_path = os.path.join(self.cwd, file_path)
                        if os.path.exists(full_path):  # Ensure file still exists
                            all_files.append(full_path)
                            
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to glob if git is not available or fails
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
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
        try:
            # Get current commit hash for tracking
            current_commit = get_current_commit(self.cwd)
            
            # Read full file content if filepath exists and is readable
            full_content = None
            if filepath and os.path.isfile(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as source_file:
                        full_content = source_file.read()
                except Exception as read_error:
                    logging.warning(f"Could not read source file {filepath}: {read_error}")
                    full_content = f"[Error reading file: {read_error}]"
            
            self.db.execute("""
                INSERT OR REPLACE INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, documented_at_commit,
                    documented_at, full_content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
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
                json.dumps(other_notes or []),
                current_commit,
                full_content
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
                (dataset_id, source_dir, files_count, loaded_at, dataset_type)
                VALUES (?, ?, 1, ?, ?)
            """, (dataset_name, os.path.dirname(filepath), datetime.now(), 'main'))
            
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
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
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
    
    def create_project_config(self, dataset_name: str, exclude_patterns: List[str] = None, model: str = None) -> Dict[str, Any]:
        """Create or update project configuration file with automatic worktree handling."""
        try:
            # Validate dataset name first
            if not self._is_valid_dataset_name(dataset_name):
                return {
                    "success": False,
                    "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
                }
            
            config_dir = os.path.join(self.cwd, ".code-query")
            os.makedirs(config_dir, exist_ok=True)
            
            config_path = os.path.join(config_dir, "config.json")
            
            # Check if we're in a worktree
            from helpers.git_helper import get_worktree_info
            wt_info = get_worktree_info(self.cwd)
            
            actual_dataset_name = dataset_name
            auto_fork_info = None
            
            if wt_info and wt_info['is_worktree']:
                # We're in a worktree - need special handling
                main_path = wt_info['main_path']
                sanitized_branch = wt_info['sanitized_branch']
                
                # Try to find the main dataset from main worktree's config
                main_config_path = os.path.join(main_path, ".code-query", "config.json")
                main_dataset = None
                
                if os.path.exists(main_config_path):
                    try:
                        with open(main_config_path, 'r') as f:
                            main_config = json.load(f)
                            main_dataset = main_config.get('mainDatasetName')
                    except Exception:
                        pass
                
                if not main_dataset:
                    # Use the provided name as base
                    main_dataset = dataset_name
                
                # Create worktree-specific dataset name with new convention
                wt_dataset_name = f"{main_dataset}_{sanitized_branch}"
                
                # Check if we need to fork
                cursor = self.db.execute("""
                    SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
                """, (wt_dataset_name,))
                wt_exists = cursor.fetchone()['count'] > 0
                
                if not wt_exists:
                    # Check if main dataset exists to fork from
                    cursor = self.db.execute("""
                        SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
                    """, (main_dataset,))
                    main_exists = cursor.fetchone()['count'] > 0
                    
                    if main_exists:
                        # Fork the main dataset
                        fork_result = self.fork_dataset(main_dataset, wt_dataset_name)
                        if fork_result['success']:
                            auto_fork_info = {
                                "forked": True,
                                "from": main_dataset,
                                "to": wt_dataset_name,
                                "files": fork_result.get('files_copied', 0)
                            }
                
                actual_dataset_name = wt_dataset_name
            
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
            
            # Model selection - default to sonnet if not provided (no interactive prompt in MCP context)
            selected_model = model or "sonnet"
            
            config_data = {
                "mainDatasetName": actual_dataset_name,
                "excludePatterns": exclude_patterns,
                "model": selected_model,
                "createdAt": datetime.now().isoformat(),
                "version": "1.1.0"
            }
            
            # Add worktree info to config if applicable
            if wt_info and wt_info['is_worktree']:
                config_data['worktreeInfo'] = {
                    'branch': wt_info['branch'],
                    'mainDatasetName': main_dataset,
                    'isWorktree': True,
                    'datasetNote': f"This worktree uses dataset '{actual_dataset_name}' which is isolated from the main dataset"
                }
            
            # Write config file
            with open(config_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            # Build response with clear messaging about what happened
            if wt_info and wt_info['is_worktree']:
                if auto_fork_info:
                    main_message = f"✅ Git worktree detected! Created isolated dataset '{actual_dataset_name}' for branch '{wt_info['branch']}' by copying {auto_fork_info['files']} files from main dataset '{auto_fork_info['from']}'."
                else:
                    main_message = f"✅ Git worktree detected! Created configuration for isolated dataset '{actual_dataset_name}' for branch '{wt_info['branch']}'."
            else:
                main_message = f"Created project configuration for dataset '{actual_dataset_name}'"
                if auto_fork_info:
                    main_message += f" (copied {auto_fork_info['files']} files from '{auto_fork_info['from']}')"
            
            response = {
                "success": True,
                "message": main_message,
                "config_path": config_path,
                "config": config_data
            }
            
            # Add clear worktree information to response
            if wt_info and wt_info['is_worktree']:
                response["worktree_dataset_info"] = {
                    "note": "This is a git worktree - data will be stored in a separate dataset",
                    "worktree_dataset": actual_dataset_name,
                    "main_dataset": main_dataset,
                    "branch": wt_info['branch'],
                    "data_isolation": "All operations in this worktree will use the worktree-specific dataset",
                    "important": f"IMPORTANT: Your data was {'copied from' if auto_fork_info else 'will be isolated from'} the main dataset. Changes in this worktree will not affect the main dataset."
                }
            
            if auto_fork_info:
                response["auto_fork"] = auto_fork_info
            
            return response
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error creating project config: {str(e)}"
            }
    
    def fork_dataset(self, source_dataset: str, target_dataset: str) -> Dict[str, Any]:
        """Fork (copy) a dataset to a new name."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset names
        if not self._is_valid_dataset_name(source_dataset) or not self._is_valid_dataset_name(target_dataset):
            return {
                "success": False,
                "message": "Invalid source or target dataset_name. They cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
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
            cursor = self.db.execute("""
                INSERT INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, full_content
                )
                SELECT 
                    ?, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, full_content
                FROM files
                WHERE dataset_id = ?
            """, (target_dataset, source_dataset))
            
            files_copied = cursor.rowcount
            
            # Detect if this is a worktree dataset by checking if we're in a worktree
            from helpers.git_helper import is_worktree
            is_worktree_dataset = is_worktree(self.cwd)
            
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
                (dataset_id, source_dir, files_count, loaded_at, dataset_type, parent_dataset_id, source_branch)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                target_dataset,
                f"{source_metadata['source_dir']} (forked from {source_dataset})",
                files_copied,
                datetime.now(),
                'worktree' if is_worktree_dataset else 'main',
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
            
            # Validate dataset_name to prevent shell injection and path traversal
            if not self._is_valid_dataset_name(dataset_name):
                return {
                    "success": False,
                    "message": "Invalid dataset_name. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
                }
            
            # Create pre-commit hook content directly (embedded script)
            # This script queues changed files for documentation updates
            hook_content = '''#!/bin/bash
# Code Query pre-commit hook - auto-generated
# This hook queues changed files for documentation updates
set -euo pipefail

# Get the working directory (git hooks run from repo root)
WORK_DIR=$(git rev-parse --show-toplevel)
cd "$WORK_DIR"

# Get the dataset name from config using absolute path
CONFIG_FILE="$WORK_DIR/.code-query/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "⚠️  Code Query: No config file found at $CONFIG_FILE. Skipping documentation queue."
    exit 0
fi

# Validate dataset name from config (prevent injection)
DATASET_NAME=$(jq -r '.mainDatasetName // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
if [ -z "$DATASET_NAME" ]; then
    echo "⚠️  Code Query: Dataset name not found in configuration."
    exit 0
fi

if ! [[ "$DATASET_NAME" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
    echo "⚠️  Code Query: Invalid dataset name in config: '$DATASET_NAME'. Skipping."
    exit 0
fi

# Queue changed files
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
if [ -z "$CHANGED_FILES" ]; then
    exit 0
fi

# Create queue file using absolute path
QUEUE_FILE="$WORK_DIR/.code-query/doc-queue.txt"
mkdir -p "$WORK_DIR/.code-query"

# Add files to queue (one per line, no duplicates)
echo "$CHANGED_FILES" | while read -r file; do
    if [ -n "$file" ] && ! grep -Fxq "$file" "$QUEUE_FILE" 2>/dev/null; then
        echo "$file" >> "$QUEUE_FILE"
    fi
done

FILE_COUNT=$(echo "$CHANGED_FILES" | wc -l)
echo "📝 Code Query: Queued $FILE_COUNT file(s) for documentation update."
echo "   Run 'code-query document_directory' to process the queue."

exit 0
'''
            
            # Write hook file
            hooks_dir = os.path.join(actual_git_dir, "hooks")
            os.makedirs(hooks_dir, exist_ok=True)
            hook_path = os.path.join(hooks_dir, "pre-commit")
            
            # Check if hook already exists
            hook_exists = os.path.exists(hook_path)
            if hook_exists:
                # Read existing hook
                with open(hook_path, 'r') as f:
                    existing_content = f.read()
                
                if "Code Query pre-commit hook" in existing_content:
                    return {
                        "success": True,
                        "message": "Pre-commit hook already installed",
                        "hook_path": hook_path
                    }
                else:
                    # Backup existing hook
                    import shutil
                    backup_path = f"{hook_path}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    shutil.copy2(hook_path, backup_path)
                    
                    # Append to existing hook
                    with open(hook_path, 'a') as f:
                        f.write("\n\n# Code Query section\n")
                        f.write(hook_content.replace('#!/bin/bash\n', ''))  # Remove shebang for append
                    
                    message = f"Appended to existing pre-commit hook (backup: {backup_path})"
            else:
                # Create new hook
                with open(hook_path, 'w') as f:
                    f.write(hook_content)
                message = f"Successfully installed pre-commit hook for dataset '{dataset_name}'"
            
            # Make executable
            os.chmod(hook_path, 0o755)
            
            return {
                "success": True,
                "message": message,
                "hook_path": hook_path,
                "next_steps": [
                    "The pre-commit hook will now queue changed files for documentation updates",
                    "Review queued files in .code-query/doc-queue.txt",
                    "Use code-query tools to process the queue and update documentation"
                ]
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
                            main_dataset = config_data.get("mainDatasetName")
                    except Exception:
                        pass
                
                if not main_dataset:
                    return {
                        "success": False,
                        "message": "No main dataset specified and couldn't find one in config."
                    }
            
            # Validate main_dataset to prevent shell injection and path traversal
            if not self._is_valid_dataset_name(main_dataset):
                return {
                    "success": False,
                    "message": "Invalid main_dataset. It cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
                }
            
            # Create post-merge hook script with improved security
            hook_content = '''#!/bin/bash
# Code Query post-merge hook - auto-generated
# This hook syncs documentation from worktree datasets back to main
set -euo pipefail

# Only run on successful merge (not during merge conflict)
if [ -f .git/MERGE_HEAD ]; then
    exit 0
fi

# Get the working directory (git hooks run from repo root)
WORK_DIR=$(git rev-parse --show-toplevel)
cd "$WORK_DIR"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "⚠️  Code Query: 'jq' is required but not installed."
    echo "   Please install jq to enable automatic documentation syncing."
    exit 0
fi

# Get current dataset from config using absolute path
CONFIG_FILE="$WORK_DIR/.code-query/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    exit 0
fi

# Read and validate dataset name from config to prevent injection
CURRENT_DATASET=$(jq -r '.mainDatasetName // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
if [ -z "$CURRENT_DATASET" ]; then
    echo "⚠️  Code Query: Dataset name not found in configuration."
    exit 0
fi

if ! [[ "$CURRENT_DATASET" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
    echo "⚠️  Code Query: Invalid dataset name in config: '$CURRENT_DATASET'. Skipping."
    exit 0
fi

# Check if this is a worktree dataset
# New naming convention: {main_dataset}_{branch_name}
# We need to determine if this is a worktree by checking git
if git rev-parse --git-common-dir >/dev/null 2>&1; then
    GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
    GIT_DIR=$(git rev-parse --git-dir)
    
    # If they're different, we're in a worktree
    if [ "$GIT_COMMON_DIR" != "$GIT_DIR" ]; then
        # Extract main dataset name by removing the branch suffix
        # Assuming pattern: mainDataset_branchName
        # We'll need to get the main dataset from the main worktree's config
        MAIN_WORKTREE_CONFIG="$GIT_COMMON_DIR/../.code-query/config.json"
        if [ -f "$MAIN_WORKTREE_CONFIG" ]; then
            MAIN_DATASET=$(jq -r '.mainDatasetName // empty' "$MAIN_WORKTREE_CONFIG" 2>/dev/null || echo "")
        else
            # Fallback: assume everything before the last underscore is the main dataset
            MAIN_DATASET="${CURRENT_DATASET%_*}"
        fi
        
        # Validate the extracted main dataset name
        if ! [[ "$MAIN_DATASET" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
            echo "⚠️  Code Query: Invalid main dataset name. Skipping."
            exit 0
        fi
        
        # Get merge base and head for sync
        MERGE_BASE=$(git merge-base HEAD ORIG_HEAD 2>/dev/null || echo "")
        if [ -z "$MERGE_BASE" ]; then
            exit 0
        fi
        
        echo "🔄 Code Query: Post-merge sync opportunity detected"
        echo "   From worktree dataset: $CURRENT_DATASET"
        echo "   To main dataset: $MAIN_DATASET"
        echo ""
        echo "   To sync changes, run:"
        echo "   code-query:sync_dataset source_dataset='$CURRENT_DATASET' target_dataset='$MAIN_DATASET' source_ref='HEAD' target_ref='$MERGE_BASE'"
    fi
    echo ""
    echo "   This will update the main dataset with changes from this worktree."
fi

exit 0
'''
            
            # Write post-merge hook
            hooks_dir = os.path.join(actual_git_dir, "hooks")
            os.makedirs(hooks_dir, exist_ok=True)  # Ensure hooks directory exists
            hook_path = os.path.join(hooks_dir, "post-merge")
            
            # Check if hook already exists
            hook_exists = os.path.exists(hook_path)
            if hook_exists:
                # Read existing hook
                with open(hook_path, 'r') as f:
                    existing_content = f.read()
                
                if "Code Query post-merge hook" in existing_content:
                    return {
                        "success": True,
                        "message": "Post-merge hook already installed",
                        "hook_path": hook_path
                    }
                else:
                    # Backup existing hook
                    import shutil
                    backup_path = f"{hook_path}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                    shutil.copy2(hook_path, backup_path)
                    
                    # Append to existing hook
                    with open(hook_path, 'a') as f:
                        f.write("\n\n# Code Query section\n")
                        f.write(hook_content.replace('#!/bin/bash\n', ''))  # Remove shebang for append
                    
                    message = f"Appended to existing post-merge hook (backup: {backup_path})"
            else:
                # Create new hook
                with open(hook_path, 'w') as f:
                    f.write(hook_content)
                message = f"Successfully installed post-merge hook"
            
            # Make hook executable
            os.chmod(hook_path, 0o755)
            
            return {
                "success": True,
                "message": message,
                "hook_path": hook_path,
                "next_steps": [
                    "The post-merge hook will detect when you merge in a worktree",
                    "It will suggest the sync_dataset command to run",
                    "This helps keep main dataset updated with worktree changes"
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
        
        # CRITICAL FIX: Add validation for git refs to prevent argument injection
        if source_ref.startswith('-') or target_ref.startswith('-'):
            return {"success": False, "message": "Invalid ref format. Refs cannot start with a dash."}
        
        # Ensure refs only contain safe characters for git
        ref_pattern = re.compile(r"^[a-zA-Z0-9_./-]+$")
        if not ref_pattern.match(source_ref) or not ref_pattern.match(target_ref):
            return {"success": False, "message": "Invalid ref format. Contains disallowed characters."}
        
        # Validate dataset names
        if not self._is_valid_dataset_name(source_dataset) or not self._is_valid_dataset_name(target_dataset):
            return {
                "success": False,
                "message": "Invalid source or target dataset_name. They cannot be '.' or '..', contain slashes, and must consist of alphanumeric characters, underscore, dot, or hyphen."
            }
        
        try:
            # 1. Get changed files using git diff with status
            # Use target_ref...source_ref to find changes introduced by source
            # Add '--' to prevent argument injection
            diff_command = ["git", "diff", "--name-status", f"{target_ref}...{source_ref}", "--"]
            result = subprocess.run(diff_command, capture_output=True, text=True, check=True, cwd=self.cwd)
            changed_files_raw = result.stdout.strip().split('\n')
            
            if not any(changed_files_raw):
                return {"success": True, "message": "No changes to sync"}
            
            # 2. Sync in transaction for atomicity
            synced_count = 0
            deleted_count = 0
            with self.db:  # Transaction context
                for line in changed_files_raw:
                    if not line: 
                        continue
                    
                    parts = line.split('\t')
                    if len(parts) < 2:
                        continue
                    status, filepath = parts[0], parts[1]
                    
                    if status.startswith('D'): # Deleted
                        self.db.execute(
                            "DELETE FROM files WHERE dataset_id = ? AND filepath = ?",
                            (target_dataset, filepath)
                        )
                        deleted_count += 1
                    else: # Added (A) or Modified (M)
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
                "message": f"Synced {synced_count} files and removed {deleted_count} files from '{target_dataset}'",
                "files_checked": len(changed_files_raw),
                "files_synced": synced_count,
                "files_deleted": deleted_count
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
            
            # 2. Find worktree datasets using dataset_type column
            cursor = self.db.execute("""
                SELECT dataset_id, source_branch 
                FROM dataset_metadata 
                WHERE dataset_type = 'worktree' AND source_branch IS NOT NULL
            """)
            type_based_datasets = cursor.fetchall()
            
            # Also check naming convention for backward compatibility with old datasets
            # Skip pattern-based detection since new convention doesn't have a clear pattern
            cursor = self.db.execute("""
                SELECT dataset_id 
                FROM dataset_metadata 
                WHERE dataset_id LIKE '%__wt_%' AND (dataset_type IS NULL OR dataset_type = 'main')
            """)
            pattern_datasets = cursor.fetchall()
            
            # 3. Identify orphans
            orphans = []
            
            # Check type-based datasets
            for row in type_based_datasets:
                dataset_id = row['dataset_id']
                source_branch = row['source_branch']
                sanitized_branch = re.sub(r'[^a-zA-Z0-9_]', '_', source_branch)
                if sanitized_branch not in active_branches:
                    orphans.append({
                        'dataset_id': dataset_id,
                        'source_branch': source_branch,
                        'detection_method': 'dataset_type'
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
                        if config_data.get("mainDatasetName"):
                            dataset_name_to_use = config_data["mainDatasetName"]
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
            
            # Default source directory - use git to determine what should be indexed
            if not source_directory:
                # If we're in a git repository, always index the full project
                # since git tracks files across the entire repository
                try:
                    subprocess.run(
                        ["git", "rev-parse", "--git-dir"],
                        cwd=self.cwd,
                        capture_output=True,
                        check=True
                    )
                    # We're in a git repo, index everything
                    source_directory = "."
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Not a git repo, fall back to common patterns
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
            
            # Check if we're in a worktree
            from helpers.git_helper import get_worktree_info
            wt_info = get_worktree_info(self.cwd)
            
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
                    "config_dataset_name": config_data.get("mainDatasetName") if config_data else None
                },
                "setup_needed": len(setup_steps) > 0,
                "setup_steps": setup_steps
            }
            
            # Add worktree information if applicable
            if wt_info and wt_info['is_worktree']:
                # Check if main dataset exists to inform about data copying
                main_dataset_exists = False
                if has_datasets:
                    for dataset in existing_datasets:
                        if dataset["name"] == final_dataset_name:
                            main_dataset_exists = True
                            break
                
                wt_dataset_name = f"{final_dataset_name}_{wt_info['sanitized_branch']}"
                copy_note = ""
                if main_dataset_exists:
                    copy_note = f" Your existing dataset '{final_dataset_name}' will be COPIED to create the worktree dataset - no data will be lost."
                
                response["worktree_info"] = {
                    "detected": True,
                    "branch": wt_info['branch'],
                    "note": f"🔄 Git worktree detected! A separate dataset '{wt_dataset_name}' will be created for this worktree.{copy_note}",
                    "important": "IMPORTANT: This worktree will use an isolated copy of your data. Changes in this worktree will NOT affect your main dataset."
                }
            
            if recommended_commands:
                # Separate optional git hook commands from required commands
                required_commands = [cmd for cmd in recommended_commands if "git hook" not in cmd.lower()]
                optional_commands = [cmd for cmd in recommended_commands if "git hook" in cmd.lower()]
                
                if required_commands and optional_commands:
                    worktree_warning = ""
                    if wt_info and wt_info['is_worktree']:
                        worktree_warning = "⚠️  **WORKTREE DETECTED**: This will create an ISOLATED copy of your data for this worktree. Your main dataset will remain unchanged.\n\n"
                    
                    response["recommendation"] = (
                        worktree_warning +
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
                    
                    worktree_warning = ""
                    if wt_info and wt_info['is_worktree']:
                        worktree_warning = "⚠️  **WORKTREE DETECTED**: Your data will be isolated in this worktree.\n\n"
                    
                    response["recommendation"] = (
                        worktree_warning +
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
                    
                    worktree_warning = ""
                    if wt_info and wt_info['is_worktree']:
                        worktree_warning = "⚠️  **WORKTREE DETECTED**: This will create an ISOLATED copy of your data for this worktree. Your main dataset will remain unchanged.\n\n"
                    
                    response["recommendation"] = (
                        worktree_warning +
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
    
    def find_files_needing_catchup(self, dataset_name: str) -> Dict[str, Any]:
        """
        Find files that have changed since they were last documented.
        
        Returns files that need to be re-documented due to git changes.
        """
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset name"
            }
        
        try:
            # Get all documented files with their last documented commit
            cursor = self.db.execute("""
                SELECT filepath, documented_at_commit, documented_at
                FROM files 
                WHERE dataset_id = ? AND documented_at_commit IS NOT NULL
                ORDER BY filepath
            """, (dataset_name,))
            
            documented_files = cursor.fetchall()
            
            if not documented_files:
                return {
                    "success": True,
                    "message": "No files found with commit tracking",
                    "files_needing_catchup": [],
                    "total_files": 0
                }
            
            files_needing_catchup = []
            current_commit = get_current_commit(self.cwd)

            # Group files by commit hash to optimize git calls
            files_by_commit = {}
            for file_row in documented_files:
                last_commit = file_row['documented_at_commit']
                if not last_commit:
                    # File was documented without commit tracking (legacy)
                    files_needing_catchup.append({
                        "filepath": file_row['filepath'],
                        "reason": "no_commit_tracking",
                        "last_documented_commit": None,
                        "documented_at": file_row['documented_at'],
                        "current_commit": current_commit
                    })
                else:
                    if last_commit not in files_by_commit:
                        files_by_commit[last_commit] = []
                    files_by_commit[last_commit].append(file_row)

            # Process files grouped by commit
            for last_commit, files in files_by_commit.items():
                changed_files_since_commit = set(get_changed_files_since_commit(last_commit, self.cwd))
                for file_row in files:
                    # Normalize database filepath to match git output format
                    db_filepath = file_row['filepath']
                    normalized_filepath = db_filepath.lstrip('./')  # Remove leading ./
                    
                    if normalized_filepath in changed_files_since_commit:
                        files_needing_catchup.append({
                            "filepath": file_row['filepath'],
                            "reason": "file_changed",
                            "last_documented_commit": last_commit,
                            "documented_at": file_row['documented_at'],
                            "current_commit": current_commit
                        })
            
            return {
                "success": True,
                "message": f"Found {len(files_needing_catchup)} files needing catchup out of {len(documented_files)} total documented files",
                "files_needing_catchup": files_needing_catchup,
                "total_documented_files": len(documented_files),
                "current_commit": current_commit
            }
            
        except Exception as e:
            logging.error(f"Error finding files needing catchup for {dataset_name}", exc_info=True)
            return {
                "success": False,
                "message": f"Error finding files needing catchup: {str(e)}"
            }
    
    def backport_commit_to_file(self, dataset_name: str, filepath: str, commit_hash: str) -> Dict[str, Any]:
        """
        Associate a commit hash with a file that was documented without commit tracking.
        
        This is useful for legacy files that were documented before commit tracking was implemented.
        """
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset name"
            }
        
        try:
            # Check if file exists in dataset
            cursor = self.db.execute("""
                SELECT filepath, documented_at_commit 
                FROM files 
                WHERE dataset_id = ? AND filepath = ?
            """, (dataset_name, filepath))
            
            file_row = cursor.fetchone()
            if not file_row:
                return {
                    "success": False,
                    "message": f"File '{filepath}' not found in dataset '{dataset_name}'"
                }
            
            # Update the commit hash
            self.db.execute("""
                UPDATE files 
                SET documented_at_commit = ?
                WHERE dataset_id = ? AND filepath = ?
            """, (commit_hash, dataset_name, filepath))
            
            return {
                "success": True,
                "message": f"Successfully associated commit {commit_hash[:8]} with file '{filepath}'",
                "filepath": filepath,
                "commit_hash": commit_hash,
                "previous_commit": file_row['documented_at_commit']
            }
            
        except Exception as e:
            logging.error(f"Error backporting commit {commit_hash} to file {filepath} in dataset {dataset_name}", exc_info=True)
            return {
                "success": False,
                "message": f"Error backporting commit to file: {str(e)}"
            }
    
    def bulk_backport_commits(self, dataset_name: str, commit_hash: str = None) -> Dict[str, Any]:
        """
        Backport commit hash to all files in dataset that don't have commit tracking.
        
        If commit_hash is None, uses current HEAD commit.
        """
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Validate dataset name
        if not self._is_valid_dataset_name(dataset_name):
            return {
                "success": False,
                "message": "Invalid dataset name"
            }
        
        try:
            # Use current commit if none provided
            if not commit_hash:
                commit_hash = get_current_commit(self.cwd)
                if not commit_hash:
                    return {
                        "success": False,
                        "message": "Could not determine current commit and no commit hash provided"
                    }
            
            # Find files without commit tracking
            cursor = self.db.execute("""
                SELECT filepath 
                FROM files 
                WHERE dataset_id = ? AND documented_at_commit IS NULL
            """, (dataset_name,))
            
            files_to_update = [row['filepath'] for row in cursor.fetchall()]
            
            if not files_to_update:
                return {
                    "success": True,
                    "message": "No files found without commit tracking",
                    "updated_files": [],
                    "commit_hash": commit_hash
                }
            
            # Update all files in a single, efficient query
            self.db.execute("""
                UPDATE files 
                SET documented_at_commit = ?
                WHERE dataset_id = ? AND documented_at_commit IS NULL
            """, (commit_hash, dataset_name))
            
            return {
                "success": True,
                "message": f"Successfully backported commit {commit_hash[:8]} to {len(files_to_update)} files",
                "updated_files": files_to_update,
                "commit_hash": commit_hash,
                "total_updated": len(files_to_update)
            }
            
        except Exception as e:
            logging.error(f"Error bulk backporting commits for dataset {dataset_name}", exc_info=True)
            return {
                "success": False,
                "message": f"Error bulk backporting commits: {str(e)}"
            }