# PR 8: Configuration Service Extraction

## Overview
This PR extracts all configuration management logic into a dedicated service, consolidating project configuration, git hook management, and settings persistence. It provides a clean API for managing code-query project settings and git integration.

**Size**: Small | **Risk**: Low | **Value**: Low

## Dependencies
- PR 5 must be completed (Configuration needs dataset operations)
- This is the final PR in the DDD refactoring series

## Objectives
1. Extract all configuration logic from sqlite_storage.py
2. Centralize project configuration management
3. Provide clean APIs for git hook installation/removal
4. Support configuration versioning and migration
5. Enable configuration validation and defaults
6. Separate git-specific logic from general configuration

## Implementation Steps

### Step 1: Create Directory Structure
```
config/
├── __init__.py              # Export main classes
├── config_service.py        # Main configuration management service
├── git_hooks.py            # Git hook installation and management
├── project_config.py       # Project configuration models and DTOs
├── config_storage.py       # Configuration persistence
└── config_validator.py     # Configuration validation logic
```

### Step 2: Define Configuration Models
**File**: `config/project_config.py`
- Project configuration DTOs
- Git hook configuration models
- Configuration version tracking
- Default values and schemas

### Step 3: Implement Git Hook Management
**File**: `config/git_hooks.py`
- Extract git hook installation logic
- Support pre-commit and post-merge hooks
- Handle hook removal and updates
- Provide hook status checking

### Step 4: Create Configuration Storage
**File**: `config/config_storage.py`
- JSON-based configuration persistence
- Configuration file management
- Atomic writes with backup
- Migration support

### Step 5: Implement Configuration Service
**File**: `config/config_service.py`
- High-level configuration API
- Dependency injection for storage and git
- Configuration lifecycle management
- Environment variable support

### Step 6: Add Configuration Validator
**File**: `config/config_validator.py`
- Schema validation for configurations
- Type checking and constraints
- Migration validation
- Compatibility checks

## Detailed Implementation

### config/project_config.py
```python
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import json

class ConfigVersion(Enum):
    """Configuration schema versions."""
    V1 = "1.0"
    V2 = "2.0"  # Future version with additional fields
    
    @classmethod
    def latest(cls) -> 'ConfigVersion':
        """Get the latest configuration version."""
        return cls.V2

class HookType(Enum):
    """Supported git hook types."""
    PRE_COMMIT = "pre-commit"
    POST_MERGE = "post-merge"
    POST_CHECKOUT = "post-checkout"

@dataclass
class GitHookConfig:
    """Configuration for a git hook."""
    hook_type: HookType
    enabled: bool = True
    mode: str = "queue"  # queue, block, async
    dataset_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "hook_type": self.hook_type.value,
            "enabled": self.enabled,
            "mode": self.mode,
            "dataset_name": self.dataset_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GitHookConfig':
        """Create from dictionary."""
        return cls(
            hook_type=HookType(data["hook_type"]),
            enabled=data.get("enabled", True),
            mode=data.get("mode", "queue"),
            dataset_name=data.get("dataset_name"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
        )

@dataclass
class ProjectConfig:
    """Complete project configuration."""
    version: ConfigVersion
    dataset_name: str
    source_directory: str
    exclude_patterns: List[str] = field(default_factory=list)
    model: str = "claude-3-5-sonnet-20241022"
    git_hooks: List[GitHookConfig] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Additional configuration options
    auto_sync: bool = False
    sync_on_merge: bool = True
    queue_batch_size: int = 20
    analysis_timeout: int = 300  # seconds
    
    @classmethod
    def get_defaults(cls) -> 'ProjectConfig':
        """Get default configuration."""
        return cls(
            version=ConfigVersion.latest(),
            dataset_name="",
            source_directory=".",
            exclude_patterns=[
                "*.pyc", "__pycache__", ".git", ".env",
                "node_modules", "venv", ".venv", "dist",
                "build", "*.egg-info", ".pytest_cache",
                ".mypy_cache", ".coverage", "*.log"
            ],
            model="claude-3-5-sonnet-20241022"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version.value,
            "dataset_name": self.dataset_name,
            "source_directory": self.source_directory,
            "exclude_patterns": self.exclude_patterns,
            "model": self.model,
            "git_hooks": [hook.to_dict() for hook in self.git_hooks],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "auto_sync": self.auto_sync,
            "sync_on_merge": self.sync_on_merge,
            "queue_batch_size": self.queue_batch_size,
            "analysis_timeout": self.analysis_timeout
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectConfig':
        """Create from dictionary, handling version migrations."""
        version = ConfigVersion(data.get("version", ConfigVersion.V1.value))
        
        # Handle version migrations
        if version == ConfigVersion.V1:
            data = cls._migrate_v1_to_v2(data)
            version = ConfigVersion.V2
        
        return cls(
            version=version,
            dataset_name=data["dataset_name"],
            source_directory=data.get("source_directory", "."),
            exclude_patterns=data.get("exclude_patterns", cls.get_defaults().exclude_patterns),
            model=data.get("model", "claude-3-5-sonnet-20241022"),
            git_hooks=[GitHookConfig.from_dict(h) for h in data.get("git_hooks", [])],
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            auto_sync=data.get("auto_sync", False),
            sync_on_merge=data.get("sync_on_merge", True),
            queue_batch_size=data.get("queue_batch_size", 20),
            analysis_timeout=data.get("analysis_timeout", 300)
        )
    
    @staticmethod
    def _migrate_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate v1 config to v2 format."""
        # V2 adds new fields with defaults
        data["version"] = ConfigVersion.V2.value
        data.setdefault("auto_sync", False)
        data.setdefault("sync_on_merge", True)
        data.setdefault("queue_batch_size", 20)
        data.setdefault("analysis_timeout", 300)
        return data

@dataclass
class ConfigurationStatus:
    """Status of project configuration."""
    has_config: bool
    config_path: Optional[str] = None
    is_git_repo: bool = False
    git_hooks_installed: List[HookType] = field(default_factory=list)
    dataset_exists: bool = False
    needs_migration: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
```

