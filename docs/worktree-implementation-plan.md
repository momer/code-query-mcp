# Git Worktree Dataset Isolation - Complete Implementation Plan

## Overview
This document contains the complete implementation plan for git worktree dataset isolation in code-query-mcp, including completed work and remaining tasks.

## Completed Implementation

### 1. Core Worktree Detection (✓ Completed)
**File: `helpers/git_helper.py`**
- `is_worktree()`: Checks if current directory is a linked worktree
- `get_main_worktree_path()`: Gets path to main worktree using `git rev-parse --path-format=absolute --git-common-dir`
- `get_worktree_info()`: Returns comprehensive worktree information

### 2. Auto-forking in Server (✓ Completed)
**File: `server.py`**
- Detects worktree on startup
- Reads main config to get `mainDatasetName`
- Auto-forks dataset with naming: `{main_dataset}__wt_{sanitized_branch}`
- Falls back gracefully on errors

### 3. Config Schema Update (✓ Completed)
**File: `storage/sqlite_storage.py`**
- Updated to use `mainDatasetName` instead of `datasetName`
- Version bumped to 1.1.0
- Backward compatible with old schema

## Remaining Implementation Tasks

### 1. Sync Dataset Tool (Priority: High)

**Rationale**: Replace fragile git hook that relies on `claude --print` with explicit, reliable tool.

**Benefits of dataset_type column over __wt_ naming**:
- Clean separation of data and metadata
- More flexible (can add other dataset types later)
- Easier queries (WHERE dataset_type = 'worktree' vs LIKE '%__wt_%')
- Better database design principles

**Implementation Details**:

#### Add to `tools/mcp_tools.py`:
```python
Tool(
    name="sync_dataset",
    description="Syncs documentation changes from a source dataset (e.g., feature branch) to a target dataset (e.g., main). Use after merging branches.",
    inputSchema={
        "type": "object",
        "properties": {
            "source_dataset": {
                "type": "string",
                "description": "The dataset to sync changes from (e.g., 'project__wt_feature_branch')"
            },
            "target_dataset": {
                "type": "string", 
                "description": "The dataset to sync changes to (e.g., 'project_main')"
            },
            "source_ref": {
                "type": "string",
                "description": "Git ref (branch/commit) for source dataset"
            },
            "target_ref": {
                "type": "string",
                "description": "Git ref (branch/commit) for target dataset"
            }
        },
        "required": ["source_dataset", "target_dataset", "source_ref", "target_ref"]
    }
)
```

#### Add to `storage/sqlite_storage.py`:
```python
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
```

#### Add to `server.py` call_tool():
```python
elif name == "sync_dataset":
    source_dataset = arguments.get("source_dataset", "")
    target_dataset = arguments.get("target_dataset", "")
    source_ref = arguments.get("source_ref", "")
    target_ref = arguments.get("target_ref", "")
    result = query_server.sync_dataset(source_dataset, target_dataset, source_ref, target_ref)
    return [TextContent(type="text", text=json.dumps(result, indent=2))]
```

**User Workflow**:
1. `git checkout main`
2. `git merge feature/new-ui`
3. Use MCP tool: `sync_dataset('project__wt_feature_new_ui', 'project_main', 'feature/new-ui', 'main')`

### 2. Enhanced Dataset Metadata Schema (Priority: High)

**Rationale**: Track parent-child relationships explicitly for robust cleanup.

#### Update `storage/sqlite_storage.py` setup_database():
```sql
CREATE TABLE IF NOT EXISTS dataset_metadata (
    dataset_id TEXT PRIMARY KEY,
    source_dir TEXT,
    files_count INTEGER,
    loaded_at TIMESTAMP,
    -- New columns for worktree tracking
    parent_dataset_id TEXT,
    source_branch TEXT,
    FOREIGN KEY(parent_dataset_id) REFERENCES dataset_metadata(dataset_id) ON DELETE SET NULL
);
```

#### Update fork_dataset() to populate new fields:
```python
# In fork_dataset(), after creating the new dataset:
if is_worktree_dataset:  # Detect by naming convention or parameter
    branch_name = get_current_branch()  # Helper to get branch name
    self.db.execute("""
        UPDATE dataset_metadata 
        SET parent_dataset_id = ?, source_branch = ?
        WHERE dataset_id = ?
    """, (source_dataset, branch_name, target_dataset))
```

