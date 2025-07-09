"""Tests for the application layer components."""

import os
import tempfile
import shutil
import sqlite3
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import pytest

from app import (
    DocumentationJob, JobStatus, ProcessedFile,
    JobStorage, FileDiscoveryService, DocumentationService
)
from storage.sqlite_storage import CodeQueryServer


class TestJobModels:
    """Test job model classes."""
    
    def test_documentation_job_creation(self):
        """Test creating a DocumentationJob with defaults."""
        job = DocumentationJob(
            dataset_name="test-dataset",
            project_root="/test/path"
        )
        
        assert job.job_id is not None
        assert job.dataset_name == "test-dataset"
        assert job.project_root == "/test/path"
        assert job.status == JobStatus.CREATED
        assert job.total_files == 0
        assert job.processed_files == 0
        assert job.failed_files == 0
        assert job.created_at is not None
        assert job.started_at is None
        assert job.completed_at is None
        
    def test_documentation_job_to_dict(self):
        """Test converting job to dictionary."""
        job = DocumentationJob(
            job_id="test-123",
            dataset_name="test-dataset",
            project_root="/test/path",
            total_files=10,
            processed_files=5
        )
        
        data = job.to_dict()
        assert data["job_id"] == "test-123"
        assert data["dataset_name"] == "test-dataset"
        assert data["total_files"] == 10
        assert data["processed_files"] == 5
        assert data["status"] == "created"
        
    def test_documentation_job_from_dict(self):
        """Test creating job from dictionary."""
        data = {
            "job_id": "test-123",
            "dataset_name": "test-dataset",
            "project_root": "/test/path",
            "status": "running",
            "total_files": 10,
            "processed_files": 5,
            "failed_files": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error_message": None,
            "file_filters": ["*.test"],
            "options": {"model": "sonnet"}
        }
        
        job = DocumentationJob.from_dict(data)
        assert job.job_id == "test-123"
        assert job.status == JobStatus.RUNNING
        assert job.file_filters == ["*.test"]
        assert job.options["model"] == "sonnet"
        
    def test_job_terminal_states(self):
        """Test is_terminal property."""
        job = DocumentationJob()
        
        # Non-terminal states
        job.status = JobStatus.CREATED
        assert not job.is_terminal
        
        job.status = JobStatus.RUNNING
        assert not job.is_terminal
        
        # Terminal states
        job.status = JobStatus.COMPLETED
        assert job.is_terminal
        
        job.status = JobStatus.FAILED
        assert job.is_terminal
        
        job.status = JobStatus.CANCELLED
        assert job.is_terminal
        
    def test_job_progress_percentage(self):
        """Test progress calculation."""
        job = DocumentationJob()
        
        # No files
        assert job.progress_percentage() == 0.0
        
        # Some progress
        job.total_files = 10
        job.processed_files = 3
        assert job.progress_percentage() == 30.0
        
        # Complete
        job.processed_files = 10
        assert job.progress_percentage() == 100.0


