#!/usr/bin/env python3
"""Standalone script to check dataset contents in a Code Query MCP database."""

import sqlite3
import json
import sys
import os

def main():
    if len(sys.argv) != 2:
        print("Usage: python check_db.py <path_to_code_data.db>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    print(f"Checking database: {db_path}")
    print("=" * 60)
    
    # List all datasets
    cursor = conn.execute("""
        SELECT d.dataset_id as name, d.source_dir, d.files_count, d.loaded_at,
               COUNT(f.filepath) as current_files
        FROM dataset_metadata d
        LEFT JOIN files f ON d.dataset_id = f.dataset_id
        GROUP BY d.dataset_id, d.source_dir, d.files_count, d.loaded_at
        ORDER BY d.loaded_at DESC
    """)
    
    datasets = cursor.fetchall()
    
    if not datasets:
        print("No datasets found.")
        return
    
    print(f"Found {len(datasets)} dataset(s):")
    print()
    
    for dataset in datasets:
        print(f"Dataset: {dataset['name']}")
        print(f"  Source: {dataset['source_dir']}")
        print(f"  Files: {dataset['current_files']}")
        print(f"  Loaded: {dataset['loaded_at']}")
        
        # Check if specific dataset has any files
        if dataset['name'] == 'acorn_files_feat_wire_up_device_connection':
            print(f"  Checking files in dataset '{dataset['name']}'...")
            file_cursor = conn.execute("""
                SELECT filepath, filename, overview 
                FROM files 
                WHERE dataset_id = ? 
                LIMIT 5
            """, (dataset['name'],))
            
            files = file_cursor.fetchall()
            if files:
                print(f"  Sample files:")
                for file in files:
                    print(f"    - {file['filepath']}")
            else:
                print(f"  No files found in this dataset!")
        
        print()
    
    # Test the specific query that's failing
    test_dataset = 'acorn_files_feat_wire_up_device_connection'
    print(f"Testing search for 'protocol' in dataset '{test_dataset}':")
    
    search_cursor = conn.execute("""
        SELECT filepath, filename, overview, ddd_context
        FROM files 
        WHERE dataset_id = ? 
        AND (filename LIKE ? OR overview LIKE ? OR ddd_context LIKE ?)
        LIMIT 5
    """, (test_dataset, '%protocol%', '%protocol%', '%protocol%'))
    
    results = search_cursor.fetchall()
    
    if results:
        print(f"Found {len(results)} result(s):")
        for result in results:
            print(f"  - {result['filepath']}")
    else:
        print("No results found for 'protocol' query.")
    
    conn.close()

if __name__ == "__main__":
    main()