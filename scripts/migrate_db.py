#!/usr/bin/env python3
"""Migrate database schema to support worktree features."""

import sqlite3
import sys
import os

def migrate_database(db_path):
    """Add missing columns to dataset_metadata table."""
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Check current schema
        cursor = conn.execute("PRAGMA table_info(dataset_metadata)")
        columns = [col[1] for col in cursor.fetchall()]
        
        print(f"Current columns in dataset_metadata: {columns}")
        
        # Add missing columns
        if 'dataset_type' not in columns:
            print("Adding dataset_type column...")
            conn.execute("ALTER TABLE dataset_metadata ADD COLUMN dataset_type TEXT DEFAULT 'main'")
            print("  ✓ Added dataset_type")
        
        if 'parent_dataset_id' not in columns:
            print("Adding parent_dataset_id column...")
            conn.execute("ALTER TABLE dataset_metadata ADD COLUMN parent_dataset_id TEXT")
            print("  ✓ Added parent_dataset_id")
        
        if 'source_branch' not in columns:
            print("Adding source_branch column...")
            conn.execute("ALTER TABLE dataset_metadata ADD COLUMN source_branch TEXT")
            print("  ✓ Added source_branch")
        
        conn.commit()
        print("\nMigration completed successfully!")
        
        # Verify the changes
        cursor = conn.execute("PRAGMA table_info(dataset_metadata)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Updated columns: {columns}")
        
        return True
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def main():
    if len(sys.argv) != 2:
        print("Usage: python migrate_db.py <path_to_code_data.db>")
        print("Example: python migrate_db.py /path/to/.mcp_code_query/code_data.db")
        sys.exit(1)
    
    db_path = sys.argv[1]
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()