class TestJobStorage:
    """Test JobStorage class."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        os.unlink(path)
        
    @pytest.fixture
    def storage(self, temp_db):
        """Create JobStorage instance with temp database."""
        return JobStorage(temp_db)
        
    def test_schema_creation(self, storage, temp_db):
        """Test that schema is created correctly."""
        # Check tables exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        
        # Check documentation_jobs table
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='documentation_jobs'
        """)
        assert cursor.fetchone() is not None
        
        # Check job_processed_files table
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='job_processed_files'
        """)
        assert cursor.fetchone() is not None
        
        conn.close()
        
    def test_create_and_get_job(self, storage):
        """Test creating and retrieving a job."""
        job = DocumentationJob(
            dataset_name="test-dataset",
            project_root="/test/path",
            total_files=5
        )
        
        # Create job
        created_job = storage.create_job(job)
        assert created_job.job_id == job.job_id
        
        # Retrieve job
        retrieved_job = storage.get_job(job.job_id)
        assert retrieved_job is not None
        assert retrieved_job.dataset_name == "test-dataset"
        assert retrieved_job.total_files == 5
        
        # Non-existent job
        assert storage.get_job("non-existent") is None
        
    def test_update_job(self, storage):
        """Test updating job status."""
        job = DocumentationJob(dataset_name="test", project_root="/test")
        storage.create_job(job)
        
        # Update job
        job.status = JobStatus.RUNNING
        job.processed_files = 3
        job.started_at = datetime.now(timezone.utc)
        
        updated = storage.update_job(job)
        
        # Verify update
        retrieved = storage.get_job(job.job_id)
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.processed_files == 3
        assert retrieved.started_at is not None
        
    def test_start_job_atomic(self, storage):
        """Test atomic job start transition."""
        job = DocumentationJob(dataset_name="test", project_root="/test")
        storage.create_job(job)
        
        # Should succeed first time
        assert storage.start_job(job.job_id) is True
        
        # Should fail second time (already started)
        assert storage.start_job(job.job_id) is False
        
        # Check job was updated
        retrieved = storage.get_job(job.job_id)
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.started_at is not None
        
    def test_record_file_processed(self, storage):
        """Test recording file processing."""
        job = DocumentationJob(dataset_name="test", project_root="/test")
        storage.create_job(job)
        
        # Record successful file
        storage.record_file_processed(
            job_id=job.job_id,
            filepath="test.py",
            success=True,
            huey_task_id="task-123"
        )
        
        # Record failed file
        storage.record_file_processed(
            job_id=job.job_id,
            filepath="error.py",
            success=False,
            error_message="Syntax error"
        )
        
        # Check counters updated
        retrieved = storage.get_job(job.job_id)
        assert retrieved.processed_files == 1
        assert retrieved.failed_files == 1
        
        # Check processed files list
        processed = storage.get_processed_files_for_job(job.job_id)
        assert "test.py" in processed
        assert "error.py" not in processed  # Failed files not included
        
    def test_list_jobs(self, storage):
        """Test listing jobs with filters."""
        # Create multiple jobs
        job1 = DocumentationJob(dataset_name="dataset1", project_root="/test")
        job2 = DocumentationJob(dataset_name="dataset2", project_root="/test")
        job3 = DocumentationJob(
            dataset_name="dataset1", 
            project_root="/test",
            status=JobStatus.COMPLETED
        )
        
        storage.create_job(job1)
        storage.create_job(job2)
        storage.create_job(job3)
        
        # List all jobs
        all_jobs = storage.list_jobs()
        assert len(all_jobs) >= 3
        
        # Filter by dataset
        dataset1_jobs = storage.list_jobs(dataset_name="dataset1")
        assert len(dataset1_jobs) == 2
        
        # Filter by status
        completed_jobs = storage.list_jobs(status=JobStatus.COMPLETED)
        assert len(completed_jobs) >= 1
        
    def test_cancel_job(self, storage):
        """Test job cancellation."""
        job = DocumentationJob(dataset_name="test", project_root="/test")
        storage.create_job(job)
        storage.start_job(job.job_id)
        
        # Cancel running job
        assert storage.cancel_job(job.job_id) is True
        
        # Verify cancelled
        retrieved = storage.get_job(job.job_id)
        assert retrieved.status == JobStatus.CANCELLED
        assert retrieved.completed_at is not None
        assert "cancelled" in retrieved.error_message.lower()
        
        # Can't cancel again
        assert storage.cancel_job(job.job_id) is False


class TestFileDiscoveryService:
    """Test FileDiscoveryService class."""
    
    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure."""
        root = tempfile.mkdtemp()
        
        # Create test files
        os.makedirs(os.path.join(root, "src"))
        os.makedirs(os.path.join(root, "tests"))
        os.makedirs(os.path.join(root, "node_modules"))
        
        # Code files
        open(os.path.join(root, "main.py"), 'w').close()
        open(os.path.join(root, "src", "utils.py"), 'w').close()
        open(os.path.join(root, "src", "helper.js"), 'w').close()
        open(os.path.join(root, "tests", "test_main.py"), 'w').close()
        
        # Non-code files
        open(os.path.join(root, "README.md"), 'w').close()
        open(os.path.join(root, ".env"), 'w').close()
        open(os.path.join(root, "node_modules", "lib.js"), 'w').close()
        
        yield root
        shutil.rmtree(root)
        
    def test_discover_files_filesystem(self, temp_project):
        """Test file discovery using filesystem traversal."""
        discovery = FileDiscoveryService(temp_project)
        
        # Mock git failure to force filesystem discovery
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            
            files = discovery.discover_files()
            
        # Should find code files, exclude .env and node_modules
        assert "main.py" in files
        assert "src/utils.py" in files
        assert "src/helper.js" in files
        assert "tests/test_main.py" in files
        assert ".env" not in files
        assert "README.md" not in files
        assert "node_modules/lib.js" not in files
        
    def test_discover_files_with_patterns(self, temp_project):
        """Test file discovery with exclude patterns."""
        discovery = FileDiscoveryService(temp_project)
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()
            
            # Exclude tests
            files = discovery.discover_files(exclude_patterns=["tests/*"])
            
        assert "main.py" in files
        assert "src/utils.py" in files
        assert "tests/test_main.py" not in files
        
    @patch('subprocess.run')
    def test_discover_files_git(self, mock_run, temp_project):
        """Test file discovery using git ls-files."""
        discovery = FileDiscoveryService(temp_project)
        
        # Mock git ls-files output
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main.py\nsrc/utils.py\nsrc/helper.js\ntests/test_main.py\nREADME.md"
        mock_run.return_value = mock_result
        
        files = discovery.discover_files()
        
        # Should use git and filter by extension
        assert mock_run.called
        assert "main.py" in files
        assert "src/utils.py" in files
        assert "README.md" not in files  # Not a code extension
        
    def test_get_file_commit_hash(self, temp_project):
        """Test getting commit hash for files."""
        discovery = FileDiscoveryService(temp_project)
        
        with patch('subprocess.run') as mock_run:
            # Successful git log
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "abc123def456"
            mock_run.return_value = mock_result
            
            hash1 = discovery.get_file_commit_hash("main.py")
            assert hash1 == "abc123def456"
            
            # Failed git log
            mock_result.returncode = 1
            hash2 = discovery.get_file_commit_hash("new_file.py")
            assert hash2 == "uncommitted"


