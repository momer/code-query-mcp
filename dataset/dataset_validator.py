"""Validates dataset operations."""

import os
import re
from typing import Optional
from pathlib import Path

from .dataset_models import DatasetValidationError


class DatasetValidator:
    """Validates dataset operations."""
    
    # Valid dataset name pattern
    DATASET_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')
    MAX_DATASET_NAME_LENGTH = 100
    
    def validate_dataset_name(self, name: str) -> None:
        """
        Validate dataset name format.
        
        Args:
            name: Dataset name to validate
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if not name:
            raise DatasetValidationError("name", name, "Dataset name cannot be empty")
        
        if len(name) > self.MAX_DATASET_NAME_LENGTH:
            raise DatasetValidationError(
                "name", name, 
                f"Dataset name cannot exceed {self.MAX_DATASET_NAME_LENGTH} characters"
            )
        
        if not self.DATASET_NAME_PATTERN.match(name):
            raise DatasetValidationError(
                "name", name,
                "Dataset name must start with alphanumeric and contain only "
                "alphanumeric, underscore, or hyphen characters"
            )
        
        # Reserved names
        reserved = {'test', 'temp', 'tmp', 'cache', 'system'}
        if name.lower() in reserved:
            raise DatasetValidationError(
                "name", name,
                f"'{name}' is a reserved dataset name"
            )
    
    def validate_source_directory(self, directory: str) -> None:
        """
        Validate source directory exists and is readable.
        
        Args:
            directory: Directory path to validate
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if not directory:
            raise DatasetValidationError(
                "directory", directory,
                "Source directory cannot be empty"
            )
        
        path = Path(directory)
        
        if not path.exists():
            raise DatasetValidationError(
                "directory", directory,
                "Source directory does not exist"
            )
        
        if not path.is_dir():
            raise DatasetValidationError(
                "directory", directory,
                "Source path is not a directory"
            )
        
        if not os.access(directory, os.R_OK):
            raise DatasetValidationError(
                "directory", directory,
                "Source directory is not readable"
            )
    
    def validate_parent_dataset(self, 
                               parent_id: Optional[str],
                               dataset_type: str) -> None:
        """
        Validate parent dataset requirements.
        
        Args:
            parent_id: Parent dataset ID
            dataset_type: Type of dataset being created
            
        Raises:
            DatasetValidationError: If validation fails
        """
        if dataset_type in ('fork', 'worktree') and not parent_id:
            raise DatasetValidationError(
                "parent_id", parent_id,
                f"Dataset type '{dataset_type}' requires a parent dataset"
            )
        
        if parent_id:
            self.validate_dataset_name(parent_id)