### 3. Cleanup Orphaned Datasets Tool (Priority: Medium)

**Rationale**: Remove datasets for deleted branches/worktrees to save space and reduce clutter.

#### Add to `tools/mcp_tools.py`:
```python
Tool(
    name="cleanup_datasets",
    description="Find and optionally remove orphaned datasets whose git branches no longer exist",
    inputSchema={
        "type": "object",
        "properties": {
            "dry_run": {
                "type": "boolean",
                "description": "If true, only list orphans without deleting. Defaults to true for safety.",
                "default": True
            }
        }
    }
)
```

#### Add to `storage/sqlite_storage.py`:
```python
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
```

#### Add to `server.py` call_tool():
```python
elif name == "cleanup_datasets":
    dry_run = arguments.get("dry_run", True)
    result = query_server.cleanup_datasets(dry_run)
    return [TextContent(type="text", text=json.dumps(result, indent=2))]
```

### 4. Testing Strategy (Priority: Medium)

#### Unit Tests Structure:
```
tests/
├── unit/
│   ├── test_git_helper.py      # Mock subprocess calls
│   ├── test_sqlite_storage.py   # In-memory DB tests
│   └── test_sync_dataset.py     # Mock git diff
└── integration/
    ├── conftest.py              # Git repo fixtures
    └── test_worktree_lifecycle.py
```

#### Key Test Scenarios:
1. **Worktree Detection**:
   - Main worktree returns is_worktree=False
   - Linked worktree returns is_worktree=True
   - Non-git directory handled gracefully

2. **Auto-forking**:
   - First access creates fork
   - Subsequent access uses existing
   - Handles special characters in branch names
   - Falls back on fork failure

3. **Sync Operation**:
   - Correctly identifies changed files
   - Syncs only modified files
   - Transaction rollback on error
   - Handles file deletions

4. **Cleanup**:
   - Identifies orphaned datasets correctly
   - dry_run doesn't delete
   - Handles both metadata and pattern detection
   - Transactional deletion

#### Integration Test Example:
```python
def test_full_worktree_lifecycle(git_repo_fixture):
    """Test complete workflow from worktree creation to cleanup."""
    # 1. Setup main dataset
    server = CodeQueryServer(db_path, db_dir)
    server.setup_database()
    server.create_project_config("test_project")
    
    # 2. Create worktree
    subprocess.run(["git", "worktree", "add", "../feature", "-b", "feature/test"])
    
    # 3. Simulate server startup in worktree (auto-fork)
    # ... test auto-fork logic ...
    
    # 4. Make changes and sync
    # ... test sync_dataset ...
    
    # 5. Remove worktree and cleanup
    subprocess.run(["git", "worktree", "remove", "../feature"])
    result = server.cleanup_datasets(dry_run=False)
    assert "test_project__wt_feature_test" in result["deleted"]
```

## Migration Considerations

1. **Existing Configs**: Support both old `datasetName` and new `mainDatasetName`
2. **Existing Datasets**: Pattern-based detection for cleanup tool
3. **Git Hooks**: Remove old hooks that use `claude --print`

## Security Considerations

1. **SQL Injection**: Use parameterized queries (already implemented)
2. **Path Traversal**: Validate file paths from git diff
3. **Transaction Safety**: All multi-row operations in transactions

## Performance Notes

1. **Fork Operation**: Copies all rows - consider progress reporting for large datasets
2. **Sync Operation**: Only processes changed files - should be fast
3. **Cleanup**: Queries all datasets - consider pagination for large installations

## User Documentation Needed

1. **Worktree Workflow Guide**: How to use worktrees with code-query
2. **Sync Command Examples**: When and how to sync datasets
3. **Cleanup Best Practices**: When to run cleanup, understanding dry_run

## Future Enhancements (Not in current scope)

1. **Automatic Sync**: Optional post-merge hook using Python script
2. **Partial Fork**: Copy-on-write approach for large datasets
3. **Conflict Resolution**: Three-way merge for documentation
4. **Progress Reporting**: For long-running operations
5. **GitPython Migration**: If subprocess becomes limiting