### config/git_hooks.py
```python
import os
import stat
import subprocess
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime
from .project_config import HookType, GitHookConfig

logger = logging.getLogger(__name__)

class GitHookManager:
    """Manages git hook installation and configuration."""
    
    # Hook templates
    PRE_COMMIT_TEMPLATE = '''#!/bin/bash
# Code Query MCP - Pre-commit Hook
# Queues changed files for documentation update

# Get the root of the git repository
GIT_ROOT=$(git rev-parse --show-toplevel)

# Configuration
DATASET_NAME="{dataset_name}"
QUEUE_FILE="$GIT_ROOT/.mcp_code_query/queued_files.json"

# Create queue directory if it doesn't exist
mkdir -p "$(dirname "$QUEUE_FILE")"

# Get changed files (staged)
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\\.(py|js|jsx|ts|tsx|java|cpp|hpp|go|rs|rb|php)$')

if [ -z "$CHANGED_FILES" ]; then
    exit 0
fi

# Queue files for documentation
if [ -f "$QUEUE_FILE" ]; then
    # Merge with existing queue
    echo "$CHANGED_FILES" | jq -R . | jq -s '. as $new | 
        ($queue_file | fromjson) as $existing | 
        ($existing + $new) | unique' --slurpfile queue_file "$QUEUE_FILE" > "$QUEUE_FILE.tmp"
    mv "$QUEUE_FILE.tmp" "$QUEUE_FILE"
else
    # Create new queue
    echo "$CHANGED_FILES" | jq -R . | jq -s '.' > "$QUEUE_FILE"
fi

echo "Code Query: Queued $(echo "$CHANGED_FILES" | wc -l) files for documentation update"
echo "Run 'code-query process-queue' to update documentation"
'''

    POST_MERGE_TEMPLATE = '''#!/bin/bash
# Code Query MCP - Post-merge Hook
# Syncs documentation changes from merged branch

# Get the root of the git repository
GIT_ROOT=$(git rev-parse --show-toplevel)

# Configuration
MAIN_DATASET="{main_dataset}"

# Only run if in a worktree
if [ -f "$GIT_ROOT/.git" ]; then
    # This is a worktree
    WORKTREE_DATASET=$(basename "$GIT_ROOT")
    
    echo "Code Query: Detected merge in worktree '$WORKTREE_DATASET'"
    echo "Run 'code-query sync-dataset --source $WORKTREE_DATASET --target $MAIN_DATASET' to sync changes"
fi
'''

    def __init__(self, git_root: str):
        """Initialize with git repository root."""
        self.git_root = Path(git_root)
        self.hooks_dir = self.git_root / ".git" / "hooks"
        
        # Handle worktrees
        if (self.git_root / ".git").is_file():
            # This is a worktree, read the gitdir
            with open(self.git_root / ".git", 'r') as f:
                gitdir = f.read().strip().replace('gitdir: ', '')
                self.hooks_dir = Path(gitdir) / "hooks"
    
    def install_hook(self, hook_config: GitHookConfig) -> bool:
        """Install a git hook."""
        try:
            # Ensure hooks directory exists
            self.hooks_dir.mkdir(parents=True, exist_ok=True)
            
            # Get hook content
            if hook_config.hook_type == HookType.PRE_COMMIT:
                content = self.PRE_COMMIT_TEMPLATE.format(
                    dataset_name=hook_config.dataset_name or "default"
                )
                hook_file = self.hooks_dir / "pre-commit"
            elif hook_config.hook_type == HookType.POST_MERGE:
                content = self.POST_MERGE_TEMPLATE.format(
                    main_dataset=hook_config.dataset_name or "main"
                )
                hook_file = self.hooks_dir / "post-merge"
            else:
                logger.error(f"Unsupported hook type: {hook_config.hook_type}")
                return False
            
            # Check for existing hook
            if hook_file.exists():
                # Back up existing hook
                backup_file = hook_file.with_suffix('.backup')
                hook_file.rename(backup_file)
                logger.info(f"Backed up existing hook to {backup_file}")
            
            # Write new hook
            hook_file.write_text(content)
            
            # Make executable
            st = hook_file.stat()
            hook_file.chmod(st.st_mode | stat.S_IEXEC)
            
            logger.info(f"Installed {hook_config.hook_type.value} hook")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install hook: {e}")
            return False
    
    def remove_hook(self, hook_type: HookType) -> bool:
        """Remove a git hook."""
        try:
            hook_file = self.hooks_dir / hook_type.value
            
            if not hook_file.exists():
                logger.warning(f"Hook {hook_type.value} not found")
                return True
            
            # Check if it's our hook
            content = hook_file.read_text()
            if "Code Query MCP" not in content:
                logger.warning(f"Hook {hook_type.value} is not managed by Code Query")
                return False
            
            # Remove the hook
            hook_file.unlink()
            
            # Restore backup if exists
            backup_file = hook_file.with_suffix('.backup')
            if backup_file.exists():
                backup_file.rename(hook_file)
                logger.info(f"Restored backed up hook for {hook_type.value}")
            
            logger.info(f"Removed {hook_type.value} hook")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove hook: {e}")
            return False
    
    def get_installed_hooks(self) -> List[HookType]:
        """Get list of installed Code Query hooks."""
        installed = []
        
        if not self.hooks_dir.exists():
            return installed
        
        for hook_type in HookType:
            hook_file = self.hooks_dir / hook_type.value
            if hook_file.exists():
                content = hook_file.read_text()
                if "Code Query MCP" in content:
                    installed.append(hook_type)
        
        return installed
    
    def check_hook_status(self, hook_type: HookType) -> Dict[str, Any]:
        """Check detailed status of a hook."""
        hook_file = self.hooks_dir / hook_type.value
        
        status = {
            "installed": False,
            "managed_by_code_query": False,
            "executable": False,
            "path": str(hook_file),
            "content_preview": None
        }
        
        if hook_file.exists():
            status["installed"] = True
            
            # Check if executable
            status["executable"] = os.access(hook_file, os.X_OK)
            
            # Check content
            try:
                content = hook_file.read_text()
                status["managed_by_code_query"] = "Code Query MCP" in content
                status["content_preview"] = content[:200] + "..." if len(content) > 200 else content
            except Exception as e:
                status["error"] = str(e)
        
        return status
    
    def validate_environment(self) -> Dict[str, Any]:
        """Validate git environment for hooks."""
        validation = {
            "is_git_repo": False,
            "git_dir": None,
            "hooks_dir_exists": False,
            "has_jq": False,
            "errors": []
        }
        
        # Check if git repo
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.git_root,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                validation["is_git_repo"] = True
                validation["git_dir"] = result.stdout.strip()
        except Exception as e:
            validation["errors"].append(f"Git check failed: {e}")
        
        # Check hooks directory
        validation["hooks_dir_exists"] = self.hooks_dir.exists()
        
        # Check for jq (required for pre-commit hook)
        try:
            result = subprocess.run(["which", "jq"], capture_output=True)
            validation["has_jq"] = result.returncode == 0
            if not validation["has_jq"]:
                validation["errors"].append("jq is required for pre-commit hook. Install with: brew install jq")
        except Exception:
            validation["errors"].append("Could not check for jq installation")
        
        return validation
```

