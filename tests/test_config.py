"""Tests for configuration management module."""

import unittest
import tempfile
import shutil
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from config.project_config import (
    ConfigVersion, HookType, GitHookConfig, 
    ProjectConfig, ConfigurationStatus
)
from config.config_storage import ConfigStorage
from config.config_validator import ConfigValidator
from config.git_hooks import GitHookManager
from config.config_service import ConfigurationService


class TestProjectConfig(unittest.TestCase):
    """Test configuration models."""
    
    def test_create_default_config(self):
        """Test creating default configuration."""
        config = ProjectConfig.create_default("test-project")
        
        self.assertEqual(config.project_name, "test-project")
        self.assertEqual(config.version, ConfigVersion.V1)
        self.assertIsInstance(config.created_at, datetime)
        self.assertIsInstance(config.updated_at, datetime)
        self.assertEqual(len(config.git_hooks), 0)
        self.assertIsNone(config.default_dataset)
        self.assertTrue(config.enable_analytics)
        
    def test_config_serialization(self):
        """Test configuration to/from dict."""
        config = ProjectConfig.create_default("test-project")
        config.default_dataset = "test-dataset"
        
        # Add a git hook
        hook = GitHookConfig(
            hook_type=HookType.PRE_COMMIT,
            enabled=True,
            mode="queue",
            dataset_name="test-dataset"
        )
        config.git_hooks.append(hook)
        
        # Serialize
        config_dict = config.to_dict()
        
        # Deserialize
        restored = ProjectConfig.from_dict(config_dict)
        
        self.assertEqual(restored.project_name, config.project_name)
        self.assertEqual(restored.version, config.version)
        self.assertEqual(restored.default_dataset, config.default_dataset)
        self.assertEqual(len(restored.git_hooks), 1)
        self.assertEqual(restored.git_hooks[0].hook_type, HookType.PRE_COMMIT)
        
    def test_git_hook_config(self):
        """Test GitHookConfig model."""
        hook = GitHookConfig(
            hook_type=HookType.POST_MERGE,
            enabled=False,
            mode="async",
            dataset_name="branch-dataset"
        )
        
        # Test to_dict
        hook_dict = hook.to_dict()
        self.assertEqual(hook_dict["hook_type"], "post-merge")
        self.assertFalse(hook_dict["enabled"])
        self.assertEqual(hook_dict["mode"], "async")
        
        # Test from_dict
        restored = GitHookConfig.from_dict(hook_dict)
        self.assertEqual(restored.hook_type, HookType.POST_MERGE)
        self.assertFalse(restored.enabled)
        
    def test_configuration_status(self):
        """Test ConfigurationStatus model."""
        status = ConfigurationStatus(
            is_configured=True,
            has_git_hooks=True,
            hooks_installed=[HookType.PRE_COMMIT],
            config_path="/test/path/config.json",
            last_modified=datetime.now(),
            needs_migration=False,
            current_version=ConfigVersion.V1
        )
        
        status_dict = status.to_dict()
        self.assertTrue(status_dict["is_configured"])
        self.assertEqual(status_dict["hooks_installed"], ["pre-commit"])
        self.assertEqual(status_dict["current_version"], "1.0")


