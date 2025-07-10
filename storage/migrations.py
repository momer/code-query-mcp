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
        
        # Fix schema_version table if it has wrong column type (legacy)
        cursor = self.db.execute("PRAGMA table_info(schema_version)")
        columns = {col[1]: col[2] for col in cursor.fetchall()}
        
        if columns.get('version') == 'INTEGER':
            logging.info("Migrating schema_version table to use TEXT version...")
            # Create new schema_version table with correct schema
            self.db.execute("""
                CREATE TABLE schema_version_new (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Note: We'll ignore old integer versions and start fresh with text versions
            self.db.execute("DROP TABLE schema_version")
            self.db.execute("ALTER TABLE schema_version_new RENAME TO schema_version")
            self.db.commit()
        
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
        
        # Migrate to v3 if needed (code-aware tokenizer)
        cursor = self.db.execute("SELECT version FROM schema_version WHERE version = '3'")
        if not cursor.fetchone():
            self._migrate_to_v3_tokenizer()
    
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
            
            # Drop temporary table if it exists from previous failed migration
            self.db.execute("DROP TABLE IF EXISTS files_v1")
            
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
    
    def _migrate_to_v3_tokenizer(self):
        """Add code-aware tokenizer configuration using a safe migration pattern."""
        logging.info("Migrating to schema version 3: Code-aware tokenizer")
        
        temp_table_name = "files_fts_temp_v3"

        try:
            # Clean up any leftover temp tables from failed migrations
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name LIKE 'files_fts_temp_v3%'
            """)
            temp_tables = [row[0] for row in cursor.fetchall()]
            for table in temp_tables:
                logging.info(f"Cleaning up leftover temp table: {table}")
                self.db.execute(f"DROP TABLE IF EXISTS {table}")
            
            # Check if FTS table exists first
            cursor = self.db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='files_fts'
            """)
            fts_exists = cursor.fetchone() is not None
            
            if not fts_exists:
                logging.info("No existing FTS table found, skipping tokenizer migration")
                # Just mark the migration as complete since there's no FTS table to update
                self.db.execute("INSERT OR REPLACE INTO schema_version (version) VALUES ('3')")
                self.db.commit()
                return
            
            logging.info(f"Creating new FTS table '{temp_table_name}' with updated tokenizer.")
            # Step 1: Create the new table with a temporary name
            self.db.execute(f"""
                CREATE VIRTUAL TABLE {temp_table_name} USING fts5(
                    dataset_id UNINDEXED,
                    filepath, filename, overview, ddd_context,
                    functions, exports, imports, types_interfaces_classes,
                    constants, dependencies, other_notes, full_content,
                    content='files',
                    content_rowid='rowid',
                    tokenize = 'unicode61 tokenchars ''._$@->:#'''
                )
            """)

            logging.info(f"Rebuilding index for '{temp_table_name}'. This may take some time...")
            # Step 2: Populate the new table
            self.db.execute(f"INSERT INTO {temp_table_name}({temp_table_name}) VALUES('rebuild')")
            
            # Step 3: Atomically swap the tables - disable triggers first
            logging.info("Swapping old FTS table with the new one.")
            
            # Disable FTS triggers temporarily
            self.db.execute("DROP TRIGGER IF EXISTS files_ai")
            self.db.execute("DROP TRIGGER IF EXISTS files_ad")
            self.db.execute("DROP TRIGGER IF EXISTS files_au")
            
            # Drop old FTS table
            self.db.execute("DROP TABLE files_fts")
            
            # Rename new table
            self.db.execute(f"ALTER TABLE {temp_table_name} RENAME TO files_fts")
            
            # Recreate triggers to keep FTS table in sync with the files table
            logging.info("Recreating FTS triggers...")
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

            # Step 4: Finalize the migration
            self.db.execute("INSERT OR REPLACE INTO schema_version (version) VALUES ('3')")
            self.db.commit()
            logging.info("Schema migration to version 3 complete.")

        except Exception as e:
            # Use exc_info=True to log the full traceback
            logging.error(f"Migration to v3 failed: {e}.", exc_info=True)
            # Attempt to clean up the temporary table
            try:
                self.db.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
            except:
                pass
            # Re-raise the exception to halt the application startup and signal failure
            raise