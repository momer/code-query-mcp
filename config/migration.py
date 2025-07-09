"""Configuration migration utilities."""

import json
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from .project_config import ProjectConfig, ConfigVersion, GitHookConfig, HookType


def migrate_legacy_config(base_path: Path) -> Optional[ProjectConfig]:
    """
    Migrate legacy .code-query/config.json to new format.
    
    Args:
        base_path: Base directory to check for legacy config
        
    Returns:
        Migrated ProjectConfig or None if no legacy config exists
    """
    # Check for legacy config file
    legacy_config_path = base_path / ".code-query" / "config.json"
    if not legacy_config_path.exists():
        return None
        
    try:
        with open(legacy_config_path, 'r') as f:
            legacy_data = json.load(f)
    except Exception as e:
        logging.error(f"Failed to read legacy config at {legacy_config_path}: {e}")
        return None
        
    # Extract data from legacy format
    dataset_name = legacy_data.get("mainDatasetName") or legacy_data.get("datasetName", "default")
    project_name = dataset_name.split("_")[0] if "_" in dataset_name else dataset_name
    
    # Create new config
    now = datetime.now()
    config = ProjectConfig(
        project_name=project_name,
        version=ConfigVersion.V1,
        created_at=datetime.fromisoformat(legacy_data.get("createdAt", now.isoformat())),
        updated_at=now,
        default_dataset=dataset_name,
        ignored_patterns=legacy_data.get("excludePatterns", []),
        file_extensions=[],  # Legacy didn't have this
        max_file_size_mb=10,  # Default
        enable_analytics=True,  # Default
        analytics_retention_days=90,  # Default
        git_hooks=[]  # Will be populated based on actual hook files
    )
    
    # Check for worktree info
    if "worktreeInfo" in legacy_data:
        # This is a worktree config, preserve the information
        wt_info = legacy_data["worktreeInfo"]
        # The dataset name should already include the branch suffix
        
    return config


def check_legacy_hooks(git_dir: Path) -> Dict[HookType, bool]:
    """
    Check for legacy git hooks installed by the old system.
    
    Args:
        git_dir: Path to .git directory
        
    Returns:
        Dictionary mapping hook types to whether they're legacy hooks
    """
    hooks_dir = git_dir / "hooks"
    if not hooks_dir.exists():
        return {}
        
    legacy_hooks = {}
    
    # Check pre-commit hook
    pre_commit_path = hooks_dir / "pre-commit"
    if pre_commit_path.exists():
        content = pre_commit_path.read_text()
        # Legacy hooks have specific markers
        if "Code Query pre-commit hook" in content or "Code Query: Queued" in content:
            legacy_hooks[HookType.PRE_COMMIT] = True
            
    # Check post-merge hook
    post_merge_path = hooks_dir / "post-merge"
    if post_merge_path.exists():
        content = post_merge_path.read_text()
        if "Code Query post-merge hook" in content or "Code Query: Post-merge sync" in content:
            legacy_hooks[HookType.POST_MERGE] = True
            
    return legacy_hooks


def migrate_queue_file(base_path: Path) -> None:
    """
    Migrate legacy queue file from .code-query/doc-queue.txt to new location.
    
    Args:
        base_path: Base directory
    """
    legacy_queue = base_path / ".code-query" / "doc-queue.txt"
    new_queue = base_path / ".mcp_code_query" / "pending_documentation.txt"
    
    if legacy_queue.exists() and not new_queue.exists():
        # Ensure new directory exists
        new_queue.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy queue file
        import shutil
        shutil.copy2(legacy_queue, new_queue)