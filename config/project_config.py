"""Configuration models and DTOs for Code Query MCP."""

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
        return cls.V1  # Start with V1 as latest


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
    auto_document: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hook_type": self.hook_type.value,
            "enabled": self.enabled,
            "mode": self.mode,
            "dataset_name": self.dataset_name,
            "auto_document": self.auto_document
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GitHookConfig':
        """Create from dictionary."""
        return cls(
            hook_type=HookType(data["hook_type"]),
            enabled=data.get("enabled", True),
            mode=data.get("mode", "queue"),
            dataset_name=data.get("dataset_name"),
            auto_document=data.get("auto_document", True)
        )


@dataclass
class ProjectConfig:
    """Main project configuration."""
    project_name: str
    version: ConfigVersion
    created_at: datetime
    updated_at: datetime
    git_hooks: List[GitHookConfig] = field(default_factory=list)
    default_dataset: Optional[str] = None
    ignored_patterns: List[str] = field(default_factory=lambda: [
        "__pycache__",
        "*.pyc",
        ".git",
        ".env",
        "venv",
        "node_modules",
        "*.log"
    ])
    file_extensions: List[str] = field(default_factory=lambda: [
        ".py", ".js", ".ts", ".tsx", ".jsx",
        ".java", ".cpp", ".c", ".h", ".hpp",
        ".go", ".rs", ".rb", ".php", ".swift"
    ])
    max_file_size_mb: int = 10
    enable_analytics: bool = True
    analytics_retention_days: int = 90
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "project_name": self.project_name,
            "version": self.version.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "git_hooks": [hook.to_dict() for hook in self.git_hooks],
            "default_dataset": self.default_dataset,
            "ignored_patterns": self.ignored_patterns,
            "file_extensions": self.file_extensions,
            "max_file_size_mb": self.max_file_size_mb,
            "enable_analytics": self.enable_analytics,
            "analytics_retention_days": self.analytics_retention_days
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectConfig':
        """Create from dictionary."""
        return cls(
            project_name=data["project_name"],
            version=ConfigVersion(data["version"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            git_hooks=[GitHookConfig.from_dict(h) for h in data.get("git_hooks", [])],
            default_dataset=data.get("default_dataset"),
            ignored_patterns=data.get("ignored_patterns", cls.__dataclass_fields__["ignored_patterns"].default_factory()),
            file_extensions=data.get("file_extensions", cls.__dataclass_fields__["file_extensions"].default_factory()),
            max_file_size_mb=data.get("max_file_size_mb", 10),
            enable_analytics=data.get("enable_analytics", True),
            analytics_retention_days=data.get("analytics_retention_days", 90)
        )
    
    @classmethod
    def create_default(cls, project_name: str) -> 'ProjectConfig':
        """Create default configuration for a project."""
        now = datetime.now()
        return cls(
            project_name=project_name,
            version=ConfigVersion.latest(),
            created_at=now,
            updated_at=now
        )


@dataclass
class ConfigurationStatus:
    """Status of project configuration."""
    is_configured: bool
    has_git_hooks: bool
    hooks_installed: List[HookType]
    config_path: str
    last_modified: Optional[datetime]
    needs_migration: bool = False
    current_version: Optional[ConfigVersion] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_configured": self.is_configured,
            "has_git_hooks": self.has_git_hooks,
            "hooks_installed": [h.value for h in self.hooks_installed],
            "config_path": self.config_path,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "needs_migration": self.needs_migration,
            "current_version": self.current_version.value if self.current_version else None
        }