### config/config_storage.py
```python
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from datetime import datetime
import shutil

logger = logging.getLogger(__name__)

class ConfigStorage:
    """Handles configuration file persistence."""
    
    CONFIG_DIR = ".code-query"
    CONFIG_FILE = "config.json"
    BACKUP_SUFFIX = ".backup"
    
    def __init__(self, base_path: str):
        """Initialize with base path for configuration."""
        self.base_path = Path(base_path)
        self.config_dir = self.base_path / self.CONFIG_DIR
        self.config_file = self.config_dir / self.CONFIG_FILE
    
    def ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def read_config(self) -> Optional[Dict[str, Any]]:
        """Read configuration from file."""
        if not self.config_file.exists():
            return None
        
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            # Try to read backup
            backup_file = self.config_file.with_suffix(self.CONFIG_FILE + self.BACKUP_SUFFIX)
            if backup_file.exists():
                logger.info("Attempting to read from backup config")
                try:
                    with open(backup_file, 'r') as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Backup config also failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to read config: {e}")
            return None
    
    def write_config(self, config: Dict[str, Any]) -> bool:
        """Write configuration to file atomically."""
        try:
            self.ensure_config_dir()
            
            # Add timestamp
            config["updated_at"] = datetime.now().isoformat()
            
            # Create backup of existing config
            if self.config_file.exists():
                backup_file = self.config_file.with_suffix(self.CONFIG_FILE + self.BACKUP_SUFFIX)
                shutil.copy2(self.config_file, backup_file)
            
            # Write to temporary file first
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Atomic rename
            temp_file.replace(self.config_file)
            
            logger.info("Configuration saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to write config: {e}")
            return False
    
    def delete_config(self) -> bool:
        """Delete configuration file."""
        try:
            if self.config_file.exists():
                # Create final backup
                backup_file = self.config_file.with_suffix('.deleted' + self.BACKUP_SUFFIX)
                shutil.copy2(self.config_file, backup_file)
                
                # Delete config
                self.config_file.unlink()
                logger.info("Configuration deleted")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete config: {e}")
            return False
    
    def get_config_path(self) -> str:
        """Get the configuration file path."""
        return str(self.config_file)
    
    def config_exists(self) -> bool:
        """Check if configuration file exists."""
        return self.config_file.exists()
    
    def get_queued_files(self) -> Optional[List[str]]:
        """Read queued files from git hook queue."""
        queue_file = self.base_path / ".mcp_code_query" / "queued_files.json"
        
        if not queue_file.exists():
            return None
        
        try:
            with open(queue_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read queue file: {e}")
            return None
    
    def clear_queued_files(self) -> bool:
        """Clear the queued files."""
        queue_file = self.base_path / ".mcp_code_query" / "queued_files.json"
        
        try:
            if queue_file.exists():
                queue_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to clear queue: {e}")
            return False
```

