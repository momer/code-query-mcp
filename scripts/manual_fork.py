#!/usr/bin/env python3
"""Manually fork a dataset for a worktree."""

import sys
import os

# Add the script's directory to Python path so it can find the modules
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from storage.sqlite_storage import CodeQueryServer
from helpers.git_helper import get_git_info

def main():
    if len(sys.argv) != 4:
        print("Usage: python manual_fork.py <project_path> <source_dataset> <target_dataset>")
        print("Example: python manual_fork.py /path/to/main/worktree acorn_files acorn_files_feat_wire_up_device_connection")
        sys.exit(1)
    
    project_path = sys.argv[1]
    source_dataset = sys.argv[2]
    target_dataset = sys.argv[3]
    
    # Get git info from the specified project path
    git_info = get_git_info(project_path)
    
    if git_info:
        DB_DIR = os.path.join(git_info["toplevel_path"], ".mcp_code_query")
        DB_PATH = os.path.join(DB_DIR, "code_data.db")
        print(f"Using database at: {DB_PATH}")
    else:
        print(f"Not a git repository: {project_path}")
        sys.exit(1)
    
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        sys.exit(1)
    
    # Initialize query server
    query_server = CodeQueryServer(DB_PATH, DB_DIR)
    query_server.setup_database()
    
    print(f"\nForking dataset:")
    print(f"  Source: {source_dataset}")
    print(f"  Target: {target_dataset}")
    
    # Perform the fork
    result = query_server.fork_dataset(source_dataset, target_dataset)
    
    if result['success']:
        print(f"\nSuccess! Forked {result.get('files_copied', 0)} files")
        print(f"Message: {result.get('message', 'Fork completed')}")
    else:
        print(f"\nFailed to fork dataset:")
        print(f"  Error: {result.get('message', 'Unknown error')}")

if __name__ == "__main__":
    main()