class TestDocumentationService:
    """Test DocumentationService orchestration."""
    
    @pytest.fixture
    def temp_project(self):
        """Create a temporary project with some files."""
        root = tempfile.mkdtemp()
        
        # Create test structure
        os.makedirs(os.path.join(root, "src"))
        open(os.path.join(root, "main.py"), 'w').close()
        open(os.path.join(root, "src", "utils.py"), 'w').close()
        
        yield root
        shutil.rmtree(root)
        
    @pytest.fixture
    def mock_storage(self, temp_project):
        """Create mock storage with real database."""
        # Use a real temporary database file
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        storage = Mock(spec=CodeQueryServer)
        storage.db_path = db_path
        storage.cwd = temp_project
        
        yield storage
        
        # Cleanup
        os.unlink(db_path)
        
    @patch('app.documentation_service.process_documentation_batch')
    @patch('app.documentation_service.get_project_config')
    def test_start_documentation_job(self, mock_config, mock_process_batch, 
                                   mock_storage, temp_project):
        """Test starting a new documentation job."""
        mock_config.return_value = {"model": "sonnet"}
        mock_process_batch.return_value = {"status": "enqueued"}
        
        service = DocumentationService(temp_project, mock_storage)
        
        # Start job
        job = service.start_documentation_job(
            dataset_name="test-dataset",
            directory=".",
            batch_size=2
        )
        
        assert job.dataset_name == "test-dataset"
        assert job.total_files == 2  # main.py and src/utils.py
        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None
        
        # Check batch was submitted
        assert mock_process_batch.called
        call_args = mock_process_batch.call_args[1]
        assert call_args["dataset_name"] == "test-dataset"
        assert call_args["job_id"] == job.job_id
        assert len(call_args["files"]) == 2
        
    def test_start_job_no_files(self, mock_storage, temp_project):
        """Test starting job with no files raises error."""
        service = DocumentationService(temp_project, mock_storage)
        
        with pytest.raises(ValueError, match="No code files found"):
            service.start_documentation_job(
                dataset_name="test",
                directory="nonexistent"
            )
            
    @patch('app.documentation_service.process_documentation_batch')
    def test_resume_job(self, mock_process_batch, mock_storage, temp_project):
        """Test resuming an interrupted job."""
        service = DocumentationService(temp_project, mock_storage)
        
        # Create a job with some files already processed
        job = DocumentationJob(
            job_id="test-123",
            dataset_name="test-dataset",
            project_root=temp_project,
            total_files=2,
            processed_files=1,
            status=JobStatus.RUNNING
        )
        
        # Mock job storage to return our job
        service.job_storage.get_job = Mock(return_value=job)
        service.job_storage.get_processed_files_for_job = Mock(
            return_value=["main.py"]  # One file already done
        )
        
        # Resume job
        resumed = service.resume_job("test-123")
        
        assert resumed is not None
        assert resumed.status == JobStatus.RUNNING
        
        # Should only submit remaining file
        assert mock_process_batch.called
        call_args = mock_process_batch.call_args[1]
        assert len(call_args["files"]) == 1
        assert call_args["files"][0]["filepath"] == "src/utils.py"
        
    def test_resume_completed_job(self, mock_storage, temp_project):
        """Test resuming a job with no remaining files marks it complete."""
        service = DocumentationService(temp_project, mock_storage)
        
        job = DocumentationJob(
            job_id="test-123",
            dataset_name="test-dataset",
            project_root=temp_project,
            total_files=2,
            processed_files=2,
            status=JobStatus.RUNNING
        )
        
        service.job_storage.get_job = Mock(return_value=job)
        service.job_storage.get_processed_files_for_job = Mock(
            return_value=["main.py", "src/utils.py"]  # All done
        )
        service.job_storage.update_job = Mock(return_value=job)
        
        resumed = service.resume_job("test-123")
        
        assert resumed.status == JobStatus.COMPLETED
        assert resumed.completed_at is not None
        
    def test_get_progress(self, mock_storage):
        """Test getting job progress."""
        service = DocumentationService("/test", mock_storage)
        
        job = DocumentationJob(
            job_id="test-123",
            total_files=10,
            processed_files=3,
            failed_files=1,
            status=JobStatus.RUNNING
        )
        
        service.job_storage.get_job = Mock(return_value=job)
        
        progress = service.get_progress("test-123")
        
        assert progress["total_files"] == 10
        assert progress["processed_files"] == 3
        assert progress["failed_files"] == 1
        assert progress["progress_percentage"] == 30.0
        assert progress["is_complete"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])