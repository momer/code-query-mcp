#!/usr/bin/env python3
"""Diagnose worktree dataset setup issues."""

import sqlite3
import json
import sys
import os

# Add the script's directory to Python path so it can find the modules
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from helpers.git_helper import get_worktree_info, get_git_info

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_worktree.py <project_path> [db_path]")
        sys.exit(1)
    
    project_path = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Get worktree info
    wt_info = get_worktree_info(project_path)
    git_info = get_git_info(project_path)
    
    print(f"Diagnosing project: {project_path}")
    print("=" * 60)
    
    if not git_info:
        print("ERROR: Not a git repository")
        return
    
    print("Git Info:")
    print(f"  Top-level path: {git_info['toplevel_path']}")
    print(f"  Branch: {git_info['branch_name']}")
    print(f"  Sanitized branch: {git_info['sanitized_branch_name']}")
    print()
    
    if wt_info:
        print("Worktree Info:")
        print(f"  Is worktree: {wt_info['is_worktree']}")
        print(f"  Main path: {wt_info['main_path']}")
        print(f"  Current path: {wt_info['current_path']}")
        print(f"  Branch: {wt_info['branch']}")
        print()
    
    # Check for config file
    config_path = os.path.join(project_path, ".code-query", "config.json")
    if os.path.exists(config_path):
        print("Config file found:")
        with open(config_path, 'r') as f:
            config = json.load(f)
        print(f"  Main dataset name: {config.get('mainDatasetName')}")
        print(f"  Worktree info: {config.get('worktreeInfo', 'None')}")
        print()
    else:
        print("No config file found at:", config_path)
        print()
    
    # If database path provided, check datasets
    if not db_path:
        # Try to find database
        db_path = os.path.join(git_info['toplevel_path'], ".mcp_code_query", "code_data.db")
    
    if os.path.exists(db_path):
        print(f"Checking database: {db_path}")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # List all datasets
        cursor = conn.execute("""
            SELECT dataset_id, source_dir, files_count, loaded_at
            FROM dataset_metadata
            ORDER BY loaded_at DESC
        """)
        
        datasets = cursor.fetchall()
        print(f"\nFound {len(datasets)} dataset(s):")
        
        for ds in datasets:
            print(f"  - {ds['dataset_id']}")
            print(f"    Source: {ds['source_dir']}")
            print(f"    Files: {ds['files_count']}")
            print(f"    Loaded: {ds['loaded_at']}")
        
        # Check for expected worktree dataset
        if wt_info and wt_info['is_worktree'] and config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            expected_dataset = config.get('mainDatasetName')
            
            if expected_dataset:
                print(f"\nChecking for expected dataset: {expected_dataset}")
                cursor = conn.execute("""
                    SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
                """, (expected_dataset,))
                count = cursor.fetchone()['count']
                print(f"  Files in dataset: {count}")
                
                # Check if it looks like a worktree dataset name
                # With new naming convention, base dataset is everything before last underscore
                if "_" in expected_dataset and expected_dataset.count("_") > 0:
                    base_dataset = expected_dataset.rsplit("_", 1)[0]
                    print(f"\nChecking base dataset: {base_dataset}")
                    cursor = conn.execute("""
                        SELECT COUNT(*) as count FROM files WHERE dataset_id = ?
                    """, (base_dataset,))
                    count = cursor.fetchone()['count']
                    print(f"  Files in base dataset: {count}")
        
        conn.close()
    else:
        print(f"Database not found at: {db_path}")

if __name__ == "__main__":
    main()