### config/config_validator.py
```python
from typing import Dict, Any, List, Optional
from .project_config import ProjectConfig, ConfigVersion, HookType
import re
from pathlib import Path

class ConfigValidator:
    """Validates project configurations."""
    
    @staticmethod
    def validate_dataset_name(name: str) -> List[str]:
        """Validate dataset name format."""
        errors = []
        
        if not name:
            errors.append("Dataset name cannot be empty")
        elif len(name) > 100:
            errors.append("Dataset name too long (max 100 characters)")
        elif not re.match(r'^[a-zA-Z0-9_-]+$', name):
            errors.append("Dataset name can only contain letters, numbers, underscores, and hyphens")
        
        return errors
    
    @staticmethod
    def validate_exclude_patterns(patterns: List[str]) -> List[str]:
        """Validate exclude patterns."""
        errors = []
        
        for pattern in patterns:
            try:
                # Test if pattern is valid glob
                Path(".").glob(pattern)
            except Exception as e:
                errors.append(f"Invalid pattern '{pattern}': {e}")
        
        return errors
    
    @staticmethod
    def validate_model(model: str) -> List[str]:
        """Validate model selection."""
        errors = []
        
        # TODO: Consider loading this list from a config file or remote source
        # to allow for easier updates without code changes
        valid_models = [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
        
        if model not in valid_models:
            errors.append(f"Invalid model '{model}'. Valid models: {', '.join(valid_models)}")
        
        return errors
    
    @classmethod
    def validate_config(cls, config: ProjectConfig) -> Dict[str, List[str]]:
        """Validate entire configuration."""
        validation_errors = {}
        
        # Validate dataset name
        dataset_errors = cls.validate_dataset_name(config.dataset_name)
        if dataset_errors:
            validation_errors["dataset_name"] = dataset_errors
        
        # Validate source directory
        source_dir = Path(config.source_directory)
        if not source_dir.exists():
            validation_errors["source_directory"] = [f"Directory '{config.source_directory}' does not exist"]
        elif not source_dir.is_dir():
            validation_errors["source_directory"] = [f"'{config.source_directory}' is not a directory"]
        
        # Validate exclude patterns
        pattern_errors = cls.validate_exclude_patterns(config.exclude_patterns)
        if pattern_errors:
            validation_errors["exclude_patterns"] = pattern_errors
        
        # Validate model
        model_errors = cls.validate_model(config.model)
        if model_errors:
            validation_errors["model"] = model_errors
        
        # Validate numeric fields
        if config.queue_batch_size < 1 or config.queue_batch_size > 1000:
            validation_errors["queue_batch_size"] = ["Must be between 1 and 1000"]
        
        if config.analysis_timeout < 10 or config.analysis_timeout > 3600:
            validation_errors["analysis_timeout"] = ["Must be between 10 and 3600 seconds"]
        
        return validation_errors
    
    @staticmethod
    def validate_migration(old_config: Dict[str, Any], new_config: ProjectConfig) -> List[str]:
        """Validate configuration migration."""
        warnings = []
        
        # Check for data loss
        old_version = ConfigVersion(old_config.get("version", ConfigVersion.V1.value))
        if old_version.value > new_config.version.value:
            warnings.append(f"Downgrading from version {old_version.value} to {new_config.version.value}")
        
        # Check for significant changes
        if old_config.get("dataset_name") != new_config.dataset_name:
            warnings.append("Dataset name has changed - ensure data integrity")
        
        return warnings
```

