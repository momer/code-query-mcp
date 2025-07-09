"""Simplified tests focusing on key app layer functionality."""

import tempfile
import os
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from app import (
    DocumentationJob, JobStatus, JobStorage,
    FileDiscoveryService, DocumentationService
)


def test_documentation_job_workflow():
    """Test basic job workflow."""
    job = DocumentationJob(
        dataset_name="test",
        project_root="/test",
        total_files=10
    )
    
    # Initial state
    assert job.status == JobStatus.CREATED
    assert job.can_resume is True
    assert job.is_terminal is False
    assert job.progress_percentage() == 0.0
    
    # Start job
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    assert job.can_resume is True
    
    # Make progress
    job.processed_files = 5
    assert job.progress_percentage() == 50.0
    
    # Complete job
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(timezone.utc)
    job.processed_files = 10
    assert job.is_terminal is True
    assert job.can_resume is False
    assert job.progress_percentage() == 100.0


def test_job_storage_lifecycle():
    """Test job storage operations."""
    # Create temporary database
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    try:
        storage = JobStorage(db_path)
        
        # Create job
        job = DocumentationJob(
            dataset_name="test",
            project_root="/test",
            total_files=2
        )
        created = storage.create_job(job)
        assert created.job_id == job.job_id
        
        # Start job atomically
        assert storage.start_job(job.job_id) is True
        assert storage.start_job(job.job_id) is False  # Can't start twice
        
        # Record file processing
        storage.record_file_processed(
            job_id=job.job_id,
            filepath="test1.py",
            success=True
        )
        storage.record_file_processed(
            job_id=job.job_id,
            filepath="test2.py",
            success=False,
            error_message="Syntax error"
        )
        
        # Check updated job
        updated = storage.get_job(job.job_id)
        assert updated.processed_files == 1
        assert updated.failed_files == 1
        
        # Check processed files list
        processed = storage.get_processed_files_for_job(job.job_id)
        assert len(processed) == 1
        assert "test1.py" in processed
        
    finally:
        os.unlink(db_path)


def test_file_discovery_with_mock():
    """Test file discovery with mocked git."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        os.makedirs(os.path.join(tmpdir, "src"))
        open(os.path.join(tmpdir, "main.py"), 'w').close()
        open(os.path.join(tmpdir, "src", "utils.py"), 'w').close()
        open(os.path.join(tmpdir, "README.md"), 'w').close()
        
        discovery = FileDiscoveryService(tmpdir)
        
        # Mock git failure to force filesystem discovery
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            
            files = discovery.discover_files()
            
            # Should find Python files only
            assert len(files) == 2
            assert "main.py" in files
            assert "src/utils.py" in files
            assert "README.md" not in files


@patch('app.documentation_service.get_project_config')
def test_documentation_service_with_mocks(mock_config):
    """Test DocumentationService with all dependencies mocked."""
    mock_config.return_value = {"model": "sonnet"}
    
    # Create mocks
    mock_storage = Mock()
    mock_storage.db_path = ":memory:"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        service = DocumentationService(tmpdir, mock_storage)
        
        # Mock file discovery
        mock_files = ["file1.py", "file2.py"]
        service.discovery.discover_files = Mock(return_value=mock_files)
        
        # Mock job storage
        mock_job_storage = Mock()
        service.job_storage = mock_job_storage
        mock_job_storage.create_job.return_value = DocumentationJob(
            job_id="test-123",
            dataset_name="test",
            project_root=tmpdir,
            total_files=2
        )
        mock_job_storage.start_job.return_value = True
        
        # Mock Huey submission
        with patch('app.documentation_service.process_documentation_batch') as mock_batch:
            mock_batch.return_value = {"status": "enqueued"}
            
            # Start job
            job = service.start_documentation_job(
                dataset_name="test",
                batch_size=2
            )
            
            assert job is not None
            assert job.total_files == 2
            assert mock_batch.called
            
            # Verify batch submission
            call_args = mock_batch.call_args[1]
            assert len(call_args["files"]) == 2
            assert call_args["dataset_name"] == "test"
            assert call_args["job_id"] == "test-123"


def test_progress_tracking():
    """Test job progress calculation."""
    job = DocumentationJob(total_files=0)
    assert job.progress_percentage() == 0.0
    
    job.total_files = 10
    job.processed_files = 0
    assert job.progress_percentage() == 0.0
    
    job.processed_files = 3
    assert job.progress_percentage() == 30.0
    
    job.processed_files = 10
    assert job.progress_percentage() == 100.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])