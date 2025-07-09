"""Main configuration management service."""

from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import os
from datetime import datetime
from .project_config import (
    ProjectConfig, ConfigVersion, HookType, 
    GitHookConfig, ConfigurationStatus
)
from .config_storage import ConfigStorage
from .git_hooks import GitHookManager
from .config_validator import ConfigValidator
from .migration import migrate_legacy_config, check_legacy_hooks, migrate_queue_file


class ConfigurationService:
    """High-level configuration management API."""
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize configuration service.
        
        Args:
            base_path: Base directory for configuration (defaults to cwd)
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.storage = ConfigStorage(self.base_path)
        self.git_manager = GitHookManager(self.base_path)
        self.validator = ConfigValidator()
        
        # Load existing config or None
        self._config: Optional[ProjectConfig] = self.storage.load_config()
        
        # Check for legacy config if no new config exists
        if not self._config:
            legacy_config = migrate_legacy_config(self.base_path)
            if legacy_config:
                # Check for legacy hooks
                if self.git_manager.git_dir:
                    legacy_hooks = check_legacy_hooks(self.git_manager.git_dir)
                    for hook_type, is_legacy in legacy_hooks.items():
                        if is_legacy:
                            legacy_config.git_hooks.append(
                                GitHookConfig(
                                    hook_type=hook_type,
                                    enabled=True,
                                    mode="queue",
                                    dataset_name=legacy_config.default_dataset
                                )
                            )
                
                # Save migrated config
                self.storage.save_config(legacy_config)
                self._config = legacy_config
                
                # Migrate queue file
                migrate_queue_file(self.base_path)
        
    def get_config(self) -> Optional[ProjectConfig]:
        """Get current project configuration."""
        return self._config
        
    def create_config(self, project_name: str, **options) -> ProjectConfig:
        """
        Create new project configuration.
        
        Args:
            project_name: Name of the project
            **options: Additional configuration options
            
        Returns:
            Created configuration
        """
        # Create default config
        config = ProjectConfig.create_default(project_name)
        
        # Apply options
        if "default_dataset" in options:
            config.default_dataset = options["default_dataset"]
        if "ignored_patterns" in options:
            config.ignored_patterns = options["ignored_patterns"]
        if "file_extensions" in options:
            config.file_extensions = options["file_extensions"]
        if "enable_analytics" in options:
            config.enable_analytics = options["enable_analytics"]
            
        # Validate
        is_valid, errors = self.validator.validate_config(config)
        if not is_valid:
            raise ValueError(f"Invalid configuration: {', '.join(errors)}")
            
        # Save
        self.storage.save_config(config)
        self._config = config
        
        return config
        
    def update_config(self, updates: Dict[str, Any]) -> ProjectConfig:
        """
        Update existing configuration.
        
        Args:
            updates: Dictionary of updates to apply
            
        Returns:
            Updated configuration
        """
        if not self._config:
            raise ValueError("No configuration exists")
            
        # Apply updates
        config_dict = self._config.to_dict()
        
        # Handle nested updates carefully
        for key, value in updates.items():
            if key == "git_hooks":
                # Special handling for git hooks
                continue
            elif key in config_dict:
                config_dict[key] = value
                
        # Recreate config from updated dict
        updated_config = ProjectConfig.from_dict(config_dict)
        
        # Validate
        is_valid, errors = self.validator.validate_config(updated_config)
        if not is_valid:
            raise ValueError(f"Invalid configuration: {', '.join(errors)}")
            
        # Save
        self.storage.save_config(updated_config)
        self._config = updated_config
        
        return updated_config
        
    def install_git_hook(self, hook_type: HookType, 
                        dataset_name: Optional[str] = None,
                        mode: str = "queue") -> Tuple[bool, str]:
        """
        Install a git hook.
        
        Args:
            hook_type: Type of hook to install
            dataset_name: Optional dataset name for the hook
            mode: Hook mode (queue, block, async)
            
        Returns:
            Tuple of (success, message)
        """
        # Create hook config
        hook_config = GitHookConfig(
            hook_type=hook_type,
            enabled=True,
            mode=mode,
            dataset_name=dataset_name or self._config.default_dataset if self._config else None
        )
        
        # Install hook
        success, message = self.git_manager.install_hook(hook_config)
        
        if success and self._config:
            # Update configuration
            # Remove existing hook config if any
            self._config.git_hooks = [
                h for h in self._config.git_hooks 
                if h.hook_type != hook_type
            ]
            # Add new hook config
            self._config.git_hooks.append(hook_config)
            self.storage.save_config(self._config)
            
        return success, message
        
    def remove_git_hook(self, hook_type: HookType) -> Tuple[bool, str]:
        """
        Remove a git hook.
        
        Args:
            hook_type: Type of hook to remove
            
        Returns:
            Tuple of (success, message)
        """
        success, message = self.git_manager.remove_hook(hook_type)
        
        if success and self._config:
            # Update configuration
            self._config.git_hooks = [
                h for h in self._config.git_hooks 
                if h.hook_type != hook_type
            ]
            self.storage.save_config(self._config)
            
        return success, message
        
    def get_installed_hooks(self) -> List[HookType]:
        """Get list of installed git hooks."""
        return self.git_manager.get_installed_hooks()
        
    def get_configuration_status(self) -> ConfigurationStatus:
        """Get detailed configuration status."""
        storage_status = self.storage.get_config_status()
        
        # Enhance with actual git hook status
        if storage_status.is_configured:
            actual_hooks = self.git_manager.get_installed_hooks()
            storage_status.hooks_installed = actual_hooks
            storage_status.has_git_hooks = len(actual_hooks) > 0
            
        return storage_status
        
    def validate_configuration(self) -> Tuple[bool, List[str]]:
        """
        Validate current configuration.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        if not self._config:
            return False, ["No configuration exists"]
            
        return self.validator.validate_config(self._config)
        
    def migrate_configuration(self) -> Optional[ProjectConfig]:
        """
        Migrate configuration to latest version if needed.
        
        Returns:
            Migrated configuration or None if no migration needed
        """
        if not self._config:
            return None
            
        if self._config.version == ConfigVersion.latest():
            return None
            
        # Backup before migration
        self.storage.backup_config()
        
        # Perform migration
        migrated = self.validator.migrate_config(self._config)
        
        # Save migrated config
        self.storage.save_config(migrated)
        self._config = migrated
        
        return migrated
        
    def get_environment_config(self) -> Dict[str, Any]:
        """Get configuration from environment variables."""
        env_config = {}
        
        # Check for relevant environment variables
        env_vars = {
            "CODEQUERY_DEFAULT_DATASET": "default_dataset",
            "CODEQUERY_ENABLE_ANALYTICS": "enable_analytics",
            "CODEQUERY_MAX_FILE_SIZE_MB": "max_file_size_mb"
        }
        
        for env_var, config_key in env_vars.items():
            value = os.environ.get(env_var)
            if value is not None:
                # Convert types as needed
                if config_key == "enable_analytics":
                    env_config[config_key] = value.lower() in ("true", "1", "yes")
                elif config_key == "max_file_size_mb":
                    try:
                        env_config[config_key] = int(value)
                    except ValueError:
                        pass
                else:
                    env_config[config_key] = value
                    
        return env_config
        
    def apply_environment_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        if not self._config:
            return
            
        env_config = self.get_environment_config()
        if env_config:
            self.update_config(env_config)
            
    def reset_configuration(self) -> None:
        """Reset configuration to defaults."""
        if self._config:
            project_name = self._config.project_name
            self.create_config(project_name)
            
    def export_config(self, path: str) -> None:
        """Export configuration to a file."""
        if not self._config:
            raise ValueError("No configuration to export")
            
        import json
        with open(path, 'w') as f:
            json.dump(self._config.to_dict(), f, indent=2)
            
    def import_config(self, path: str) -> ProjectConfig:
        """Import configuration from a file."""
        import json
        with open(path, 'r') as f:
            data = json.load(f)
            
        config = ProjectConfig.from_dict(data)
        
        # Validate
        is_valid, errors = self.validator.validate_config(config)
        if not is_valid:
            raise ValueError(f"Invalid configuration: {', '.join(errors)}")
            
        # Save
        self.storage.save_config(config)
        self._config = config
        
        return config