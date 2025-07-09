"""Configuration validation and migration."""

from typing import Tuple, List, Dict, Any
import re
from datetime import datetime
from .project_config import ProjectConfig, ConfigVersion, HookType, GitHookConfig


class ConfigValidator:
    """Validates and migrates project configurations."""
    
    # Valid file extension pattern
    FILE_EXT_PATTERN = re.compile(r'^\.\w+$')
    
    # Valid ignored pattern (simple glob patterns)
    IGNORED_PATTERN = re.compile(r'^[\w\-.*/_]+$')
    
    def validate_config(self, config: ProjectConfig) -> Tuple[bool, List[str]]:
        """
        Validate a project configuration.
        
        Args:
            config: Configuration to validate
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Validate project name
        if not config.project_name or not config.project_name.strip():
            errors.append("Project name cannot be empty")
        elif len(config.project_name) > 100:
            errors.append("Project name too long (max 100 characters)")
            
        # Validate version
        if config.version not in ConfigVersion:
            errors.append(f"Invalid configuration version: {config.version}")
            
        # Validate timestamps
        if config.created_at > datetime.now():
            errors.append("Created timestamp cannot be in the future")
        if config.updated_at < config.created_at:
            errors.append("Updated timestamp cannot be before created timestamp")
            
        # Validate file extensions
        for ext in config.file_extensions:
            if not self.FILE_EXT_PATTERN.match(ext):
                errors.append(f"Invalid file extension: {ext}")
                
        # Validate ignored patterns
        for pattern in config.ignored_patterns:
            if not self.IGNORED_PATTERN.match(pattern):
                errors.append(f"Invalid ignored pattern: {pattern}")
                
        # Validate max file size
        if config.max_file_size_mb <= 0:
            errors.append("Max file size must be positive")
        elif config.max_file_size_mb > 1000:
            errors.append("Max file size too large (max 1000 MB)")
            
        # Validate analytics retention
        if config.analytics_retention_days < 0:
            errors.append("Analytics retention days cannot be negative")
        elif config.analytics_retention_days > 365:
            errors.append("Analytics retention too long (max 365 days)")
            
        # Validate git hooks
        hook_types_seen = set()
        for hook in config.git_hooks:
            # Check for duplicates
            if hook.hook_type in hook_types_seen:
                errors.append(f"Duplicate git hook: {hook.hook_type.value}")
            hook_types_seen.add(hook.hook_type)
            
            # Validate hook mode
            if hook.mode not in ["queue", "block", "async"]:
                errors.append(f"Invalid hook mode: {hook.mode}")
                
        return len(errors) == 0, errors
        
    def migrate_config(self, config: ProjectConfig) -> ProjectConfig:
        """
        Migrate configuration to latest version.
        
        Args:
            config: Configuration to migrate
            
        Returns:
            Migrated configuration
        """
        if config.version == ConfigVersion.latest():
            # Already latest version
            return config
            
        # Create a copy of the config
        config_dict = config.to_dict()
        
        # Perform migrations based on version
        if config.version == ConfigVersion.V1:
            # V1 to V2 migration
            config_dict = self._migrate_v1_to_v2(config_dict)
            
        # Update version
        config_dict["version"] = ConfigVersion.latest().value
        config_dict["updated_at"] = datetime.now().isoformat()
        
        # Create new config from migrated data
        return ProjectConfig.from_dict(config_dict)
        
    def _migrate_v1_to_v2(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Migrate from V1 to V2.
        
        V2 additions (example for future):
        - Add search_settings field
        - Add team_settings field
        - Rename some fields
        """
        # Example migration (currently V2 doesn't exist)
        # This is a placeholder for future migrations
        
        # Add new fields with defaults
        if "search_settings" not in config_dict:
            config_dict["search_settings"] = {
                "fuzzy_matching": True,
                "min_score": 0.5
            }
            
        if "team_settings" not in config_dict:
            config_dict["team_settings"] = {
                "shared_datasets": False,
                "access_control": False
            }
            
        return config_dict
        
    def validate_hook_compatibility(self, config: ProjectConfig) -> List[str]:
        """
        Check for hook compatibility issues.
        
        Args:
            config: Configuration to check
            
        Returns:
            List of compatibility warnings
        """
        warnings = []
        
        # Check for conflicting hooks
        has_pre_commit = any(h.hook_type == HookType.PRE_COMMIT for h in config.git_hooks)
        has_post_merge = any(h.hook_type == HookType.POST_MERGE for h in config.git_hooks)
        
        if has_pre_commit and has_post_merge:
            # Check if they reference different datasets
            pre_commit_datasets = {
                h.dataset_name for h in config.git_hooks 
                if h.hook_type == HookType.PRE_COMMIT and h.dataset_name
            }
            post_merge_datasets = {
                h.dataset_name for h in config.git_hooks 
                if h.hook_type == HookType.POST_MERGE and h.dataset_name
            }
            
            if pre_commit_datasets and post_merge_datasets and \
               pre_commit_datasets != post_merge_datasets:
                warnings.append(
                    "Pre-commit and post-merge hooks reference different datasets"
                )
                
        return warnings
        
    def suggest_configuration(self, project_path: str) -> Dict[str, Any]:
        """
        Suggest configuration based on project analysis.
        
        Args:
            project_path: Path to project
            
        Returns:
            Suggested configuration options
        """
        from pathlib import Path
        project_dir = Path(project_path)
        suggestions = {
            "ignored_patterns": [],
            "file_extensions": []
        }
        
        # Check for common patterns to ignore
        ignore_patterns = []
        
        # Python projects
        if (project_dir / "setup.py").exists() or \
           (project_dir / "pyproject.toml").exists():
            ignore_patterns.extend(["__pycache__", "*.pyc", ".pytest_cache", 
                                  "*.egg-info", "dist", "build"])
            suggestions["file_extensions"].append(".py")
            
        # Node.js projects
        if (project_dir / "package.json").exists():
            ignore_patterns.extend(["node_modules", "dist", "build", ".next"])
            suggestions["file_extensions"].extend([".js", ".ts", ".jsx", ".tsx"])
            
        # Java projects
        if (project_dir / "pom.xml").exists() or \
           (project_dir / "build.gradle").exists():
            ignore_patterns.extend(["target", "build", "*.class"])
            suggestions["file_extensions"].extend([".java"])
            
        # Go projects
        if (project_dir / "go.mod").exists():
            ignore_patterns.append("vendor")
            suggestions["file_extensions"].append(".go")
            
        # Rust projects
        if (project_dir / "Cargo.toml").exists():
            ignore_patterns.append("target")
            suggestions["file_extensions"].append(".rs")
            
        # Common VCS and IDE patterns
        ignore_patterns.extend([".git", ".svn", ".hg", ".idea", ".vscode", 
                               "*.swp", "*.bak", "~*"])
        
        # Common build and dependency directories
        ignore_patterns.extend(["vendor", "deps", "dependencies"])
        
        # Set unique patterns
        suggestions["ignored_patterns"] = list(set(ignore_patterns))
        
        # Ensure common extensions are included
        common_extensions = [".md", ".txt", ".yml", ".yaml", ".json", ".xml"]
        suggestions["file_extensions"].extend(common_extensions)
        suggestions["file_extensions"] = list(set(suggestions["file_extensions"]))
        
        return suggestions