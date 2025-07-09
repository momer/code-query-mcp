"""Configuration persistence and storage."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import shutil
from .project_config import ProjectConfig, ConfigVersion, ConfigurationStatus, HookType


class ConfigStorage:
    """Handles configuration file persistence."""
    
    CONFIG_FILENAME = "project_config.json"
    CONFIG_DIR = ".mcp_code_query"
    
    def __init__(self, base_path: Optional[str] = None):
        """Initialize configuration storage."""
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.config_dir = self.base_path / self.CONFIG_DIR
        self.config_file = self.config_dir / self.CONFIG_FILENAME
        
    def _ensure_config_dir(self) -> None:
        """Ensure configuration directory exists."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
    def load_config(self) -> Optional[ProjectConfig]:
        """
        Load configuration from file.
        
        Returns:
            ProjectConfig if exists and valid, None otherwise
        """
        if not self.config_file.exists():
            return None
            
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            return ProjectConfig.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Log error but don't crash
            print(f"Warning: Failed to load config: {e}")
            return None
            
    def save_config(self, config: ProjectConfig) -> None:
        """
        Save configuration to file with atomic write.
        
        Args:
            config: Configuration to save
        """
        self._ensure_config_dir()
        
        # Update timestamp
        config.updated_at = datetime.now()
        
        # Serialize to JSON
        config_data = config.to_dict()
        json_content = json.dumps(config_data, indent=2)
        
        # Atomic write with backup
        temp_file = self.config_file.with_suffix('.tmp')
        try:
            # Write to temporary file
            with open(temp_file, 'w') as f:
                f.write(json_content)
                
            # Create backup of existing config
            if self.config_file.exists():
                backup_file = self.config_file.with_suffix('.backup')
                shutil.copy2(self.config_file, backup_file)
                
            # Move temp file to actual config file
            temp_file.replace(self.config_file)
            
        except Exception as e:
            # Clean up temp file on error
            if temp_file.exists():
                temp_file.unlink()
            raise
            
    def get_config_status(self) -> ConfigurationStatus:
        """Get current configuration status."""
        has_config = self.config_file.exists()
        
        if not has_config:
            return ConfigurationStatus(
                is_configured=False,
                has_git_hooks=False,
                hooks_installed=[],
                config_path=str(self.config_file),
                last_modified=None
            )
            
        # Load config to check details
        config = self.load_config()
        if not config:
            return ConfigurationStatus(
                is_configured=False,
                has_git_hooks=False,
                hooks_installed=[],
                config_path=str(self.config_file),
                last_modified=datetime.fromtimestamp(self.config_file.stat().st_mtime)
            )
            
        # Check which hooks are configured
        configured_hooks = [h.hook_type for h in config.git_hooks if h.enabled]
        
        # Check version
        needs_migration = config.version != ConfigVersion.latest()
        
        return ConfigurationStatus(
            is_configured=True,
            has_git_hooks=len(configured_hooks) > 0,
            hooks_installed=configured_hooks,
            config_path=str(self.config_file),
            last_modified=config.updated_at,
            needs_migration=needs_migration,
            current_version=config.version
        )
        
    def backup_config(self) -> Optional[Path]:
        """
        Create a timestamped backup of current configuration.
        
        Returns:
            Path to backup file if created, None if no config exists
        """
        if not self.config_file.exists():
            return None
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"project_config_{timestamp}.json"
        backup_path = self.config_dir / "backups" / backup_name
        
        # Ensure backup directory exists
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy config file
        shutil.copy2(self.config_file, backup_path)
        
        return backup_path
        
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all configuration backups."""
        backup_dir = self.config_dir / "backups"
        if not backup_dir.exists():
            return []
            
        backups = []
        for backup_file in backup_dir.glob("project_config_*.json"):
            stat = backup_file.stat()
            backups.append({
                "filename": backup_file.name,
                "path": str(backup_file),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime)
            })
            
        # Sort by modified time, newest first
        backups.sort(key=lambda x: x["modified"], reverse=True)
        return backups
        
    def restore_backup(self, backup_path: str) -> None:
        """
        Restore configuration from backup.
        
        Args:
            backup_path: Path to backup file
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
            
        # Validate it's a valid config
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
            config = ProjectConfig.from_dict(data)  # Validate structure
        except Exception as e:
            raise ValueError(f"Invalid backup file: {e}")
            
        # Create backup of current config before restoring
        if self.config_file.exists():
            self.backup_config()
            
        # Write the config data directly (avoids timestamp update)
        self._ensure_config_dir()
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)
        
    def get_config_path(self) -> Path:
        """Get path to configuration file."""
        return self.config_file
        
    def remove_config(self) -> None:
        """Remove configuration file and directory."""
        if self.config_file.exists():
            # Create final backup
            self.backup_config()
            
            # Remove config file
            self.config_file.unlink()
            
        # Remove directory if empty
        if self.config_dir.exists() and not any(self.config_dir.iterdir()):
            self.config_dir.rmdir()