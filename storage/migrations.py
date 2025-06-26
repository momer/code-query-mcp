"""Database migration logic for Code Query MCP Server."""

import logging
import sqlite3
from typing import Optional


class SchemaMigrator:
    """Handles database schema migrations."""
    
    def __init__(self, db_connection: sqlite3.Connection):
        self.db = db_connection
    
    def migrate_to_current_version(self):
        """Migrate schema to current version."""
        # Create schema_version table if it doesn't exist
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Check if dataset_id column exists (legacy migration)
        cursor = self.db.execute("PRAGMA table_info(files)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'dataset_id' not in columns:
            self._migrate_legacy_to_datasets()
        
        # Ensure dataset_metadata table exists
        self._ensure_dataset_metadata_table()
        
        # Add dataset_type column if missing
        self._add_dataset_type_column()
        
        # Migrate to v1.0.0 if needed (commit tracking support)
        cursor = self.db.execute("SELECT version FROM schema_version WHERE version = '1.0.0'")
        if not cursor.fetchone():
            self._migrate_to_v1_0_0()
        
        # Migrate to v1.1.0 if needed (full-content support)
        cursor = self.db.execute("SELECT version FROM schema_version WHERE version = '1.1.0'")
        if not cursor.fetchone():
            self._migrate_to_v1_1_0()
    
    def _migrate_legacy_to_datasets(self):
        """Migrate from legacy schema to dataset-based schema."""
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
            # Drop and recreate FTS - will be handled by parent class
            self.db.execute("DROP TABLE files_fts")
        
        self.db.commit()
        logging.info("Schema migration completed")
    
    def _ensure_dataset_metadata_table(self):
        """Ensure dataset_metadata table exists with current schema."""
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
                    loaded_at TIMESTAMP,
                    dataset_type TEXT DEFAULT 'main',
                    parent_dataset_id TEXT,
                    source_branch TEXT,
                    FOREIGN KEY(parent_dataset_id) REFERENCES dataset_metadata(dataset_id) ON DELETE SET NULL
                )
            """)
            self.db.commit()
    
    def _add_dataset_type_column(self):
        """Add dataset_type column to dataset_metadata if missing."""
        cursor = self.db.execute("PRAGMA table_info(dataset_metadata)")
        metadata_columns = [col[1] for col in cursor.fetchall()]
        
        if 'dataset_type' not in metadata_columns:
            logging.info("Adding dataset_type column to dataset_metadata table...")
            try:
                self.db.execute("""
                    ALTER TABLE dataset_metadata 
                    ADD COLUMN dataset_type TEXT DEFAULT 'main'
                """)
                
                self.db.execute("""
                    ALTER TABLE dataset_metadata 
                    ADD COLUMN parent_dataset_id TEXT
                """)
                
                self.db.execute("""
                    ALTER TABLE dataset_metadata 
                    ADD COLUMN source_branch TEXT
                """)
                
                self.db.commit()
                logging.info("Successfully added dataset_type column")
            except sqlite3.OperationalError as e:
                logging.warning(f"Could not add dataset_type column: {e}")
    
    def _migrate_to_v1_0_0(self):
        """Migrate to schema v1.0.0 with commit tracking."""
        logging.info("Migrating to schema v1.0.0...")
        
        # Check if commit tracking columns exist
        cursor = self.db.execute("PRAGMA table_info(files)")
        file_columns = [col[1] for col in cursor.fetchall()]
        
        if 'documented_at_commit' not in file_columns:
            logging.info("Adding commit tracking columns...")
            
            # Create new table with v1.0.0 schema
            self.db.execute("""
                CREATE TABLE files_v1 (
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
                    PRIMARY KEY (dataset_id, filepath)
                )
            """)
            
            # Copy existing data with current timestamp for documented_at
            self.db.execute("""
                INSERT INTO files_v1 (
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, documented_at_commit,
                    documented_at
                )
                SELECT 
                    dataset_id, filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, NULL,
                    CURRENT_TIMESTAMP
                FROM files
            """)
            
            # Drop old table and rename new one
            self.db.execute("DROP TABLE files")
            self.db.execute("ALTER TABLE files_v1 RENAME TO files")
            
            # Recreate index
            self.db.execute("""
                CREATE INDEX idx_dataset_filepath ON files(dataset_id, filepath)
            """)
            
            # Note: FTS table recreation should be handled by parent class
        
        # Mark v1.0.0 as applied
        self.db.execute("""
            INSERT OR REPLACE INTO schema_version (version) VALUES ('1.0.0')
        """)
        
        self.db.commit()
        logging.info("Successfully migrated to schema v1.0.0")
    
    def _migrate_to_v1_1_0(self):
        """Migrate to schema v1.1.0 with full-content support."""
        logging.info("Migrating to schema v1.1.0...")
        
        # Check if full_content column exists
        cursor = self.db.execute("PRAGMA table_info(files)")
        file_columns = [col[1] for col in cursor.fetchall()]
        
        if 'full_content' not in file_columns:
            logging.info("Adding full_content column...")
            
            try:
                # Add full_content column to files table
                self.db.execute("""
                    ALTER TABLE files 
                    ADD COLUMN full_content TEXT
                """)
                
                # Drop existing FTS table to recreate with full_content
                cursor = self.db.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='files_fts'
                """)
                if cursor.fetchone():
                    logging.info("Dropping existing FTS table to add full_content support...")
                    self.db.execute("DROP TABLE files_fts")
                
                self.db.commit()
                logging.info("Successfully added full_content column")
                
            except sqlite3.OperationalError as e:
                logging.error(f"Could not add full_content column: {e}")
                raise
        
        # Mark v1.1.0 as applied
        self.db.execute("""
            INSERT OR REPLACE INTO schema_version (version) VALUES ('1.1.0')
        """)
        
        self.db.commit()
        logging.info("Successfully migrated to schema v1.1.0")