### config/config_service.py
```python
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
import logging
from datetime import datetime

from .project_config import ProjectConfig, GitHookConfig, HookType, ConfigurationStatus
from .config_storage import ConfigStorage
from .config_validator import ConfigValidator
from .git_hooks import GitHookManager
from dataset.dataset_service import DatasetService
from helpers.git_helper import GitHelper

logger = logging.getLogger(__name__)

class ConfigurationService:
    """Main service for configuration management."""
    
    def __init__(self, 
                 dataset_service: DatasetService,
                 git_helper: Optional[GitHelper] = None,
                 base_path: Optional[str] = None):
        """Initialize with dependencies."""
        self.dataset_service = dataset_service
        self.git_helper = git_helper or GitHelper()
        self.base_path = Path(base_path or os.getcwd())
        self.storage = ConfigStorage(str(self.base_path))
        self.validator = ConfigValidator()
        self.hook_manager = GitHookManager(str(self.base_path))
    
    def get_config(self) -> Optional[ProjectConfig]:
        """Get current project configuration."""
        config_data = self.storage.read_config()
        if not config_data:
            return None
        
        try:
            return ProjectConfig.from_dict(config_data)
        except Exception as e:
            logger.error(f"Failed to parse config: {e}")
            return None
    
    def create_config(self, 
                     dataset_name: str,
                     source_directory: Optional[str] = None,
                     exclude_patterns: Optional[List[str]] = None,
                     model: Optional[str] = None) -> ProjectConfig:
        """Create new project configuration."""
        # Get defaults
        config = ProjectConfig.get_defaults()
        
        # Override with provided values
        config.dataset_name = dataset_name
        config.source_directory = source_directory or str(self.base_path)
        if exclude_patterns is not None:
            config.exclude_patterns = exclude_patterns
        if model is not None:
            config.model = model
        
        # Validate
        errors = self.validator.validate_config(config)
        if errors:
            raise ValueError(f"Invalid configuration: {errors}")
        
        # Save
        if self.storage.write_config(config.to_dict()):
            logger.info(f"Created project configuration for dataset '{dataset_name}'")
            return config
        else:
            raise RuntimeError("Failed to save configuration")
    
    def update_config(self, updates: Dict[str, Any]) -> ProjectConfig:
        """Update existing configuration."""
        current = self.get_config()
        if not current:
            raise ValueError("No existing configuration found")
        
        # Apply updates
        config_dict = current.to_dict()
        config_dict.update(updates)
        config_dict["updated_at"] = datetime.now().isoformat()
        
        # Parse and validate
        new_config = ProjectConfig.from_dict(config_dict)
        errors = self.validator.validate_config(new_config)
        if errors:
            raise ValueError(f"Invalid configuration: {errors}")
        
        # Check migration warnings
        warnings = self.validator.validate_migration(current.to_dict(), new_config)
        for warning in warnings:
            logger.warning(warning)
        
        # Save
        if self.storage.write_config(new_config.to_dict()):
            logger.info("Updated project configuration")
            return new_config
        else:
            raise RuntimeError("Failed to save configuration")
    
    def delete_config(self) -> bool:
        """Delete project configuration."""
        return self.storage.delete_config()
    
    def get_status(self) -> ConfigurationStatus:
        """Get comprehensive configuration status."""
        status = ConfigurationStatus(
            has_config=self.storage.config_exists(),
            config_path=self.storage.get_config_path() if self.storage.config_exists() else None
        )
        
        # Check git status
        if self.git_helper:
            repo_info = self.git_helper.get_repository_info(str(self.base_path))
            status.is_git_repo = repo_info["is_git_repo"]
        
        # Check installed hooks
        if status.is_git_repo:
            status.git_hooks_installed = self.hook_manager.get_installed_hooks()
        
        # Check dataset
        config = self.get_config()
        if config:
            try:
                dataset = self.dataset_service.get_dataset(config.dataset_name)
                status.dataset_exists = dataset is not None
            except Exception:
                status.dataset_exists = False
        
        # Check for needed migrations
        if config and config.version != ConfigVersion.latest():
            status.needs_migration = True
            status.warnings.append(f"Configuration needs migration from {config.version.value} to {ConfigVersion.latest().value}")
        
        # Validate environment
        if status.is_git_repo:
            env_validation = self.hook_manager.validate_environment()
            if env_validation["errors"]:
                status.errors.extend(env_validation["errors"])
        
        return status
    
    def install_git_hook(self, 
                        hook_type: HookType,
                        dataset_name: Optional[str] = None,
                        mode: str = "queue") -> bool:
        """Install a git hook."""
        # Get current config
        config = self.get_config()
        if not config and not dataset_name:
            raise ValueError("No configuration found and no dataset name provided")
        
        if not dataset_name:
            dataset_name = config.dataset_name
        
        # Create hook config
        hook_config = GitHookConfig(
            hook_type=hook_type,
            dataset_name=dataset_name,
            mode=mode,
            created_at=datetime.now()
        )
        
        # Install hook
        if not self.hook_manager.install_hook(hook_config):
            return False
        
        # Update configuration
        if config:
            # Remove existing hook of same type
            config.git_hooks = [h for h in config.git_hooks if h.hook_type != hook_type]
            config.git_hooks.append(hook_config)
            self.update_config({"git_hooks": [h.to_dict() for h in config.git_hooks]})
        
        return True
    
    def remove_git_hook(self, hook_type: HookType) -> bool:
        """Remove a git hook."""
        # Remove from filesystem
        if not self.hook_manager.remove_hook(hook_type):
            return False
        
        # Update configuration
        config = self.get_config()
        if config:
            config.git_hooks = [h for h in config.git_hooks if h.hook_type != hook_type]
            self.update_config({"git_hooks": [h.to_dict() for h in config.git_hooks]})
        
        return True
    
    def get_queued_files(self) -> Optional[List[str]]:
        """Get files queued by git hooks."""
        return self.storage.get_queued_files()
    
    def clear_queued_files(self) -> bool:
        """Clear queued files."""
        return self.storage.clear_queued_files()
    
    def recommend_setup(self) -> Dict[str, Any]:
        """Recommend setup steps based on current state."""
        recommendations = {
            "steps": [],
            "current_state": {},
            "is_ready": False
        }
        
        status = self.get_status()
        recommendations["current_state"] = {
            "has_config": status.has_config,
            "is_git_repo": status.is_git_repo,
            "dataset_exists": status.dataset_exists,
            "hooks_installed": [h.value for h in status.git_hooks_installed]
        }
        
        # Check what needs to be done
        if not status.has_config:
            recommendations["steps"].append({
                "action": "create_config",
                "description": "Create project configuration",
                "command": "code-query create-config --dataset-name YOUR_DATASET_NAME"
            })
        
        if not status.dataset_exists:
            recommendations["steps"].append({
                "action": "document_directory",
                "description": "Document your codebase",
                "command": "code-query document-directory --dataset-name YOUR_DATASET_NAME --directory ."
            })
        
        if status.is_git_repo and HookType.PRE_COMMIT not in status.git_hooks_installed:
            recommendations["steps"].append({
                "action": "install_pre_commit_hook",
                "description": "Install pre-commit hook for automatic file queuing",
                "command": "code-query install-hook --type pre-commit"
            })
        
        if status.needs_migration:
            recommendations["steps"].append({
                "action": "migrate_config",
                "description": "Migrate configuration to latest version",
                "command": "code-query migrate-config"
            })
        
        # Check if ready
        recommendations["is_ready"] = (
            status.has_config and 
            status.dataset_exists and 
            not status.errors and
            not status.needs_migration
        )
        
        return recommendations
    
    def migrate_config(self) -> ProjectConfig:
        """Migrate configuration to latest version."""
        config = self.get_config()
        if not config:
            raise ValueError("No configuration to migrate")
        
        if config.version == ConfigVersion.latest():
            logger.info("Configuration already at latest version")
            return config
        
        # Force migration by re-parsing
        config_dict = config.to_dict()
        new_config = ProjectConfig.from_dict(config_dict)
        
        # Save migrated config
        if self.storage.write_config(new_config.to_dict()):
            logger.info(f"Migrated configuration from {config.version.value} to {new_config.version.value}")
            return new_config
        else:
            raise RuntimeError("Failed to save migrated configuration")
```

