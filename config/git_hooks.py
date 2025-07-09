"""Git hook installation and management."""

import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from .project_config import HookType, GitHookConfig
from .utils import check_jq_installed


class GitHookManager:
    """Manages git hook installation and removal."""
    
    HOOK_TEMPLATES = {
        HookType.PRE_COMMIT: '''#!/bin/bash
# [Code Query] pre-commit hook - auto-generated
# This hook queues changed files for documentation updates
set -euo pipefail

# Get the working directory (git hooks run from repo root)
WORK_DIR=$(git rev-parse --show-toplevel)
cd "$WORK_DIR"

# Get the dataset name from config using absolute path
# Check new config location first, then legacy
CONFIG_FILE="$WORK_DIR/.mcp_code_query/project_config.json"
LEGACY_CONFIG="$WORK_DIR/.code-query/config.json"

if [ -f "$CONFIG_FILE" ]; then
    # New config format
    DATASET_NAME=$(jq -r '.default_dataset // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
elif [ -f "$LEGACY_CONFIG" ]; then
    # Legacy config format
    DATASET_NAME=$(jq -r '.mainDatasetName // .datasetName // empty' "$LEGACY_CONFIG" 2>/dev/null || echo "")
else
    echo "⚠️  Code Query: No config file found. Skipping documentation queue."
    exit 0
fi
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
''',
        
        HookType.POST_MERGE: '''#!/bin/bash
# [Code Query] post-merge hook - auto-generated
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
# Check new config location first, then legacy
CONFIG_FILE="$WORK_DIR/.mcp_code_query/project_config.json"
LEGACY_CONFIG="$WORK_DIR/.code-query/config.json"

if [ -f "$CONFIG_FILE" ]; then
    # New config format
    CURRENT_DATASET=$(jq -r '.default_dataset // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
elif [ -f "$LEGACY_CONFIG" ]; then
    # Legacy config format
    CURRENT_DATASET=$(jq -r '.mainDatasetName // .datasetName // empty' "$LEGACY_CONFIG" 2>/dev/null || echo "")
else
    exit 0
fi
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
        MAIN_WORKTREE_CONFIG="$GIT_COMMON_DIR/../.mcp_code_query/config.json"
        if [ -f "$MAIN_WORKTREE_CONFIG" ]; then
            MAIN_DATASET=$(jq -r '.default_dataset // empty' "$MAIN_WORKTREE_CONFIG" 2>/dev/null || echo "")
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
''',
        
        HookType.POST_CHECKOUT: '''#!/bin/bash
# [Code Query] MCP Post-checkout Hook  
# Notify about potential dataset changes when switching branches

# Get previous and new HEAD
prev_head=$1
new_head=$2
is_branch_checkout=$3

# Only interested in branch checkouts
if [ "$is_branch_checkout" != "1" ]; then
    exit 0
fi

# Get branch names
prev_branch=$(git name-rev --name-only $prev_head 2>/dev/null | sed 's/remotes\\/origin\\///')
new_branch=$(git rev-parse --abbrev-ref HEAD)

if [ "$prev_branch" != "$new_branch" ]; then
    echo "[Code Query] Switched from $prev_branch to $new_branch"
    
    # Check if datasets exist for these branches
    if [ -f .mcp_code_query/code_data.db ]; then
        echo "[Code Query] Consider using branch-specific datasets for isolated documentation"
    fi
fi
'''
    }
    
    def __init__(self, repo_path: Optional[str] = None):
        """Initialize git hook manager."""
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self.git_dir = self._find_git_dir()
        
    def _find_git_dir(self) -> Optional[Path]:
        """Find the .git directory (handles worktrees)."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            git_dir = result.stdout.strip()
            return Path(git_dir)
        except subprocess.CalledProcessError:
            return None
            
    def _get_hook_path(self, hook_type: HookType) -> Path:
        """Get the path to a specific hook file."""
        if not self.git_dir:
            raise ValueError("Not in a git repository")
        return self.git_dir / "hooks" / hook_type.value
        
    def get_hook_path(self, hook_type: HookType) -> Optional[Path]:
        """
        Get the path to a specific hook file (public method).
        
        Returns:
            Path to hook file or None if not in a git repository
        """
        try:
            return self._get_hook_path(hook_type)
        except ValueError:
            return None
        
    def install_hook(self, config: GitHookConfig) -> Tuple[bool, str]:
        """
        Install a git hook.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.git_dir:
            return False, "Not in a git repository"
            
        # Check jq requirement for hooks that need it
        if config.hook_type in [HookType.PRE_COMMIT, HookType.POST_MERGE]:
            jq_installed, jq_error = check_jq_installed()
            if not jq_installed:
                return False, f"jq is required for {config.hook_type.value} hook but not installed. {jq_error['message']}"
            
        hook_path = self._get_hook_path(config.hook_type)
        
        # Check if hook already exists
        if hook_path.exists():
            # Read existing content
            existing_content = hook_path.read_text()
            if "[Code Query]" in existing_content:
                return True, f"{config.hook_type.value} hook already installed"
            else:
                # Backup existing hook
                backup_path = hook_path.with_suffix(".backup")
                hook_path.rename(backup_path)
                message = f"Backed up existing {config.hook_type.value} hook to {backup_path.name}"
        else:
            message = f"Installed {config.hook_type.value} hook"
            
        # Get template
        template = self.HOOK_TEMPLATES.get(config.hook_type)
        if not template:
            return False, f"No template for {config.hook_type.value} hook"
            
        # Customize template if needed
        if config.dataset_name:
            template = template.replace(
                'dataset_name=""',
                f'dataset_name="{config.dataset_name}"'
            )
            
        # Write hook file
        hook_path.write_text(template)
        
        # Make executable
        hook_path.chmod(0o755)
        
        return True, message
        
    def remove_hook(self, hook_type: HookType) -> Tuple[bool, str]:
        """
        Remove a git hook.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.git_dir:
            return False, "Not in a git repository"
            
        hook_path = self._get_hook_path(hook_type)
        
        if not hook_path.exists():
            return True, f"{hook_type.value} hook not installed"
            
        # Check if it's our hook
        content = hook_path.read_text()
        if "[Code Query]" not in content:
            return False, f"{hook_type.value} hook exists but was not installed by Code Query"
            
        # Remove hook
        hook_path.unlink()
        
        # Restore backup if exists
        backup_path = hook_path.with_suffix(".backup")
        if backup_path.exists():
            backup_path.rename(hook_path)
            return True, f"Removed {hook_type.value} hook and restored backup"
            
        return True, f"Removed {hook_type.value} hook"
        
    def get_installed_hooks(self) -> List[HookType]:
        """Get list of installed Code Query hooks."""
        if not self.git_dir:
            return []
            
        installed = []
        for hook_type in HookType:
            hook_path = self._get_hook_path(hook_type)
            if hook_path.exists():
                content = hook_path.read_text()
                if "[Code Query]" in content:
                    installed.append(hook_type)
                    
        return installed
        
    def validate_hook(self, hook_type: HookType) -> Tuple[bool, Optional[str]]:
        """
        Validate that a hook is properly installed.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.git_dir:
            return False, "Not in a git repository"
            
        hook_path = self._get_hook_path(hook_type)
        
        if not hook_path.exists():
            return False, f"{hook_type.value} hook not found"
            
        # Check if executable
        if not os.access(hook_path, os.X_OK):
            return False, f"{hook_type.value} hook is not executable"
            
        # Check content
        content = hook_path.read_text()
        if "[Code Query]" not in content:
            return False, f"{hook_type.value} hook exists but was not installed by Code Query"
            
        return True, None
        
    def get_hook_status(self) -> Dict[str, Any]:
        """Get status of all hooks."""
        if not self.git_dir:
            return {
                "git_available": False,
                "hooks": {}
            }
            
        status = {
            "git_available": True,
            "git_dir": str(self.git_dir),
            "hooks": {}
        }
        
        for hook_type in HookType:
            hook_path = self._get_hook_path(hook_type)
            is_valid, error = self.validate_hook(hook_type)
            
            status["hooks"][hook_type.value] = {
                "installed": hook_path.exists(),
                "is_code_query_hook": is_valid,
                "error": error,
                "path": str(hook_path)
            }
            
        return status