class TestConfigStorage(unittest.TestCase):
    """Test configuration storage operations."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.storage = ConfigStorage(self.test_dir)
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)
        
    def test_save_and_load_config(self):
        """Test saving and loading configuration."""
        # Create config
        config = ProjectConfig.create_default("test-project")
        config.default_dataset = "test-data"
        
        # Save
        self.storage.save_config(config)
        
        # Verify file exists
        self.assertTrue(self.storage.config_file.exists())
        
        # Load
        loaded = self.storage.load_config()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.project_name, "test-project")
        self.assertEqual(loaded.default_dataset, "test-data")
        
    def test_atomic_write(self):
        """Test atomic write with backup."""
        # Create initial config
        config1 = ProjectConfig.create_default("project-v1")
        self.storage.save_config(config1)
        
        # Update config
        config2 = ProjectConfig.create_default("project-v2")
        self.storage.save_config(config2)
        
        # Check backup exists
        backup_file = self.storage.config_file.with_suffix('.backup')
        self.assertTrue(backup_file.exists())
        
        # Verify backup contains old config
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        self.assertEqual(backup_data["project_name"], "project-v1")
        
    def test_config_status(self):
        """Test getting configuration status."""
        # No config
        status = self.storage.get_config_status()
        self.assertFalse(status.is_configured)
        self.assertIsNone(status.last_modified)
        
        # With config
        config = ProjectConfig.create_default("test")
        self.storage.save_config(config)
        
        status = self.storage.get_config_status()
        self.assertTrue(status.is_configured)
        self.assertIsNotNone(status.last_modified)
        self.assertEqual(status.current_version, ConfigVersion.V1)
        
    def test_backup_operations(self):
        """Test backup creation and listing."""
        # Create config
        config = ProjectConfig.create_default("test")
        self.storage.save_config(config)
        
        # Create backup
        backup_path = self.storage.backup_config()
        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())
        
        # List backups
        backups = self.storage.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertIn("project_config_", backups[0]["filename"])
        
    def test_restore_backup(self):
        """Test restoring from backup."""
        # Create initial config
        config1 = ProjectConfig.create_default("original")
        self.storage.save_config(config1)
        
        # Create backup
        backup_path = self.storage.backup_config()
        
        # Modify config
        config2 = ProjectConfig.create_default("modified")
        self.storage.save_config(config2)
        
        # Restore backup
        self.storage.restore_backup(str(backup_path))
        
        # Load and verify
        restored = self.storage.load_config()
        self.assertEqual(restored.project_name, "original")


class TestConfigValidator(unittest.TestCase):
    """Test configuration validation."""
    
    def setUp(self):
        """Set up validator."""
        self.validator = ConfigValidator()
        
    def test_valid_config(self):
        """Test validation of valid configuration."""
        config = ProjectConfig.create_default("valid-project")
        is_valid, errors = self.validator.validate_config(config)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
        
    def test_invalid_project_name(self):
        """Test validation with invalid project name."""
        config = ProjectConfig.create_default("")
        is_valid, errors = self.validator.validate_config(config)
        
        self.assertFalse(is_valid)
        self.assertIn("Project name cannot be empty", errors)
        
    def test_invalid_file_extensions(self):
        """Test validation with invalid file extensions."""
        config = ProjectConfig.create_default("test")
        config.file_extensions = [".py", "invalid", ".js"]
        
        is_valid, errors = self.validator.validate_config(config)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Invalid file extension: invalid" in e for e in errors))
        
    def test_invalid_file_size(self):
        """Test validation with invalid file size."""
        config = ProjectConfig.create_default("test")
        config.max_file_size_mb = -5
        
        is_valid, errors = self.validator.validate_config(config)
        
        self.assertFalse(is_valid)
        self.assertIn("Max file size must be positive", errors)
        
    def test_duplicate_git_hooks(self):
        """Test validation with duplicate git hooks."""
        config = ProjectConfig.create_default("test")
        hook1 = GitHookConfig(hook_type=HookType.PRE_COMMIT)
        hook2 = GitHookConfig(hook_type=HookType.PRE_COMMIT)
        config.git_hooks = [hook1, hook2]
        
        is_valid, errors = self.validator.validate_config(config)
        
        self.assertFalse(is_valid)
        self.assertIn("Duplicate git hook: pre-commit", errors)
        
    def test_suggest_configuration(self):
        """Test configuration suggestions."""
        # Create temp Python project
        test_dir = tempfile.mkdtemp()
        try:
            Path(test_dir, "setup.py").touch()
            
            suggestions = self.validator.suggest_configuration(test_dir)
            
            self.assertIn("__pycache__", suggestions["ignored_patterns"])
            self.assertIn(".py", suggestions["file_extensions"])
            
        finally:
            shutil.rmtree(test_dir)


class TestGitHookManager(unittest.TestCase):
    """Test git hook management."""
    
    def setUp(self):
        """Set up test git repository."""
        self.test_dir = tempfile.mkdtemp()
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=self.test_dir, capture_output=True)
        self.hook_manager = GitHookManager(self.test_dir)
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)
        
    def test_find_git_dir(self):
        """Test finding git directory."""
        self.assertIsNotNone(self.hook_manager.git_dir)
        self.assertTrue(self.hook_manager.git_dir.exists())
        
    def test_install_hook(self):
        """Test installing a git hook."""
        config = GitHookConfig(
            hook_type=HookType.PRE_COMMIT,
            dataset_name="test-dataset"
        )
        
        success, message = self.hook_manager.install_hook(config)
        
        self.assertTrue(success)
        hook_path = self.hook_manager._get_hook_path(HookType.PRE_COMMIT)
        self.assertTrue(hook_path.exists())
        
        # Verify content
        content = hook_path.read_text()
        self.assertIn("[Code Query]", content)
        
    def test_remove_hook(self):
        """Test removing a git hook."""
        # Install first
        config = GitHookConfig(hook_type=HookType.PRE_COMMIT)
        self.hook_manager.install_hook(config)
        
        # Remove
        success, message = self.hook_manager.remove_hook(HookType.PRE_COMMIT)
        
        self.assertTrue(success)
        
        # Verify it's no longer a Code Query hook
        installed = self.hook_manager.get_installed_hooks()
        self.assertNotIn(HookType.PRE_COMMIT, installed)
        
    def test_get_installed_hooks(self):
        """Test listing installed hooks."""
        # Install multiple hooks
        for hook_type in [HookType.PRE_COMMIT, HookType.POST_MERGE]:
            config = GitHookConfig(hook_type=hook_type)
            self.hook_manager.install_hook(config)
            
        installed = self.hook_manager.get_installed_hooks()
        
        self.assertEqual(len(installed), 2)
        self.assertIn(HookType.PRE_COMMIT, installed)
        self.assertIn(HookType.POST_MERGE, installed)
        
    def test_validate_hook(self):
        """Test hook validation."""
        # No hook
        is_valid, error = self.hook_manager.validate_hook(HookType.PRE_COMMIT)
        self.assertFalse(is_valid)
        
        # Install hook
        config = GitHookConfig(hook_type=HookType.PRE_COMMIT)
        self.hook_manager.install_hook(config)
        
        # Should be valid
        is_valid, error = self.hook_manager.validate_hook(HookType.PRE_COMMIT)
        self.assertTrue(is_valid)
        self.assertIsNone(error)


class TestConfigurationService(unittest.TestCase):
    """Test main configuration service."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=self.test_dir, capture_output=True)
        self.service = ConfigurationService(self.test_dir)
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)
        
    def test_create_config(self):
        """Test creating new configuration."""
        config = self.service.create_config(
            "test-project",
            default_dataset="main-dataset",
            enable_analytics=False
        )
        
        self.assertEqual(config.project_name, "test-project")
        self.assertEqual(config.default_dataset, "main-dataset")
        self.assertFalse(config.enable_analytics)
        
        # Verify saved
        loaded = self.service.get_config()
        self.assertEqual(loaded.project_name, "test-project")
        
    def test_update_config(self):
        """Test updating configuration."""
        # Create initial
        self.service.create_config("test")
        
        # Update
        updated = self.service.update_config({
            "default_dataset": "new-dataset",
            "max_file_size_mb": 20
        })
        
        self.assertEqual(updated.default_dataset, "new-dataset")
        self.assertEqual(updated.max_file_size_mb, 20)
        
    def test_install_and_remove_hook(self):
        """Test installing and removing git hooks."""
        # Create config
        self.service.create_config("test")
        
        # Install hook
        success, message = self.service.install_git_hook(
            HookType.PRE_COMMIT,
            dataset_name="test-data"
        )
        self.assertTrue(success)
        
        # Verify in config
        config = self.service.get_config()
        self.assertEqual(len(config.git_hooks), 1)
        self.assertEqual(config.git_hooks[0].dataset_name, "test-data")
        
        # Remove hook
        success, message = self.service.remove_git_hook(HookType.PRE_COMMIT)
        self.assertTrue(success)
        
        # Verify removed from config
        config = self.service.get_config()
        self.assertEqual(len(config.git_hooks), 0)
        
    def test_environment_overrides(self):
        """Test environment variable overrides."""
        # Set environment variables
        import os
        os.environ["CODEQUERY_DEFAULT_DATASET"] = "env-dataset"
        os.environ["CODEQUERY_ENABLE_ANALYTICS"] = "false"
        
        try:
            # Create config
            self.service.create_config("test")
            
            # Apply overrides
            self.service.apply_environment_overrides()
            
            config = self.service.get_config()
            self.assertEqual(config.default_dataset, "env-dataset")
            self.assertFalse(config.enable_analytics)
            
        finally:
            # Clean up env vars
            del os.environ["CODEQUERY_DEFAULT_DATASET"]
            del os.environ["CODEQUERY_ENABLE_ANALYTICS"]
            
    def test_export_import_config(self):
        """Test exporting and importing configuration."""
        # Create config
        config = self.service.create_config(
            "export-test",
            default_dataset="test-data"
        )
        
        # Export
        export_path = Path(self.test_dir) / "exported.json"
        self.service.export_config(str(export_path))
        self.assertTrue(export_path.exists())
        
        # Clear current config
        self.service._config = None
        
        # Import
        imported = self.service.import_config(str(export_path))
        self.assertEqual(imported.project_name, "export-test")
        self.assertEqual(imported.default_dataset, "test-data")


if __name__ == "__main__":
    import subprocess
    unittest.main()