## Testing Plan

### Unit Tests

#### test_project_config.py
```python
def test_config_defaults():
    """Test default configuration values."""
    config = ProjectConfig.get_defaults("test_dataset")  # Now requires dataset name
    assert config.version == ConfigVersion.latest()
    assert config.dataset_name == "test_dataset"
    assert len(config.exclude_patterns) > 0
    assert ".git" in config.exclude_patterns

def test_config_serialization():
    """Test config to/from dict conversion."""
    config = ProjectConfig(
        version=ConfigVersion.V2,
        dataset_name="test_dataset",
        source_directory="/test/path"
    )
    
    # Convert to dict and back
    config_dict = config.to_dict()
    restored = ProjectConfig.from_dict(config_dict)
    
    assert restored.dataset_name == config.dataset_name
    assert restored.source_directory == config.source_directory

def test_config_migration():
    """Test v1 to v2 migration."""
    v1_config = {
        "version": "1.0",
        "dataset_name": "test",
        "source_directory": "."
    }
    
    config = ProjectConfig.from_dict(v1_config)
    assert config.version == ConfigVersion.V2
    assert hasattr(config, "auto_sync")
    assert hasattr(config, "queue_batch_size")
```

#### test_config_validator.py
```python
def test_dataset_name_validation():
    """Test dataset name validation rules."""
    validator = ConfigValidator()
    
    # Valid names
    assert validator.validate_dataset_name("valid_name") == []
    assert validator.validate_dataset_name("project-123") == []
    
    # Invalid names
    assert len(validator.validate_dataset_name("")) > 0
    assert len(validator.validate_dataset_name("has spaces")) > 0
    assert len(validator.validate_dataset_name("a" * 101)) > 0

def test_config_validation():
    """Test full config validation."""
    validator = ConfigValidator()
    
    config = ProjectConfig(
        version=ConfigVersion.V2,
        dataset_name="test@invalid",  # Invalid character
        source_directory="/nonexistent",  # Doesn't exist
        queue_batch_size=10000  # Too large
    )
    
    errors = validator.validate_config(config)
    assert "dataset_name" in errors
    assert "source_directory" in errors
    assert "queue_batch_size" in errors
```

