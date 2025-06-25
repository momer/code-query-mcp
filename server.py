#!/usr/bin/env python3
"""Code Query MCP Server - Search and query code review JSON files.

Dataset Discovery Pattern:
When using any tool that requires a dataset_name parameter, if the dataset name
is unknown, use the list_datasets tool first to discover available datasets.
This ensures Claude can always find the appropriate dataset for the current project.
"""

import os
import json
import sqlite3
import glob
import logging
import fnmatch
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel import NotificationOptions

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Database configuration
DB_DIR = os.path.join(os.getcwd(), ".mcp_code_query")
DB_PATH = os.path.join(DB_DIR, "code_data.db")


class CodeQueryServer:
    def __init__(self):
        self.db = None
        self.cwd = os.getcwd()
        # Ensure database directory exists
        os.makedirs(DB_DIR, exist_ok=True)
        
    def setup_database(self):
        """Connect to persistent SQLite database."""
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        
        # Enable FTS5 if available
        self.db.execute("PRAGMA compile_options")
        
        # Check if schema exists
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files'
        """)
        
        if not cursor.fetchone():
            self._create_schema()
            logging.info(f"Created database schema at {DB_PATH}")
        else:
            # Check if we need to migrate to newer schema
            self._migrate_schema()
            logging.info(f"Connected to existing database at {DB_PATH}")
    
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
        
        # FTS5 virtual table for full-text search
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
                content=files,
                content_rowid=rowid,
                tokenize='porter unicode61'
            )
        """)
        
        # Triggers to keep FTS5 in sync with main table
        self.db.execute("""
            CREATE TRIGGER files_fts_insert AFTER INSERT ON files BEGIN
                INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                    ddd_context, functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes)
                VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview,
                    new.ddd_context, new.functions, new.exports, new.imports, 
                    new.types_interfaces_classes, new.constants, new.dependencies, new.other_notes);
            END
        """)
        
        self.db.execute("""
            CREATE TRIGGER files_fts_update AFTER UPDATE ON files BEGIN
                UPDATE files_fts SET 
                    dataset_id = new.dataset_id,
                    filepath = new.filepath,
                    filename = new.filename,
                    overview = new.overview,
                    ddd_context = new.ddd_context,
                    functions = new.functions,
                    exports = new.exports,
                    imports = new.imports,
                    types_interfaces_classes = new.types_interfaces_classes,
                    constants = new.constants,
                    dependencies = new.dependencies,
                    other_notes = new.other_notes
                WHERE rowid = new.rowid;
            END
        """)
        
        self.db.execute("""
            CREATE TRIGGER files_fts_delete AFTER DELETE ON files BEGIN
                DELETE FROM files_fts WHERE rowid = old.rowid;
            END
        """)
        
        # Spellfix1 virtual table for typo correction
        try:
            self.db.execute("""
                CREATE VIRTUAL TABLE spellfix_terms USING spellfix1
            """)
        except sqlite3.OperationalError as e:
            # Spellfix1 might not be available in all SQLite builds
            logging.warning(f"Spellfix1 not available: {e}")
        
        # Metadata table for tracking datasets
        self.db.execute("""
            CREATE TABLE dataset_metadata (
                dataset_id TEXT PRIMARY KEY,
                source_dir TEXT,
                files_count INTEGER,
                loaded_at TIMESTAMP,
                schema_version INTEGER DEFAULT 2
            )
        """)
        
        # Schema version table for migrations
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.db.execute("INSERT INTO schema_version (version) VALUES (2)")
        
        self.db.commit()
    
    def _migrate_schema(self):
        """Migrate database schema to latest version."""
        # Check current schema version
        try:
            cursor = self.db.execute("SELECT MAX(version) as version FROM schema_version")
            current_version = cursor.fetchone()['version'] or 1
        except sqlite3.OperationalError:
            # schema_version table doesn't exist, we're at version 1
            current_version = 1
            self.db.execute("""
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db.execute("INSERT INTO schema_version (version) VALUES (1)")
        
        # Migrate from version 1 to 2 (add FTS5)
        if current_version < 2:
            logging.info("Migrating database schema from version 1 to 2 (adding FTS5)")
            
            # Add schema_version column to dataset_metadata if not exists
            try:
                self.db.execute("ALTER TABLE dataset_metadata ADD COLUMN schema_version INTEGER DEFAULT 2")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Create FTS5 virtual table
            try:
                self.db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
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
                        content=files,
                        content_rowid=rowid,
                        tokenize='porter unicode61'
                    )
                """)
                
                # Create triggers
                self.db.execute("""
                    CREATE TRIGGER IF NOT EXISTS files_fts_insert AFTER INSERT ON files BEGIN
                        INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                            ddd_context, functions, exports, imports, types_interfaces_classes,
                            constants, dependencies, other_notes)
                        VALUES (new.rowid, new.dataset_id, new.filepath, new.filename, new.overview,
                            new.ddd_context, new.functions, new.exports, new.imports, 
                            new.types_interfaces_classes, new.constants, new.dependencies, new.other_notes);
                    END
                """)
                
                self.db.execute("""
                    CREATE TRIGGER IF NOT EXISTS files_fts_update AFTER UPDATE ON files BEGIN
                        UPDATE files_fts SET 
                            dataset_id = new.dataset_id,
                            filepath = new.filepath,
                            filename = new.filename,
                            overview = new.overview,
                            ddd_context = new.ddd_context,
                            functions = new.functions,
                            exports = new.exports,
                            imports = new.imports,
                            types_interfaces_classes = new.types_interfaces_classes,
                            constants = new.constants,
                            dependencies = new.dependencies,
                            other_notes = new.other_notes
                        WHERE rowid = new.rowid;
                    END
                """)
                
                self.db.execute("""
                    CREATE TRIGGER IF NOT EXISTS files_fts_delete AFTER DELETE ON files BEGIN
                        DELETE FROM files_fts WHERE rowid = old.rowid;
                    END
                """)
                
                # Populate FTS5 table with existing data
                self.db.execute("""
                    INSERT INTO files_fts(rowid, dataset_id, filepath, filename, overview, 
                        ddd_context, functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes)
                    SELECT rowid, dataset_id, filepath, filename, overview,
                        ddd_context, functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes
                    FROM files
                """)
                
                logging.info("Successfully created FTS5 virtual table and migrated existing data")
            except sqlite3.OperationalError as e:
                logging.error(f"Failed to create FTS5 table: {e}")
                logging.warning("FTS5 may not be available in your SQLite build. Search will use standard LIKE queries.")
            
            # Try to create spellfix1 table
            try:
                self.db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS spellfix_terms USING spellfix1
                """)
                logging.info("Successfully created spellfix1 virtual table")
            except sqlite3.OperationalError:
                logging.warning("Spellfix1 not available in your SQLite build. Typo correction will not be available.")
            
            # Update schema version
            self.db.execute("INSERT INTO schema_version (version) VALUES (2)")
            self.db.commit()
    
    def validate_directory(self, directory: str) -> str:
        """Validate and resolve directory path."""
        # Prevent absolute paths
        if os.path.isabs(directory):
            raise ValueError("Absolute paths are not allowed for security reasons.")
        
        # Resolve the real path to guard against traversal attacks
        # os.path.normpath is not enough, realpath resolves '..' and symlinks
        full_path = os.path.realpath(os.path.join(self.cwd, directory))
        cwd_real = os.path.realpath(self.cwd)
        
        if not full_path.startswith(cwd_real):
            raise ValueError("Path traversal attempt detected. Only subdirectories are allowed.")
        
        # Check if directory exists
        if not os.path.isdir(full_path):
            raise ValueError(f"Directory not found or is not a directory: {directory}")
        
        return full_path
    
    def import_data(self, dataset_name: str, directory: str, replace: bool = False) -> Dict[str, Any]:
        """Import JSON files from directory into named dataset."""
        try:
            # Validate directory
            full_path = self.validate_directory(directory)
            
            # Check if dataset already exists
            existing = self.db.execute(
                "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if existing and not replace:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' already exists with {existing['files_count']} files. Use replace=true to overwrite."
                }
            
            # If replacing, delete existing data
            if existing and replace:
                self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
                self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
                self.db.commit()
            
            # Find JSON files
            patterns = [
                os.path.join(full_path, "agent_*_review.json"),
                os.path.join(full_path, "*.json")
            ]
            
            # Use a set to avoid duplicates if a file matches multiple patterns
            json_files = set()
            for pattern in patterns:
                json_files.update(glob.glob(pattern))
            
            if not json_files:
                return {
                    "success": False,
                    "message": f"No JSON files found in {directory}"
                }
            
            # Load files
            files_loaded = 0
            errors = []
            
            for json_file in json_files:
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                    
                    # Handle both single object and array formats
                    if isinstance(data, list):
                        for item in data:
                            if self._insert_file_data(dataset_name, item):
                                files_loaded += 1
                    else:
                        if self._insert_file_data(dataset_name, data):
                            files_loaded += 1
                            
                except Exception as e:
                    error_msg = f"Error loading {os.path.basename(json_file)}: {e}"
                    logging.error(error_msg)
                    errors.append(error_msg)
            
            # Update metadata
            self.db.execute("""
                INSERT OR REPLACE INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, ?, ?)
            """, (dataset_name, directory, files_loaded, datetime.now()))
            
            self.db.commit()
            
            # Populate spellfix vocabulary if available
            self._populate_spellfix_vocabulary(dataset_name)
            
            result = {
                "success": True,
                "dataset_name": dataset_name,
                "files_loaded": files_loaded,
                "source": directory
            }
            
            if errors:
                result["errors"] = errors
            
            logging.info(f"Imported {files_loaded} files into dataset '{dataset_name}' from {directory}")
            return result
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def _insert_file_data(self, dataset_id: str, data: dict) -> bool:
        """Insert a single file's data into the database."""
        try:
            self.db.execute("""
                INSERT OR REPLACE INTO files (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dataset_id,
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
            return True
        except Exception as e:
            logging.error(f"Error inserting file data: {e}")
            return False
    
    def search_files(self, query: str, dataset_name: str, limit: int = 10) -> Dict[str, Any]:
        """Search files in specific dataset by query string using FTS5 if available."""
        if not self.db:
            return {"results": [], "search_info": {"method": "No database", "features_used": []}}
        
        # Check if FTS5 is available
        cursor = self.db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='files_fts'
        """)
        
        has_fts5 = cursor.fetchone() is not None
        search_metadata = {
            "method": "LIKE",
            "features_used": []
        }
        
        if has_fts5:
            # Use FTS5 for better search
            search_metadata["method"] = "FTS5"
            search_metadata["features_used"].append("Full-text search with Porter tokenizer")
            
            # Clean query for FTS5 - escape special characters
            fts_query = query.replace('"', '""')
            
            # Try spell correction if available
            corrected_query = self._get_spell_corrected_query(query)
            if corrected_query and corrected_query != query:
                logging.info(f"Spell correction: '{query}' -> '{corrected_query}'")
                search_metadata["features_used"].append(f"Spell correction: '{query}' → '{corrected_query}'")
                fts_query = f'({fts_query} OR {corrected_query})'
            
            cursor = self.db.execute("""
                SELECT DISTINCT f.filepath, f.filename, f.overview, f.ddd_context,
                       highlight(files_fts, 2, '<mark>', '</mark>') as highlighted_overview,
                       rank * -1 as relevance
                FROM files_fts fts
                JOIN files f ON f.rowid = fts.rowid
                WHERE fts.dataset_id = ? AND files_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (dataset_name, fts_query, limit))
            
            search_metadata["features_used"].append("Result highlighting")
            search_metadata["features_used"].append("Relevance ranking")
        else:
            # Fallback to LIKE queries
            search_metadata["features_used"].append("Pattern matching across all fields")
            cursor = self.db.execute("""
                SELECT filepath, filename, overview, ddd_context
                FROM files
                WHERE dataset_id = ? AND (
                    filename LIKE ? OR filepath LIKE ? OR overview LIKE ? 
                    OR ddd_context LIKE ? OR functions LIKE ? OR other_notes LIKE ?
                )
                LIMIT ?
            """, (
                dataset_name,
                f'%{query}%', f'%{query}%', f'%{query}%',
                f'%{query}%', f'%{query}%', f'%{query}%', limit
            ))
        
        results = []
        for row in cursor:
            result = {
                'filepath': row['filepath'],
                'filename': row['filename'],
                'overview': row['overview'],
                'ddd_context': row['ddd_context']
            }
            # Include highlighted overview if available
            if has_fts5 and 'highlighted_overview' in row.keys():
                if row['highlighted_overview']:
                    result['overview'] = row['highlighted_overview']
            results.append(result)
        
        return {
            "results": results,
            "search_info": search_metadata
        }
    
    def _get_spell_corrected_query(self, query: str) -> Optional[str]:
        """Get spell-corrected version of query using spellfix1 if available."""
        try:
            # Check if spellfix1 is available
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='spellfix_terms'
            """)
            
            if not cursor.fetchone():
                return None
            
            # Split query into words and correct each
            words = query.split()
            corrected_words = []
            
            for word in words:
                cursor = self.db.execute("""
                    SELECT word FROM spellfix_terms 
                    WHERE word MATCH ? AND distance <= 2
                    ORDER BY score
                    LIMIT 1
                """, (word,))
                
                result = cursor.fetchone()
                if result:
                    corrected_words.append(result['word'])
                else:
                    corrected_words.append(word)
            
            corrected = ' '.join(corrected_words)
            return corrected if corrected != query else None
            
        except Exception as e:
            logging.debug(f"Spell correction failed: {e}")
            return None
    
    def _populate_spellfix_vocabulary(self, dataset_name: str):
        """Populate spellfix1 vocabulary from dataset for better typo correction."""
        try:
            # Check if spellfix1 is available
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='spellfix_terms'
            """)
            
            if not cursor.fetchone():
                return
            
            # Extract unique words from the dataset
            cursor = self.db.execute("""
                SELECT DISTINCT filename, overview, ddd_context
                FROM files
                WHERE dataset_id = ?
            """, (dataset_name,))
            
            vocabulary = set()
            for row in cursor:
                # Extract words from text fields
                for field in ['filename', 'overview', 'ddd_context']:
                    if row[field]:
                        # Simple word extraction (could be improved with proper tokenization)
                        words = row[field].replace('_', ' ').replace('-', ' ').replace('/', ' ').split()
                        for word in words:
                            # Clean and filter words
                            word = word.strip('.,;:!?"\'()[]{}').lower()
                            if len(word) > 2 and word.isalnum():
                                vocabulary.add(word)
            
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
        """List all unique DDD context domains in dataset."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT DISTINCT ddd_context FROM files
            WHERE dataset_id = ? AND ddd_context IS NOT NULL AND ddd_context != ''
            ORDER BY ddd_context
        """, (dataset_name,))
        
        return [row[0] for row in cursor]
    
    def list_datasets(self) -> List[Dict[str, Any]]:
        """List all loaded datasets."""
        if not self.db:
            return []
        
        cursor = self.db.execute("""
            SELECT dataset_id, source_dir, files_count, loaded_at
            FROM dataset_metadata
            ORDER BY loaded_at DESC
        """)
        
        results = []
        for row in cursor:
            results.append({
                'name': row['dataset_id'],
                'source': row['source_dir'],
                'file_count': row['files_count'],
                'loaded_at': row['loaded_at']
            })
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current database status."""
        datasets = self.list_datasets()
        total_files = sum(d['file_count'] for d in datasets)
        
        return {
            'database_path': DB_PATH,
            'datasets': datasets,
            'total_files': total_files
        }
    
    def clear_dataset(self, dataset_name: str) -> Dict[str, Any]:
        """Clear a specific dataset."""
        if not self.db:
            return {"success": False, "message": "Database not connected"}
        
        # Check if dataset exists
        existing = self.db.execute(
            "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
            (dataset_name,)
        ).fetchone()
        
        if not existing:
            return {
                "success": False,
                "message": f"Dataset '{dataset_name}' not found"
            }
        
        # Delete data
        self.db.execute("DELETE FROM files WHERE dataset_id = ?", (dataset_name,))
        self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
        self.db.commit()
        
        return {
            "success": True,
            "message": f"Cleared dataset '{dataset_name}' with {existing['files_count']} files"
        }
    
    def _scan_directory(self, directory: str, exclude_patterns: List[str] = None) -> List[str]:
        """Scan directory for code files, respecting exclusion patterns."""
        exclude_patterns = exclude_patterns or []
        
        # Default exclude patterns
        default_excludes = ['node_modules', '.git', '.venv', '__pycache__', '*.pyc', '*.pyo']
        all_excludes = default_excludes + exclude_patterns
        
        # Supported file extensions
        code_extensions = {'.py', '.js', '.jsx', '.ts', '.tsx', '.astro', '.vue', '.svelte'}
        
        files = []
        for root, dirs, filenames in os.walk(directory):
            # Remove excluded directories from dirs to prevent walking into them
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pattern) for pattern in all_excludes)]
            
            for filename in filenames:
                # Check if file should be excluded
                if any(fnmatch.fnmatch(filename, pattern) for pattern in all_excludes):
                    continue
                
                # Check if file has supported extension
                if any(filename.endswith(ext) for ext in code_extensions):
                    rel_path = os.path.relpath(os.path.join(root, filename), directory)
                    files.append(rel_path)
        
        return sorted(files)
    
    def document_directory(self, dataset_name: str, directory: str, 
                         exclude_patterns: List[str] = None, batch_size: int = 20) -> Dict[str, Any]:
        """Generate instructions for Claude to orchestrate documentation of a directory."""
        try:
            # Validate directory
            full_path = self.validate_directory(directory)
            
            # Check if dataset already exists
            existing = self.db.execute(
                "SELECT files_count FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if existing:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' already exists. Please choose a different name or clear the existing dataset first."
                }
            
            # Create dataset entry
            self.db.execute("""
                INSERT INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, ?, ?)
            """, (dataset_name, directory, 0, datetime.now()))
            self.db.commit()
            
            # Scan directory for files
            files = self._scan_directory(full_path, exclude_patterns)
            
            if not files:
                # Remove the empty dataset
                self.db.execute("DELETE FROM dataset_metadata WHERE dataset_id = ?", (dataset_name,))
                self.db.commit()
                return {
                    "success": False,
                    "message": f"No code files found in {directory}"
                }
            
            # Create batches
            batches = {}
            for i in range(0, len(files), batch_size):
                batch_num = (i // batch_size) + 1
                batches[f"batch_{batch_num}"] = files[i:i + batch_size]
            
            # Generate instructions
            instructions = f"""I'll help you document the codebase in '{directory}' with {len(files)} files divided into {len(batches)} batches.

Please create {len(batches)} subagents to analyze the code files in parallel. Each agent should:

1. Process their assigned batch of files
2. For each file, analyze the code and extract:
   - Overview (1-3 sentences about the file's purpose)
   - Functions with parameters, returns, and purpose
   - Exports and what they provide
   - Imports and their sources
   - Types, interfaces, and classes
   - Constants and their purposes
   - DDD context (based on directory structure)
   - Dependencies (external libraries used)
   - Other relevant notes

3. Use the code-query MCP insert_file_documentation tool to store each file's analysis:
   "Use code-query MCP insert_file_documentation with dataset_name='{dataset_name}' and the file details"

4. Report completion status for tracking

The agents should respect DDD boundaries and understand the broader application context when analyzing files."""

            agent_template = """You are Agent {{AGENT_ID}} analyzing code files for documentation.

Your assigned files from '{directory}':
{{FILE_LIST}}

For each file:
1. Read and analyze the code thoroughly
2. Extract all relevant metadata (functions, types, imports, etc.)
3. Understand the file's role in the DDD architecture
4. Store the analysis using:
   "Use code-query MCP insert_file_documentation tool with dataset_name='{dataset_name}', filepath='{{FILEPATH}}', and all the extracted details"

Focus on being concise but comprehensive. Identify the core purpose and key elements of each file."""

            mcp_insert_template = {
                "tool": "insert_file_documentation",
                "parameters": {
                    "dataset_name": dataset_name,
                    "filepath": "path/to/file.ts",
                    "filename": "file.ts",
                    "overview": "Brief description of file purpose",
                    "functions": {
                        "functionName": {
                            "purpose": "What it does",
                            "parameters": ["param1: string", "param2: number"],
                            "returns": "ReturnType"
                        }
                    },
                    "exports": {
                        "exportName": "Description of export"
                    },
                    "imports": {
                        "from": ["what", "is", "imported"]
                    },
                    "types_interfaces_classes": {
                        "TypeName": "Description or definition"
                    },
                    "constants": {
                        "CONST_NAME": "Value or description"
                    },
                    "ddd_context": "domain-name",
                    "dependencies": ["react", "lodash"],
                    "other_notes": ["Additional observations"]
                }
            }
            
            return {
                "success": True,
                "dataset_name": dataset_name,
                "directory": directory,
                "total_files": len(files),
                "batch_count": len(batches),
                "batch_size": batch_size,
                "files_by_batch": batches,
                "instructions": instructions,
                "agent_template": agent_template.format(directory=directory, dataset_name=dataset_name),
                "mcp_insert_example": mcp_insert_template,
                "next_steps": [
                    f"Create {len(batches)} subagents",
                    "Assign each agent their batch of files",
                    "Agents analyze and insert documentation for each file",
                    "Monitor progress and handle any errors",
                    "Verify all files were processed successfully"
                ]
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def insert_file_documentation(self, dataset_name: str, filepath: str, filename: str,
                                overview: str, functions: Dict[str, Any] = None,
                                exports: Dict[str, str] = None, imports: Dict[str, List[str]] = None,
                                types_interfaces_classes: Dict[str, str] = None,
                                constants: Dict[str, str] = None, ddd_context: str = "",
                                dependencies: List[str] = None, other_notes: List[str] = None) -> Dict[str, Any]:
        """Insert file documentation analyzed by agents."""
        try:
            # Check if dataset exists
            existing = self.db.execute(
                "SELECT dataset_id FROM dataset_metadata WHERE dataset_id = ?",
                (dataset_name,)
            ).fetchone()
            
            if not existing:
                return {
                    "success": False,
                    "message": f"Dataset '{dataset_name}' not found. Please create it first using document_directory."
                }
            
            # Prepare data for insertion
            data = {
                'filepath': filepath,
                'filename': filename,
                'overview': overview,
                'ddd_context': ddd_context or self._extract_ddd_context(filepath),
                'functions': functions or {},
                'exports': exports or {},
                'imports': imports or {},
                'types_interfaces_classes': types_interfaces_classes or {},
                'constants': constants or {},
                'dependencies': dependencies or [],
                'other_notes': other_notes or []
            }
            
            # Insert the file data
            if self._insert_file_data(dataset_name, data):
                # Update file count
                self.db.execute("""
                    UPDATE dataset_metadata 
                    SET files_count = (
                        SELECT COUNT(*) FROM files WHERE dataset_id = ?
                    )
                    WHERE dataset_id = ?
                """, (dataset_name, dataset_name))
                self.db.commit()
                
                return {
                    "success": True,
                    "message": f"Successfully inserted documentation for {filepath}"
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to insert documentation for {filepath}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Error inserting documentation: {str(e)}"
            }
    
    def _extract_ddd_context(self, filepath: str) -> str:
        """Extract DDD context from filepath based on directory structure."""
        parts = filepath.split('/')
        
        # Look for common DDD patterns
        if 'features' in parts:
            idx = parts.index('features')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        elif 'domains' in parts:
            idx = parts.index('domains')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        elif 'modules' in parts:
            idx = parts.index('modules')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        
        # Default to first meaningful directory
        for part in parts:
            if part not in ['src', 'lib', 'app'] and not part.startswith('.'):
                return part
        
        return ""
    
    def update_file_documentation(self, dataset_name: str, filepath: str, filename: str = None,
                                overview: str = None, functions: Dict[str, Any] = None,
                                exports: Dict[str, str] = None, imports: Dict[str, List[str]] = None,
                                types_interfaces_classes: Dict[str, str] = None,
                                constants: Dict[str, str] = None, ddd_context: str = None,
                                dependencies: List[str] = None, other_notes: List[str] = None) -> Dict[str, Any]:
        """Update existing file documentation in dataset."""
        try:
            # Check if file exists in dataset
            existing = self.db.execute(
                "SELECT * FROM files WHERE dataset_id = ? AND filepath = ?",
                (dataset_name, filepath)
            ).fetchone()
            
            if not existing:
                return {
                    "success": False,
                    "message": f"File '{filepath}' not found in dataset '{dataset_name}'. Use insert_file_documentation for new files."
                }
            
            # Build update query dynamically based on provided fields
            update_fields = []
            update_values = []
            
            if filename is not None:
                update_fields.append("filename = ?")
                update_values.append(filename)
            if overview is not None:
                update_fields.append("overview = ?")
                update_values.append(overview)
            if ddd_context is not None:
                update_fields.append("ddd_context = ?")
                update_values.append(ddd_context)
            if functions is not None:
                update_fields.append("functions = ?")
                update_values.append(json.dumps(functions))
            if exports is not None:
                update_fields.append("exports = ?")
                update_values.append(json.dumps(exports))
            if imports is not None:
                update_fields.append("imports = ?")
                update_values.append(json.dumps(imports))
            if types_interfaces_classes is not None:
                update_fields.append("types_interfaces_classes = ?")
                update_values.append(json.dumps(types_interfaces_classes))
            if constants is not None:
                update_fields.append("constants = ?")
                update_values.append(json.dumps(constants))
            if dependencies is not None:
                update_fields.append("dependencies = ?")
                update_values.append(json.dumps(dependencies))
            if other_notes is not None:
                update_fields.append("other_notes = ?")
                update_values.append(json.dumps(other_notes))
            
            if not update_fields:
                return {
                    "success": False,
                    "message": "No fields provided to update"
                }
            
            # Add WHERE clause values
            update_values.extend([dataset_name, filepath])
            
            # Execute update
            update_query = f"""
                UPDATE files 
                SET {', '.join(update_fields)}
                WHERE dataset_id = ? AND filepath = ?
            """
            
            self.db.execute(update_query, update_values)
            self.db.commit()
            
            return {
                "success": True,
                "message": f"Successfully updated documentation for {filepath}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error updating documentation: {str(e)}"
            }
    
    def get_project_config(self) -> Dict[str, Any]:
        """Get comprehensive project configuration including git hooks status."""
        result = {
            "success": True,
            "project_root": self.cwd,
            "config_exists": False,
            "config": None,
            "git_hooks": {
                "pre_commit": {
                    "installed": False,
                    "is_code_query": False,
                    "path": None
                },
                "post_merge": {
                    "installed": False,
                    "is_code_query": False,
                    "path": None
                }
            },
            "datasets": [],
            "worktree_info": None
        }
        
        # Check configuration file
        config_path = os.path.join(self.cwd, ".code-query", "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                result["config_exists"] = True
                result["config"] = config
            except (IOError, OSError, json.JSONDecodeError) as e:
                result["config_error"] = f"Error reading configuration: {str(e)}"
                logging.warning(f"Could not read config file: {e}")
        
        # Check git repository status
        git_dir = os.path.join(self.cwd, ".git")
        if os.path.exists(git_dir):
            result["git_repository"] = True
            
            # Check for git hooks
            hooks_dir = os.path.join(git_dir, "hooks")
            
            # Check pre-commit hook
            pre_commit_path = os.path.join(hooks_dir, "pre-commit")
            if os.path.exists(pre_commit_path):
                result["git_hooks"]["pre_commit"]["installed"] = True
                result["git_hooks"]["pre_commit"]["path"] = pre_commit_path
                try:
                    with open(pre_commit_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if "Code Query MCP Pre-commit Hook" in content:
                            result["git_hooks"]["pre_commit"]["is_code_query"] = True
                except (IOError, OSError) as e:
                    logging.warning(f"Could not read pre-commit hook file: {e}")
            
            # Check post-merge hook
            post_merge_path = os.path.join(hooks_dir, "post-merge")
            if os.path.exists(post_merge_path):
                result["git_hooks"]["post_merge"]["installed"] = True
                result["git_hooks"]["post_merge"]["path"] = post_merge_path
                try:
                    with open(post_merge_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if "Code Query MCP Post-merge Hook" in content:
                            result["git_hooks"]["post_merge"]["is_code_query"] = True
                except (IOError, OSError) as e:
                    logging.warning(f"Could not read post-merge hook file: {e}")
            
            # Check if we're in a worktree
            try:
                # Get git directory path
                git_dir_result = subprocess.run(
                    ["git", "rev-parse", "--git-dir"],
                    cwd=self.cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10
                )
                git_dir_path = git_dir_result.stdout.strip()
                
                # Check if this is a worktree (path contains .git/worktrees/)
                if ".git/worktrees/" in git_dir_path:
                    # Extract worktree name from path
                    worktree_name = os.path.basename(git_dir_path)
                    
                    # Get current branch name
                    branch_result = subprocess.run(
                        ["git", "branch", "--show-current"],
                        cwd=self.cwd,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=10
                    )
                    branch_name = branch_result.stdout.strip()
                    
                    result["worktree_info"] = {
                        "is_worktree": True,
                        "branch": branch_name,
                        "worktree_name": worktree_name,
                        "worktree_dataset_name": None
                    }
                    
                    # Calculate worktree dataset name if config exists
                    if result.get("config") and result["config"].get("datasetName"):
                        base_dataset = result["config"]["datasetName"]
                        # Use worktree directory name, matching shell scripts
                        worktree_dataset = f"{base_dataset}-wt-{worktree_name}"
                        result["worktree_info"]["worktree_dataset_name"] = worktree_dataset
                        
            except FileNotFoundError:
                logging.warning("git command not found. Skipping worktree checks.")
            except subprocess.CalledProcessError as e:
                logging.warning(f"git command failed: {e}")
                if e.stderr:
                    logging.warning(f"git stderr: {e.stderr}")
            except subprocess.TimeoutExpired:
                logging.warning("git command timed out")
            except OSError as e:
                logging.warning(f"OS error running git command: {e}")
        else:
            result["git_repository"] = False
        
        # Get dataset information
        try:
            datasets_list = self.list_datasets()
            # FIX: list_datasets returns a list, not a dict
            if datasets_list:
                result["datasets"] = datasets_list
                
                # Check if configured dataset exists
                if result.get("config") and result["config"].get("datasetName"):
                    dataset_name = result["config"]["datasetName"]
                    dataset_exists = any(d["name"] == dataset_name for d in result["datasets"])
                    result["configured_dataset_exists"] = dataset_exists
                    
                    # Check if worktree dataset exists
                    if result.get("worktree_info") and result["worktree_info"].get("worktree_dataset_name"):
                        worktree_dataset_name = result["worktree_info"]["worktree_dataset_name"]
                        worktree_dataset_exists = any(d["name"] == worktree_dataset_name for d in result["datasets"])
                        result["worktree_info"]["dataset_exists"] = worktree_dataset_exists
        except Exception as e:
            logging.warning(f"Could not retrieve dataset information: {e}")
        
        # Check for other code-query files
        code_query_dir = os.path.join(self.cwd, ".code-query")
        if os.path.exists(code_query_dir):
            result["code_query_files"] = {
                "git_doc_update": os.path.exists(os.path.join(code_query_dir, "git-doc-update")),
                "update_queue": os.path.exists(os.path.join(code_query_dir, "update_queue.txt")),
                "gitignore": os.path.exists(os.path.join(code_query_dir, ".gitignore"))
            }
            
            # Check update queue status
            queue_file = os.path.join(code_query_dir, "update_queue.txt")
            if os.path.exists(queue_file):
                try:
                    with open(queue_file, 'r') as f:
                        queued_files = [line.strip() for line in f if line.strip()]
                    result["update_queue_count"] = len(queued_files)
                except (IOError, OSError) as e:
                    logging.warning(f"Could not read update queue file: {e}")
        
        # Generate setup recommendations
        setup_complete = (
            result.get("config_exists", False) and
            result.get("git_hooks", {}).get("pre_commit", {}).get("is_code_query", False) and
            result.get("configured_dataset_exists", False)
        )
        
        result["setup_complete"] = setup_complete
        
        if not setup_complete:
            recommendations = []
            
            if not result.get("configured_dataset_exists", False):
                recommendations.append("Document your codebase or import existing data")
            
            if not result.get("config_exists", False):
                recommendations.append("Create project configuration with create_project_config")
            
            if result.get("git_repository", False) and not result.get("git_hooks", {}).get("pre_commit", {}).get("is_code_query", False):
                recommendations.append("Install pre-commit hook for automatic documentation updates")
            
            result["setup_recommendations"] = recommendations
        
        return result
    
    def create_project_config(self, dataset_name: str, exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """Create or update project configuration file."""
        try:
            # Create .code-query directory
            code_query_dir = os.path.join(self.cwd, ".code-query")
            os.makedirs(code_query_dir, exist_ok=True)
            
            # Set default exclude patterns if not provided
            if exclude_patterns is None:
                exclude_patterns = ["*.test.js", "*.spec.ts", "node_modules/*", ".git/*", "build/*", "dist/*"]
            
            # Create configuration
            config = {
                "datasetName": dataset_name,
                "excludePatterns": exclude_patterns,
                "createdAt": datetime.now().isoformat()
            }
            
            # Check if config already exists
            config_path = os.path.join(code_query_dir, "config.json")
            if os.path.exists(config_path):
                # Read existing config
                with open(config_path, 'r') as f:
                    existing_config = json.load(f)
                
                # Update with new values but preserve existing ones
                config["updatedAt"] = datetime.now().isoformat()
                if "createdAt" in existing_config:
                    config["createdAt"] = existing_config["createdAt"]
                if "mode" in existing_config:
                    config["mode"] = existing_config["mode"]
            
            # Write configuration
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Create .gitignore if needed
            gitignore_path = os.path.join(code_query_dir, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, 'w') as f:
                    f.write("update_queue.txt\n")
            
            return {
                "success": True,
                "message": f"Successfully created/updated configuration for dataset '{dataset_name}'",
                "config_path": config_path,
                "config": config
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Error creating configuration: {str(e)}"
            }
    
    def fork_dataset(self, source_dataset: str, target_dataset: str) -> Dict[str, Any]:
        """Fork (copy) a dataset to a new name, useful for git worktrees."""
        try:
            # Check if source dataset exists
            source_metadata = self.db.execute(
                "SELECT * FROM dataset_metadata WHERE dataset_id = ?",
                (source_dataset,)
            ).fetchone()
            
            if not source_metadata:
                return {
                    "success": False,
                    "message": f"Source dataset '{source_dataset}' not found. Use list_datasets to see available datasets."
                }
            
            # Check if target dataset already exists
            target_exists = self.db.execute(
                "SELECT dataset_id FROM dataset_metadata WHERE dataset_id = ?",
                (target_dataset,)
            ).fetchone()
            
            if target_exists:
                return {
                    "success": False,
                    "message": f"Target dataset '{target_dataset}' already exists. Choose a different name or clear it first."
                }
            
            # Copy all files from source to target dataset
            files_copied = 0
            cursor = self.db.execute(
                """SELECT * FROM files WHERE dataset_id = ?""",
                (source_dataset,)
            )
            
            for row in cursor:
                self.db.execute("""
                    INSERT INTO files (
                        dataset_id, filepath, filename, overview, ddd_context,
                        functions, exports, imports, types_interfaces_classes,
                        constants, dependencies, other_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    target_dataset, row['filepath'], row['filename'],
                    row['overview'], row['ddd_context'], row['functions'],
                    row['exports'], row['imports'], row['types_interfaces_classes'],
                    row['constants'], row['dependencies'], row['other_notes']
                ))
                files_copied += 1
            
            # Create metadata entry for target dataset
            self.db.execute("""
                INSERT INTO dataset_metadata 
                (dataset_id, source_dir, files_count, loaded_at)
                VALUES (?, ?, ?, ?)
            """, (
                target_dataset,
                f"{source_metadata['source_dir']} (forked from {source_dataset})",
                files_copied,
                datetime.now()
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
            # Check if we're in a git repository
            git_dir = os.path.join(self.cwd, ".git")
            if not os.path.exists(git_dir):
                return {
                    "success": False,
                    "message": "Not in a git repository. Please run this from the root of your git project."
                }
            
            # Create .code-query directory
            code_query_dir = os.path.join(self.cwd, ".code-query")
            os.makedirs(code_query_dir, exist_ok=True)
            
            # Create configuration file
            config_path = os.path.join(code_query_dir, "config.json")
            config = {
                "datasetName": dataset_name,
                "mode": mode,
                "excludePatterns": ["*.test.js", "*.spec.ts", "node_modules/*", ".git/*"],
                "createdAt": datetime.now().isoformat()
            }
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Pre-commit hook content
            pre_commit_hook = """#!/bin/bash
# Code Query MCP Pre-commit Hook
# This hook queues changed files for documentation updates
# Supports git worktrees with separate datasets

CONFIG_FILE=".code-query/config.json"
QUEUE_FILE=".code-query/update_queue.txt"

# Function to get worktree-specific dataset name
get_dataset_name() {
    local base_dataset="$1"
    
    # Check if we're in a worktree
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    if [ -z "$GIT_DIR" ]; then
        echo "$base_dataset"
        return
    fi
    
    # Check if this is a worktree (not the main git dir)
    if [[ "$GIT_DIR" == *".git/worktrees/"* ]]; then
        # Extract worktree name from path
        WORKTREE_NAME=$(echo "$GIT_DIR" | sed 's/.*\\.git\\/worktrees\\/\\([^\\/]*\\).*/\\1/')
        echo "${base_dataset}-wt-${WORKTREE_NAME}"
    else
        echo "$base_dataset"
    fi
}

# Check if configuration exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Warning: Code Query configuration not found. Skipping documentation queue."
    exit 0
fi

# Get base dataset name from config
BASE_DATASET=$(jq -r '.datasetName' "$CONFIG_FILE" 2>/dev/null)
if [ -z "$BASE_DATASET" ] || [ "$BASE_DATASET" = "null" ]; then
    echo "Warning: Dataset name not found in configuration."
    exit 0
fi

# Get worktree-aware dataset name
DATASET_NAME=$(get_dataset_name "$BASE_DATASET")

# Show worktree info if applicable
if [ "$DATASET_NAME" != "$BASE_DATASET" ]; then
    echo "📌 Code Query: Using worktree dataset '$DATASET_NAME'"
fi

# Get staged files (Added, Copied, Modified, Deleted)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACMD)

if [ -z "$STAGED_FILES" ]; then
    # No relevant files staged
    exit 0
fi

# Create queue file if it doesn't exist
touch "$QUEUE_FILE"

# Append staged files to queue (avoid duplicates)
echo "$STAGED_FILES" | while IFS= read -r file; do
    if [ -n "$file" ] && ! grep -Fxq "$file" "$QUEUE_FILE"; then
        echo "$file" >> "$QUEUE_FILE"
    fi
done

# Count queued files
QUEUE_COUNT=$(wc -l < "$QUEUE_FILE" | tr -d ' ')

echo "📄 Code Query: $QUEUE_COUNT file(s) queued for documentation update."
echo "   Run '.code-query/git-doc-update' when ready to update documentation."

exit 0
"""
            
            # Git doc-update script content
            git_doc_update = """#!/bin/bash
# Code Query Documentation Update Script
# Supports git worktrees with separate datasets

CONFIG_FILE=".code-query/config.json"
QUEUE_FILE=".code-query/update_queue.txt"

# Helper functions
error_exit() {
    echo "Error: $1" >&2
    exit 1
}

# Function to get worktree-specific dataset name
get_dataset_name() {
    local base_dataset="$1"
    
    # Check if we're in a worktree
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    if [ -z "$GIT_DIR" ]; then
        echo "$base_dataset"
        return
    fi
    
    # Check if this is a worktree (not the main git dir)
    if [[ "$GIT_DIR" == *".git/worktrees/"* ]]; then
        # Extract worktree name from path
        WORKTREE_NAME=$(echo "$GIT_DIR" | sed 's/.*\\.git\\/worktrees\\/\\([^\\/]*\\).*/\\1/')
        echo "${base_dataset}-wt-${WORKTREE_NAME}"
    else
        echo "$base_dataset"
    fi
}

# Check dependencies
if ! command -v jq &> /dev/null; then
    error_exit "'jq' is not installed. Please install 'jq' to parse JSON configuration."
fi

if ! command -v claude &> /dev/null; then
    error_exit "'claude' CLI not found. Please ensure Claude Code is installed."
fi

# Check configuration
if [ ! -f "$CONFIG_FILE" ]; then
    error_exit "Configuration file not found. Run: claude --print \"Use code-query MCP to install pre-commit hook for dataset 'your-dataset-name'\""
fi

# Get base dataset name from config
BASE_DATASET=$(jq -r '.datasetName' "$CONFIG_FILE")
if [ -z "$BASE_DATASET" ] || [ "$BASE_DATASET" = "null" ]; then
    error_exit "Dataset name not found in configuration."
fi

# Get worktree-aware dataset name
DATASET_NAME=$(get_dataset_name "$BASE_DATASET")

# Show worktree info if applicable
if [ "$DATASET_NAME" != "$BASE_DATASET" ]; then
    echo "📌 Using worktree dataset: $DATASET_NAME"
    echo ""
    
    # Check if worktree dataset exists
    claude --print "Use code-query MCP to list datasets" 2>/dev/null | grep -q "\"$DATASET_NAME\""
    if [ $? -ne 0 ]; then
        echo "⚠️  Worktree dataset '$DATASET_NAME' not found."
        echo ""
        echo "Creating worktree dataset by forking from '$BASE_DATASET'..."
        claude --print "Use code-query MCP to fork dataset from '$BASE_DATASET' to '$DATASET_NAME'"
        if [ $? -ne 0 ]; then
            error_exit "Failed to create worktree dataset"
        fi
        echo "✅ Worktree dataset created successfully."
        echo ""
    fi
fi

# Check queue file
if [ ! -f "$QUEUE_FILE" ] || [ ! -s "$QUEUE_FILE" ]; then
    echo "No files queued for documentation update."
    exit 0
fi

# Read and deduplicate files
mapfile -t UNIQUE_FILES < <(sort -u "$QUEUE_FILE")
NUM_FILES=${#UNIQUE_FILES[@]}

if [ "$NUM_FILES" -eq 0 ]; then
    echo "No files queued after deduplication."
    > "$QUEUE_FILE"
    exit 0
fi

echo "Found $NUM_FILES file(s) queued for documentation update:"
printf "  - %s\\n" "${UNIQUE_FILES[@]}"
echo ""

# Estimate time
EST_TIME_MIN=$((NUM_FILES * 5 / 60))
EST_TIME_MAX=$((NUM_FILES * 30 / 60))
if [ "$EST_TIME_MIN" -eq 0 ]; then
    echo "Estimated time: ${NUM_FILES}0-$((NUM_FILES * 30)) seconds"
else
    echo "Estimated time: ${EST_TIME_MIN}-${EST_TIME_MAX} minutes"
fi

read -p "Proceed with documentation update? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Documentation update cancelled."
    exit 0
fi

echo ""
echo "Starting documentation update..."

# Build file list for Claude prompt
FILE_LIST=""
for file in "${UNIQUE_FILES[@]}"; do
    if [ -n "$FILE_LIST" ]; then
        FILE_LIST="$FILE_LIST, '$file'"
    else
        FILE_LIST="'$file'"
    fi
done

# Call Claude CLI
claude "Use the code-query MCP to update documentation for files $FILE_LIST in dataset '$DATASET_NAME'"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Documentation update completed successfully."
    > "$QUEUE_FILE"  # Clear the queue
else
    echo ""
    echo "❌ Documentation update failed. Files remain in queue."
    exit 1
fi
"""
            
            # Write pre-commit hook
            hook_path = os.path.join(git_dir, "hooks", "pre-commit")
            
            # Check if hook already exists
            if os.path.exists(hook_path):
                # Read existing hook to check if it's ours
                with open(hook_path, 'r') as f:
                    existing_content = f.read()
                    if "Code Query MCP Pre-commit Hook" not in existing_content:
                        return {
                            "success": False,
                            "message": "A pre-commit hook already exists. Please manually integrate or remove it first."
                        }
            
            # Write the hook
            with open(hook_path, 'w') as f:
                f.write(pre_commit_hook)
            
            # Make hook executable
            os.chmod(hook_path, 0o755)
            
            # Write git-doc-update script
            update_script_path = os.path.join(code_query_dir, "git-doc-update")
            with open(update_script_path, 'w') as f:
                f.write(git_doc_update)
            
            # Make update script executable
            os.chmod(update_script_path, 0o755)
            
            # Create .gitignore in .code-query if needed
            gitignore_path = os.path.join(code_query_dir, ".gitignore")
            if not os.path.exists(gitignore_path):
                with open(gitignore_path, 'w') as f:
                    f.write("update_queue.txt\n")
            
            return {
                "success": True,
                "message": f"Successfully installed pre-commit hook for dataset '{dataset_name}'",
                "details": {
                    "config_path": config_path,
                    "hook_path": hook_path,
                    "update_script": update_script_path,
                    "mode": mode
                },
                "next_steps": [
                    "The pre-commit hook will now queue changed files for documentation updates",
                    "Run '.code-query/git-doc-update' to process queued files",
                    "You can also create an alias: alias git-doc-update='.code-query/git-doc-update'"
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
            git_dir = os.path.join(self.cwd, ".git")
            if not os.path.exists(git_dir):
                return {
                    "success": False,
                    "message": "Not in a git repository. Please run this from the root of your git project."
                }
            
            # Read config to get main dataset name if not provided
            config_path = os.path.join(self.cwd, ".code-query", "config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    if not main_dataset:
                        main_dataset = config.get("datasetName")
            
            if not main_dataset:
                return {
                    "success": False,
                    "message": "Main dataset name not provided and not found in config. Please specify the main dataset name."
                }
            
            # Post-merge hook content
            post_merge_hook = f"""#!/bin/bash
# Code Query MCP Post-merge Hook
# This hook syncs changes from worktree datasets back to main dataset

CONFIG_FILE=".code-query/config.json"
MAIN_DATASET="{main_dataset}"

# Function to get worktree-specific dataset name
get_dataset_name() {{
    local base_dataset="$1"
    
    # Check if we're in a worktree
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    if [ -z "$GIT_DIR" ]; then
        echo "$base_dataset"
        return
    fi
    
    # Check if this is a worktree (not the main git dir)
    if [[ "$GIT_DIR" == *".git/worktrees/"* ]]; then
        # Extract worktree name from path
        WORKTREE_NAME=$(echo "$GIT_DIR" | sed 's/.*\\.git\\/worktrees\\/\\([^\\/]*\\).*/\\1/')
        echo "${{base_dataset}}-wt-${{WORKTREE_NAME}}"
    else
        echo "$base_dataset"
    fi
}}

# Check if configuration exists
if [ ! -f "$CONFIG_FILE" ]; then
    exit 0  # Silently exit if no config
fi

# Get base dataset name from config
BASE_DATASET=$(jq -r '.datasetName' "$CONFIG_FILE" 2>/dev/null)
if [ -z "$BASE_DATASET" ] || [ "$BASE_DATASET" = "null" ]; then
    exit 0  # Silently exit if no dataset name
fi

# Get worktree-aware dataset name
CURRENT_DATASET=$(get_dataset_name "$BASE_DATASET")

# Only proceed if we're in a worktree
if [ "$CURRENT_DATASET" = "$BASE_DATASET" ]; then
    exit 0  # Not in a worktree, nothing to sync
fi

# Check if we just merged from main branch
MERGED_FROM=$(git reflog -1 | grep -o "merge [^:]*" | cut -d' ' -f2)
if [[ "$MERGED_FROM" == *"main"* ]] || [[ "$MERGED_FROM" == *"master"* ]]; then
    echo "📄 Code Query: Detected merge from main branch"
    echo "   Syncing documentation from worktree dataset '$CURRENT_DATASET' to main dataset '$MAIN_DATASET'"
    
    # Get list of changed files in the merge
    CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD)
    
    if [ -n "$CHANGED_FILES" ]; then
        # Build file list for Claude
        FILE_LIST=""
        while IFS= read -r file; do
            if [ -n "$FILE_LIST" ]; then
                FILE_LIST="$FILE_LIST, '$file'"
            else
                FILE_LIST="'$file'"
            fi
        done <<< "$CHANGED_FILES"
        
        echo "   Files to sync: $FILE_LIST"
        echo ""
        
        # Use Claude to sync the files
        claude --print "Use code-query MCP to copy documentation for files $FILE_LIST from dataset '$CURRENT_DATASET' to dataset '$MAIN_DATASET'"
    fi
fi

exit 0
"""
            
            # Write post-merge hook
            hook_path = os.path.join(git_dir, "hooks", "post-merge")
            
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
    
    def recommend_setup(self, project_name: str = None, source_directory: str = None) -> Dict[str, Any]:
        """Recommend complete setup process for a new project."""
        try:
            # Check current state
            config_exists = os.path.exists(os.path.join(self.cwd, ".code-query", "config.json"))
            git_exists = os.path.exists(os.path.join(self.cwd, ".git"))
            
            # Check if any datasets exist
            existing_datasets = self.list_datasets()
            has_datasets = len(existing_datasets) > 0
            
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
                    "datasets": existing_datasets
                })
            
            # Step 2: Create configuration
            if not config_exists:
                setup_steps.append({
                    "step": 2,
                    "action": "Create project configuration",
                    "reason": "No .code-query/config.json found",
                    "command": f"create_project_config('{project_name}')"
                })
                recommended_commands.append(
                    f"Use code-query MCP to create project config for '{project_name}'"
                )
            
            # Step 3: Install git hooks
            if git_exists:
                pre_commit_exists = os.path.exists(os.path.join(self.cwd, ".git", "hooks", "pre-commit"))
                post_merge_exists = os.path.exists(os.path.join(self.cwd, ".git", "hooks", "post-merge"))
                
                if not pre_commit_exists:
                    setup_steps.append({
                        "step": 3,
                        "action": "Install pre-commit hook",
                        "reason": "Automatically queue changed files for documentation updates",
                        "command": f"install_pre_commit_hook('{project_name}')"
                    })
                    recommended_commands.append(
                        f"Use code-query MCP to install pre-commit hook for '{project_name}'"
                    )
                
                if not post_merge_exists:
                    setup_steps.append({
                        "step": 4,
                        "action": "Install post-merge hook",
                        "reason": "Sync documentation from git worktrees back to main",
                        "command": f"install_post_merge_hook('{project_name}')"
                    })
                    recommended_commands.append(
                        f"Use code-query MCP to install post-merge hook for '{project_name}'"
                    )
            
            # Build response
            response = {
                "success": True,
                "project_name": project_name,
                "source_directory": source_directory,
                "current_state": {
                    "config_exists": config_exists,
                    "git_repository": git_exists,
                    "has_datasets": has_datasets,
                    "dataset_count": len(existing_datasets)
                },
                "setup_needed": len(setup_steps) > 0,
                "setup_steps": setup_steps
            }
            
            if recommended_commands:
                response["recommendation"] = (
                    f"To complete the Code Query MCP setup for '{project_name}', "
                    f"I recommend running these {len(recommended_commands)} commands:\n\n" +
                    "\n".join(f"{i+1}. {cmd}" for i, cmd in enumerate(recommended_commands)) +
                    "\n\nWould you like me to run all these setup commands now?"
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


# Initialize server
server = Server("code-query")
query_server = CodeQueryServer()


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools."""
    return [
        Tool(
            name="import_data",
            description="Import JSON files from directory into named dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path containing JSON files"
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "Replace existing dataset if it exists",
                        "default": False
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="recommend_setup",
            description="Get setup recommendations for Code Query MCP. This analyzes your project and recommends the necessary setup steps including data import, configuration, and git hooks. Use this when starting with a new project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "Name for the project (auto-detected if not provided)"
                    },
                    "source_directory": {
                        "type": "string",
                        "description": "Directory to document (auto-detected if not provided)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="search_files",
            description="Search files in dataset by query string. Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to search in. Use list_datasets tool if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10
                    }
                },
                "required": ["query", "dataset_name"]
            }
        ),
        Tool(
            name="get_file",
            description="Get complete details for a specific file. Supports partial path matching (e.g., 'login.ts' finds 'src/auth/login.ts'). Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Full or partial path to the file. Use % for wildcards."
                    },
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use list_datasets tool if unknown."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results for partial matches",
                        "default": 10
                    }
                },
                "required": ["filepath", "dataset_name"]
            }
        ),
        Tool(
            name="list_domains",
            description="List all unique DDD context domains in dataset. Use list_datasets first if you don't know the dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to analyze. Use list_datasets tool if unknown."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="list_datasets",
            description="List all loaded datasets with their names, sources, and file counts. Use this when you need to discover available dataset names.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_status",
            description="Get current database status",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="clear_dataset",
            description="Clear a specific dataset. Use list_datasets to see available datasets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to clear. Use list_datasets tool to see available options."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="document_directory",
            description="Generate orchestration instructions for documenting a directory of code files",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Name for this dataset"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path to document"
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., '*.test.js', 'temp/*')"
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of files per agent batch",
                        "default": 20
                    }
                },
                "required": ["dataset_name", "directory"]
            }
        ),
        Tool(
            name="insert_file_documentation",
            description="Insert analyzed file documentation into dataset (used by agents)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset to insert into. Use list_datasets tool if unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path"
                    },
                    "filename": {
                        "type": "string",
                        "description": "File name"
                    },
                    "overview": {
                        "type": "string",
                        "description": "Brief file overview"
                    },
                    "functions": {
                        "type": "object",
                        "description": "Functions with their details"
                    },
                    "exports": {
                        "type": "object",
                        "description": "Exported items"
                    },
                    "imports": {
                        "type": "object",
                        "description": "Imported items"
                    },
                    "types_interfaces_classes": {
                        "type": "object",
                        "description": "Type definitions"
                    },
                    "constants": {
                        "type": "object",
                        "description": "Constant definitions"
                    },
                    "ddd_context": {
                        "type": "string",
                        "description": "DDD domain context"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "External dependencies"
                    },
                    "other_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional notes"
                    }
                },
                "required": ["dataset_name", "filepath", "filename", "overview"]
            }
        ),
        Tool(
            name="update_file_documentation",
            description="Update existing file documentation in dataset. Only updates provided fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset containing the file. Use list_datasets tool if unknown."
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Full file path to update"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Updated file name (optional)"
                    },
                    "overview": {
                        "type": "string",
                        "description": "Updated file overview (optional)"
                    },
                    "functions": {
                        "type": "object",
                        "description": "Updated functions (optional)"
                    },
                    "exports": {
                        "type": "object",
                        "description": "Updated exports (optional)"
                    },
                    "imports": {
                        "type": "object",
                        "description": "Updated imports (optional)"
                    },
                    "types_interfaces_classes": {
                        "type": "object",
                        "description": "Updated type definitions (optional)"
                    },
                    "constants": {
                        "type": "object",
                        "description": "Updated constants (optional)"
                    },
                    "ddd_context": {
                        "type": "string",
                        "description": "Updated DDD context (optional)"
                    },
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated dependencies (optional)"
                    },
                    "other_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Updated notes (optional)"
                    }
                },
                "required": ["dataset_name", "filepath"]
            }
        ),
        Tool(
            name="get_project_config",
            description="Get comprehensive project configuration including dataset status, git hooks, and setup completeness. This tool helps understand what setup steps have been completed and what remains to be done.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="install_pre_commit_hook",
            description="Install pre-commit hook for automatic documentation update queuing",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset name to use for this project"
                    },
                    "mode": {
                        "type": "string",
                        "description": "Hook mode: 'queue' (default) queues files for manual update",
                        "enum": ["queue"],
                        "default": "queue"
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="create_project_config",
            description="Create or update code-query project configuration file (.code-query/config.json)",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_name": {
                        "type": "string",
                        "description": "Dataset name for this project"
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Patterns to exclude (e.g., '*.test.js', 'node_modules/*'). Defaults to common exclusions if not provided."
                    }
                },
                "required": ["dataset_name"]
            }
        ),
        Tool(
            name="fork_dataset",
            description="Fork (copy) a dataset to a new name. Useful for git worktrees where you want to work on the same codebase with different branches. Use list_datasets first if you don't know the source dataset name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_dataset": {
                        "type": "string",
                        "description": "Source dataset to copy from. Use list_datasets tool if unknown."
                    },
                    "target_dataset": {
                        "type": "string",
                        "description": "New dataset name to create"
                    }
                },
                "required": ["source_dataset", "target_dataset"]
            }
        ),
        Tool(
            name="install_post_merge_hook",
            description="Install post-merge hook for syncing worktree changes back to main dataset",
            inputSchema={
                "type": "object",
                "properties": {
                    "main_dataset": {
                        "type": "string",
                        "description": "Main dataset name to sync to (defaults to config datasetName)"
                    }
                },
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    if name == "import_data":
        dataset_name = arguments.get("dataset_name", "")
        directory = arguments.get("directory", "")
        replace = arguments.get("replace", False)
        result = query_server.import_data(dataset_name, directory, replace)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "recommend_setup":
        project_name = arguments.get("project_name")
        source_directory = arguments.get("source_directory")
        result = query_server.recommend_setup(project_name, source_directory)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "search_files":
        query = arguments.get("query", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        results = query_server.search_files(query, dataset_name, limit)
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    
    elif name == "get_file":
        filepath = arguments.get("filepath", "")
        dataset_name = arguments.get("dataset_name", "")
        limit = arguments.get("limit", 10)
        result = query_server.get_file(filepath, dataset_name, limit)
        if result:
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({"error": "File not found"}))]
    
    elif name == "list_domains":
        dataset_name = arguments.get("dataset_name", "")
        domains = query_server.list_domains(dataset_name)
        return [TextContent(type="text", text=json.dumps(domains, indent=2))]
    
    elif name == "list_datasets":
        datasets = query_server.list_datasets()
        return [TextContent(type="text", text=json.dumps(datasets, indent=2))]
    
    elif name == "get_status":
        status = query_server.get_status()
        return [TextContent(type="text", text=json.dumps(status, indent=2))]
    
    elif name == "clear_dataset":
        dataset_name = arguments.get("dataset_name", "")
        result = query_server.clear_dataset(dataset_name)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "document_directory":
        dataset_name = arguments.get("dataset_name", "")
        directory = arguments.get("directory", "")
        exclude_patterns = arguments.get("exclude_patterns", [])
        batch_size = arguments.get("batch_size", 20)
        result = query_server.document_directory(dataset_name, directory, exclude_patterns, batch_size)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "insert_file_documentation":
        dataset_name = arguments.get("dataset_name", "")
        filepath = arguments.get("filepath", "")
        filename = arguments.get("filename", "")
        overview = arguments.get("overview", "")
        functions = arguments.get("functions", {})
        exports = arguments.get("exports", {})
        imports = arguments.get("imports", {})
        types_interfaces_classes = arguments.get("types_interfaces_classes", {})
        constants = arguments.get("constants", {})
        ddd_context = arguments.get("ddd_context", "")
        dependencies = arguments.get("dependencies", [])
        other_notes = arguments.get("other_notes", [])
        
        result = query_server.insert_file_documentation(
            dataset_name, filepath, filename, overview,
            functions, exports, imports, types_interfaces_classes,
            constants, ddd_context, dependencies, other_notes
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "update_file_documentation":
        dataset_name = arguments.get("dataset_name", "")
        filepath = arguments.get("filepath", "")
        filename = arguments.get("filename")
        overview = arguments.get("overview")
        functions = arguments.get("functions")
        exports = arguments.get("exports")
        imports = arguments.get("imports")
        types_interfaces_classes = arguments.get("types_interfaces_classes")
        constants = arguments.get("constants")
        ddd_context = arguments.get("ddd_context")
        dependencies = arguments.get("dependencies")
        other_notes = arguments.get("other_notes")
        
        result = query_server.update_file_documentation(
            dataset_name, filepath, filename, overview,
            functions, exports, imports, types_interfaces_classes,
            constants, ddd_context, dependencies, other_notes
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "get_project_config":
        result = query_server.get_project_config()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_pre_commit_hook":
        dataset_name = arguments.get("dataset_name", "")
        mode = arguments.get("mode", "queue")
        result = query_server.install_pre_commit_hook(dataset_name, mode)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "create_project_config":
        dataset_name = arguments.get("dataset_name", "")
        exclude_patterns = arguments.get("exclude_patterns")
        result = query_server.create_project_config(dataset_name, exclude_patterns)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "fork_dataset":
        source_dataset = arguments.get("source_dataset", "")
        target_dataset = arguments.get("target_dataset", "")
        result = query_server.fork_dataset(source_dataset, target_dataset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "install_post_merge_hook":
        main_dataset = arguments.get("main_dataset")
        result = query_server.install_post_merge_hook(main_dataset)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Main entry point."""
    # Setup database connection (but don't load data)
    query_server.setup_database()
    
    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="code-query",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())