#### test_git_hooks.py
```python
def test_hook_installation(tmp_git_repo):
    """Test git hook installation."""
    manager = GitHookManager(tmp_git_repo)
    
    hook_config = GitHookConfig(
        hook_type=HookType.PRE_COMMIT,
        dataset_name="test_dataset"
    )
    
    # Install hook
    assert manager.install_hook(hook_config)
    
    # Verify installation
    installed = manager.get_installed_hooks()
    assert HookType.PRE_COMMIT in installed
    
    # Check content
    status = manager.check_hook_status(HookType.PRE_COMMIT)
    assert status["installed"]
    assert status["managed_by_code_query"]
    assert status["executable"]

def test_hook_removal(tmp_git_repo):
    """Test git hook removal."""
    manager = GitHookManager(tmp_git_repo)
    
    # Install then remove
    hook_config = GitHookConfig(hook_type=HookType.PRE_COMMIT)
    manager.install_hook(hook_config)
    
    assert manager.remove_hook(HookType.PRE_COMMIT)
    assert HookType.PRE_COMMIT not in manager.get_installed_hooks()
```

#### test_config_storage.py
```python
def test_atomic_write(tmp_path):
    """Test atomic configuration writes."""
    storage = ConfigStorage(str(tmp_path))
    
    config = {"test": "data", "nested": {"key": "value"}}
    
    # Write config
    assert storage.write_config(config)
    
    # Read back
    read_config = storage.read_config()
    assert read_config["test"] == "data"
    assert "updated_at" in read_config

def test_backup_on_corruption(tmp_path):
    """Test backup recovery on corrupted config."""
    storage = ConfigStorage(str(tmp_path))
    
    # Write valid config
    storage.write_config({"valid": "config"})
    
    # Corrupt the file
    config_file = tmp_path / ".code-query" / "config.json"
    config_file.write_text("invalid json{")
    
    # Should recover from backup
    config = storage.read_config()
    assert config is not None
```

### Integration Tests
```python
def test_full_configuration_flow():
    """Test complete configuration lifecycle."""
    # Create services
    dataset_service = Mock()
    config_service = ConfigurationService(dataset_service)
    
    # Create configuration
    config = config_service.create_config(
        dataset_name="test_project",
        exclude_patterns=["*.log", "temp/*"]
    )
    assert config.dataset_name == "test_project"
    
    # Install git hook
    assert config_service.install_git_hook(HookType.PRE_COMMIT)
    
    # Get status
    status = config_service.get_status()
    assert status.has_config
    assert HookType.PRE_COMMIT in status.git_hooks_installed
    
    # Update config
    updated = config_service.update_config({"model": "claude-3-opus-20240229"})
    assert updated.model == "claude-3-opus-20240229"
```

## Migration Strategy

### Phase 1: Extract Components
1. Create new config module with all classes
2. Move configuration logic from sqlite_storage.py
3. Extract git hook logic into GitHookManager
4. Keep backward compatibility temporarily

### Phase 2: Integration
1. Update MCP tools to use ConfigurationService
2. Replace direct config access with service calls
3. Update all git hook operations
4. Maintain existing file locations

### Phase 3: Cleanup
1. Remove configuration code from sqlite_storage.py
2. Update documentation
3. Add deprecation notices for old methods
4. Clean up imports

## Configuration File Structure

### Location: `.code-query/config.json`
```json
{
  "version": "2.0",
  "dataset_name": "my_project",
  "source_directory": ".",
  "exclude_patterns": [
    "*.pyc",
    "__pycache__",
    ".git",
    "node_modules"
  ],
  "model": "claude-3-5-sonnet-20241022",
  "git_hooks": [
    {
      "hook_type": "pre-commit",
      "enabled": true,
      "mode": "queue",
      "dataset_name": "my_project",
      "created_at": "2024-01-15T10:30:00",
      "updated_at": "2024-01-15T10:30:00"
    }
  ],
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T10:30:00",
  "auto_sync": false,
  "sync_on_merge": true,
  "queue_batch_size": 20,
  "analysis_timeout": 300
}
```

## Environment Variables

Support environment variable overrides:
```bash
CODEQUERY_DATASET_NAME=my_dataset
CODEQUERY_MODEL=claude-3-opus-20240229
CODEQUERY_EXCLUDE_PATTERNS="*.log,temp/*,build/*"
CODEQUERY_AUTO_SYNC=true
```

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Config corruption | Lost settings | Automatic backups, validation |
| Git hook conflicts | Broken workflows | Check existing hooks, backup |
| Migration failures | Stuck on old version | Careful migration logic, rollback |
| Permission issues | Can't write config | Clear error messages, fallbacks |

## Success Criteria

1. **Clean Separation**: All config logic extracted from storage
2. **Validation**: Comprehensive validation with clear errors
3. **Git Integration**: Reliable hook installation/removal
4. **Migration Support**: Smooth version upgrades
5. **Atomic Operations**: No partial writes or corruption
6. **User Experience**: Clear status and recommendations

## Future Enhancements

1. **Multi-project Support**: Multiple configs in one repo
2. **Team Settings**: Shared vs personal configuration
3. **Config Profiles**: Different settings for dev/prod
4. **Remote Config**: Fetch configuration from URL
5. **Config UI**: Web interface for configuration
6. **Config Templates**: Pre-built configurations for common setups