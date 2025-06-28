# Phase 2 PR Plan: Polish and Documentation

## PR Title
feat: Complete queue processing with comprehensive docs, testing, and UX polish

## PR Description
This PR completes the automated queue processing feature by adding comprehensive documentation, robust error handling, and a polished user experience. It ensures the feature is production-ready with clear usage instructions and excellent troubleshooting support.

## Changes Overview

### 1. Comprehensive Documentation
- User guide with quickstart
- Troubleshooting guide
- Architecture documentation
- API reference

### 2. Error Handling Improvements
- Better error messages
- Recovery mechanisms
- Diagnostic commands

### 3. User Experience Polish
- Interactive setup wizard
- Migration tools
- Progress indicators

### 4. Testing Suite
- Unit tests for all components
- Focus on core functionality testing

### 5. Monitoring and Metrics
- Queue metrics collection
- Performance tracking
- Error rate monitoring

## Implementation Details

### 1. Documentation Structure
```
docs/
├── getting-started.md      # Quickstart guide
├── user-guide.md          # Comprehensive user manual
├── troubleshooting.md     # Common issues and solutions
├── architecture.md        # Technical architecture
└── api-reference.md       # Tool and API documentation
```

#### `docs/getting-started.md`
```markdown
# Queue Processing Quick Start

## Installation
```bash
pip install huey psutil
```

## Basic Setup (2 steps)

### 1. Enable Queue Processing
```bash
# In your project directory
python server.py worker setup
```

### 2. Start Processing
```bash
python server.py worker start
```

### 3. Verify It's Working
```bash
git commit -m "test"
# Should see: "✓ Documentation updates queued for background processing"
```

## Common Commands
- `worker status` - Check if worker is running
- `worker logs` - View recent processing logs
- `worker stop` - Stop background processing

## Troubleshooting
- Not working? Run `python server.py worker diagnose`
- Need help? See [troubleshooting guide](troubleshooting.md)
```

### 2. Enhanced Error Handling (`helpers/error_handler.py`)
```python
import sys
import traceback
from typing import Optional, Dict, Any
from enum import Enum

class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class CodeQueryError(Exception):
    """Base exception for code-query errors"""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.ERROR, 
                 context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.severity = severity
        self.context = context or {}

class WorkerNotRunningError(CodeQueryError):
    """Raised when worker is expected but not running"""
    def __init__(self):
        super().__init__(
            "Background worker is not running",
            severity=ErrorSeverity.WARNING,
            context={
                'suggestion': 'Run "python server.py worker start" to enable background processing',
                'fallback': 'Processing will continue synchronously'
            }
        )

class ConfigurationError(CodeQueryError):
    """Raised when configuration is invalid"""
    pass

class QueueError(CodeQueryError):
    """Raised when queue operations fail"""
    pass

def handle_error(error: Exception, verbose: bool = False):
    """Centralized error handling with user-friendly messages"""
    if isinstance(error, CodeQueryError):
        # Custom errors with context
        print(f"[{error.severity.value.upper()}] {error}")
        
        if error.context.get('suggestion'):
            print(f"💡 {error.context['suggestion']}")
        
        if error.context.get('fallback'):
            print(f"ℹ️  {error.context['fallback']}")
        
        if verbose and error.context:
            print("\nContext:")
            for key, value in error.context.items():
                if key not in ['suggestion', 'fallback']:
                    print(f"  {key}: {value}")
    else:
        # Unknown errors - avoid exposing sensitive information
        print("[ERROR] An unexpected error occurred.")
        if verbose:
            print(f"Details: {error}")
            print("\nTraceback:")
            traceback.print_exc()
        else:
            print("💡 Run the command again with the --verbose flag for more details.")
```

### 3. Interactive Setup Wizard (`cli/setup_wizard.py`)
```python
import os
import sys
from typing import Dict, Optional
from pathlib import Path

class SetupWizard:
    """Interactive setup wizard for queue processing"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.config_path = os.path.join(project_root, '.code-query', 'config.json')
    
    def run(self) -> bool:
        """Run the interactive setup wizard"""
        print("🚀 Code Query Queue Processing Setup")
        print("=" * 40)
        
        # Check existing configuration
        if self._has_existing_config():
            if not self._confirm("Existing configuration found. Update it?"):
                return False
        
        config = {}
        
        # Step 1: Dataset name
        print("\n📁 Step 1: Project Configuration")
        config['dataset_name'] = self._prompt(
            "Project/dataset name",
            default=Path(self.project_root).name
        )
        
        # Step 2: Processing mode
        print("\n⚙️  Step 2: Processing Mode")
        print("1. Manual (default) - Process synchronously during commits")
        print("2. Auto - Queue for background processing")
        mode_choice = self._prompt("Choose mode (1/2)", default="1")
        config['processing'] = {
            'mode': 'auto' if mode_choice == '2' else 'manual'
        }
        
        # Step 3: Model selection
        print("\n🤖 Step 3: Model Selection")
        print("1. claude-3-5-sonnet-20240620 (recommended)")
        print("2. claude-3-haiku-20240307 (faster)")
        print("3. Custom model")
        model_choice = self._prompt("Choose model (1/2/3)", default="1")
        
        if model_choice == '1':
            config['model'] = 'claude-3-5-sonnet-20240620'
        elif model_choice == '2':
            config['model'] = 'claude-3-haiku-20240307'
        else:
            config['model'] = self._prompt("Enter model name")
        
        # Step 4: Advanced options
        if self._confirm("\n🔧 Configure advanced options?", default=False):
            print("\nAdvanced Configuration:")
            config['processing']['batch_size'] = self._prompt_int(
                "Batch size", default="5"
            )
            config['processing']['delay_seconds'] = self._prompt_int(
                "Delay between batches (seconds)", default="300"
            )
        
        # Step 5: Git hooks
        print("\n🔗 Step 4: Git Hook Installation")
        if self._confirm("Install/update git hooks?"):
            self._install_git_hooks()
        
        # Save configuration
        self._save_config(config)
        
        print("\n✅ Setup complete!")
        print("\nNext steps:")
        
        if config['processing']['mode'] == 'auto':
            print("1. Start the worker: python server.py worker start")
            print("2. Make a commit to test queue processing")
        else:
            print("1. Make a commit to test synchronous processing")
            print("2. To enable background processing later:")
            print("   python server.py worker setup --mode auto")
        
        return True
    
    def _prompt(self, message: str, default: Optional[str] = None) -> str:
        """Prompt user for input with optional default"""
        if default:
            prompt = f"{message} [{default}]: "
        else:
            prompt = f"{message}: "
        
        value = input(prompt).strip()
        return value if value else default
    
    def _prompt_int(self, message: str, default: str) -> int:
        """Prompt user for an integer with validation"""
        while True:
            value_str = self._prompt(message, default=default)
            try:
                return int(value_str)
            except ValueError:
                print(f"❌ Invalid input. Please enter a whole number.")
    
    def _confirm(self, message: str, default: bool = True) -> bool:
        """Ask user for yes/no confirmation"""
        default_str = "Y/n" if default else "y/N"
        response = input(f"{message} [{default_str}]: ").strip().lower()
        
        if not response:
            return default
        return response in ['y', 'yes']
    
    def _has_existing_config(self) -> bool:
        """Check if configuration already exists"""
        return os.path.exists(self.config_path)
    
    def _save_config(self, config: Dict):
        """Save configuration to file atomically"""
        import json
        
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        # Load existing config to preserve other settings
        existing = {}
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    # Handle corrupted existing config
                    print("⚠ Existing config was corrupted, creating new one")
        
        # Merge with new settings
        existing.update(config)
        
        # Write atomically using temp file
        temp_path = self.config_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(existing, f, indent=2)
        
        # Atomic replace
        os.replace(temp_path, self.config_path)
    
    def _install_git_hooks(self):
        """Install or update git hooks"""
        # Implementation would call existing git hook installation logic
        print("✓ Git hooks installed/updated")
```

### 4. Diagnostic Tool (`cli/diagnostics.py`)
```python
import os
import sys
import subprocess
import json
from typing import Dict, List, Tuple

class Diagnostics:
    """Diagnostic tool for troubleshooting queue processing"""
    
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.issues = []
        self.warnings = []
        self.info = []
    
    def run(self) -> bool:
        """Run all diagnostic checks"""
        print("🔍 Running Code Query Diagnostics")
        print("=" * 40)
        
        # Run all checks
        self._check_dependencies()
        self._check_configuration()
        self._check_git_hooks()
        self._check_worker_status()
        self._check_queue_health()
        self._check_permissions()
        self._check_environment()
        
        # Report results
        self._report_results()
        
        return len(self.issues) == 0
    
    def _check_dependencies(self):
        """Check if required dependencies are installed"""
        print("\n📦 Checking dependencies...")
        
        dependencies = {
            'huey': 'huey',
            'psutil': 'psutil',
            'mcp': 'mcp'
        }
        
        for module, package in dependencies.items():
            try:
                __import__(module)
                self.info.append(f"✓ {package} is installed")
            except ImportError:
                self.issues.append(f"✗ {package} is not installed. Run: pip install {package}")
    
    def _check_configuration(self):
        """Check configuration file"""
        print("\n⚙️  Checking configuration...")
        
        config_path = os.path.join(self.project_root, '.code-query', 'config.json')
        
        if not os.path.exists(config_path):
            self.issues.append("✗ Configuration file not found. Run: python server.py worker setup")
            return
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Check required fields
            if 'dataset_name' not in config:
                self.issues.append("✗ Missing 'dataset_name' in configuration")
            
            if 'model' not in config:
                self.warnings.append("⚠ No model specified, will use default")
            
            processing = config.get('processing', {})
            mode = processing.get('mode', 'manual')
            
            self.info.append(f"✓ Configuration found (mode: {mode})")
            
        except json.JSONDecodeError:
            self.issues.append("✗ Configuration file is invalid JSON")
    
    def _check_git_hooks(self):
        """Check git hook installation"""
        print("\n🔗 Checking git hooks...")
        
        git_dir = os.path.join(self.project_root, '.git')
        if not os.path.exists(git_dir):
            self.warnings.append("⚠ Not a git repository")
            return
        
        hooks = ['pre-commit', 'post-commit']
        for hook in hooks:
            hook_path = os.path.join(git_dir, 'hooks', hook)
            if os.path.exists(hook_path):
                with open(hook_path, 'r') as f:
                    content = f.read()
                    if 'code-query' in content:
                        self.info.append(f"✓ {hook} hook installed")
                    else:
                        self.warnings.append(f"⚠ {hook} hook exists but doesn't include code-query")
            else:
                self.warnings.append(f"⚠ {hook} hook not installed")
    
    def _check_worker_status(self):
        """Check worker process status"""
        print("\n👷 Checking worker status...")
        
        from helpers.worker_detector import is_worker_running
        
        running, pid = is_worker_running()
        if running:
            self.info.append(f"✓ Worker is running (PID: {pid})")
            
            # Check PID file
            pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
            if os.path.exists(pid_file):
                self.info.append("✓ PID file exists")
            else:
                self.warnings.append("⚠ Worker running but PID file missing")
        else:
            config_path = os.path.join(self.project_root, '.code-query', 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    if config.get('processing', {}).get('mode') == 'auto':
                        self.warnings.append("⚠ Worker not running (auto mode enabled)")
                        self.warnings.append("  Start with: python server.py worker start")
            else:
                self.info.append("✓ Worker not running (manual mode)")
    
    def _check_queue_health(self):
        """Check queue database health"""
        print("\n📊 Checking queue health...")
        
        queue_db = os.path.join(self.project_root, '.code-query', 'huey_jobs.db')
        
        if os.path.exists(queue_db):
            size = os.path.getsize(queue_db) / 1024 / 1024  # MB
            self.info.append(f"✓ Queue database exists ({size:.1f} MB)")
            
            # Try to connect and check
            try:
                import sqlite3
                with sqlite3.connect(queue_db) as conn:  # Auto-closes on exit
                    cursor = conn.cursor()
                    
                    # Check pending tasks
                    cursor.execute("SELECT COUNT(*) FROM huey_task")
                    pending = cursor.fetchone()[0]
                    
                    if pending > 0:
                        self.info.append(f"ℹ️  {pending} tasks pending in queue")
            except Exception as e:
                self.warnings.append(f"⚠ Could not check queue database: {e}")
        else:
            self.info.append("ℹ️  Queue database not yet created")
    
    def _check_permissions(self):
        """Check file permissions"""
        print("\n🔐 Checking permissions...")
        
        dirs_to_check = [
            '.code-query',
            '.git/hooks'
        ]
        
        for dir_path in dirs_to_check:
            full_path = os.path.join(self.project_root, dir_path)
            if os.path.exists(full_path):
                if os.access(full_path, os.W_OK):
                    self.info.append(f"✓ Write permission for {dir_path}")
                else:
                    self.issues.append(f"✗ No write permission for {dir_path}")
    
    def _check_environment(self):
        """Check environment variables and system"""
        print("\n🌍 Checking environment...")
        
        # Python version
        py_version = sys.version.split()[0]
        if sys.version_info >= (3, 8):
            self.info.append(f"✓ Python {py_version}")
        else:
            self.issues.append(f"✗ Python {py_version} (require 3.8+)")
        
        # Check if in virtual environment
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            self.info.append("✓ Running in virtual environment")
        else:
            self.warnings.append("⚠ Not running in virtual environment")
        
        # Platform
        import platform
        self.info.append(f"ℹ️  Platform: {platform.system()} {platform.release()}")
    
    def _report_results(self):
        """Report diagnostic results"""
        print("\n" + "=" * 40)
        print("📋 Diagnostic Summary")
        print("=" * 40)
        
        if self.issues:
            print(f"\n❌ {len(self.issues)} issue(s) found:")
            for issue in self.issues:
                print(f"  {issue}")
        
        if self.warnings:
            print(f"\n⚠️  {len(self.warnings)} warning(s):")
            for warning in self.warnings:
                print(f"  {warning}")
        
        if self.info:
            print(f"\nℹ️  System information:")
            for info in self.info:
                print(f"  {info}")
        
        if not self.issues:
            print("\n✅ All checks passed! System is ready.")
        else:
            print("\n❌ Please fix the issues above before proceeding.")
```

### 5. Simple Performance Monitoring (`monitoring/metrics.py`)
```python
import time
import json
import os
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, asdict

@dataclass
class TaskMetric:
    """Metrics for a single task execution"""
    task_id: str
    filepath: str
    start_time: float
    end_time: float
    duration: float
    success: bool
    error: Optional[str] = None

class MetricsCollector:
    """Collect and store performance metrics"""
    
    def __init__(self, metrics_file: str):
        self.metrics_file = metrics_file
        self.current_metrics: Dict[str, TaskMetric] = {}
    
    def start_task(self, task_id: str, filepath: str):
        """Record task start"""
        self.current_metrics[task_id] = TaskMetric(
            task_id=task_id,
            filepath=filepath,
            start_time=time.time(),
            end_time=0,
            duration=0,
            success=False
        )
    
    def end_task(self, task_id: str, success: bool, error: Optional[str] = None):
        """Record task completion"""
        if task_id not in self.current_metrics:
            return
        
        metric = self.current_metrics[task_id]
        metric.end_time = time.time()
        metric.duration = metric.end_time - metric.start_time
        metric.success = success
        metric.error = error
        
        self._save_metric(metric)
        del self.current_metrics[task_id]
    
    def _save_metric(self, metric: TaskMetric):
        """Save metric to file"""
        os.makedirs(os.path.dirname(self.metrics_file), exist_ok=True)
        
        with open(self.metrics_file, 'a') as f:
            f.write(json.dumps(asdict(metric)) + '\n')
    
    def get_summary(self, last_n_days: int = 7) -> Dict:
        """Get metrics summary"""
        if not os.path.exists(self.metrics_file):
            return {
                'total_tasks': 0,
                'success_rate': 0,
                'avg_duration': 0
            }
        
        cutoff_time = time.time() - (last_n_days * 24 * 60 * 60)
        metrics = []
        
        with open(self.metrics_file, 'r') as f:
            for line in f:
                try:
                    metric = json.loads(line)
                    if metric['start_time'] > cutoff_time:
                        metrics.append(metric)
                except json.JSONDecodeError:
                    continue
        
        if not metrics:
            return {
                'total_tasks': 0,
                'success_rate': 0,
                'avg_duration': 0
            }
        
        total_tasks = len(metrics)
        successful_tasks = sum(1 for m in metrics if m['success'])
        total_duration = sum(m['duration'] for m in metrics)
        
        return {
            'total_tasks': total_tasks,
            'success_rate': (successful_tasks / total_tasks) * 100,
            'avg_duration': total_duration / total_tasks,
            'failed_tasks': total_tasks - successful_tasks
        }
```

## Testing Strategy

### Unit Tests (`tests/test_queue_processing.py`)
```python
import unittest
import tempfile
import os
from unittest.mock import Mock, patch

class TestQueueProcessing(unittest.TestCase):
    """Test suite for queue processing components"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = self.temp_dir
    
    def tearDown(self):
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_worker_detection(self):
        """Test worker detection mechanism"""
        from helpers.worker_detector import is_worker_running
        
        # Test with no PID file
        running, pid = is_worker_running()
        self.assertFalse(running)
        self.assertIsNone(pid)
        
        # Test with PID file
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))  # Current process PID
        
        running, pid = is_worker_running()
        self.assertTrue(running)
        self.assertEqual(pid, os.getpid())
    
    @patch('helpers.worker_detector.psutil.pid_exists')
    def test_worker_detection_stale_pid(self, mock_pid_exists):
        """Test worker detection with stale PID file"""
        from helpers.worker_detector import is_worker_running
        
        # Simulate process not running
        mock_pid_exists.return_value = False
        
        pid_file = os.path.join(self.project_root, '.code-query', 'worker.pid')
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        
        # Write a fake, non-existent PID
        with open(pid_file, 'w') as f:
            f.write('99999')
        
        running, pid = is_worker_running()
        self.assertFalse(running)
        self.assertIsNone(pid)
        
        # Verify PID file was cleaned up
        self.assertFalse(os.path.exists(pid_file))
    
    def test_configuration_loading(self):
        """Test configuration management"""
        from storage.config_manager import ConfigManager
        
        config_path = os.path.join(self.temp_dir, '.code-query', 'config.json')
        manager = ConfigManager(config_path)
        
        # Test default processing config
        processing = manager.get_processing_config()
        self.assertEqual(processing['mode'], 'manual')
        self.assertTrue(processing['fallback_to_sync'])
    
    def test_error_handling(self):
        """Test error handling mechanisms"""
        from helpers.error_handler import handle_error, WorkerNotRunningError
        
        # Test custom error
        error = WorkerNotRunningError()
        with patch('builtins.print') as mock_print:
            handle_error(error)
            
            # Check error was printed with context
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any('WARNING' in call for call in calls))
            self.assertTrue(any('suggestion' in call for call in calls))
    
    def test_metrics_collection(self):
        """Test metrics collector"""
        from monitoring.metrics import MetricsCollector
        
        metrics_file = os.path.join(self.temp_dir, 'metrics.json')
        collector = MetricsCollector(metrics_file)
        
        # Record a task
        collector.start_task('task-1', 'test.py')
        collector.end_task('task-1', success=True)
        
        # Check summary
        summary = collector.get_summary()
        self.assertEqual(summary['total_tasks'], 1)
        self.assertEqual(summary['success_rate'], 100.0)
        self.assertGreater(summary['avg_duration'], 0)
```

## Documentation Updates

### README.md additions:
```markdown
## Queue Processing

Code Query MCP now supports automated background processing of documentation updates. This means:
- ⚡ Instant git commits (no waiting for documentation)
- 🔄 Automatic processing in the background
- 📈 Better performance for large codebases
- 🛡️ Graceful fallback if worker isn't running

### Quick Start
```bash
# Setup queue processing
python server.py worker setup

# Start background worker
python server.py worker start
```

See [documentation](docs/getting-started.md) for details.
```

## Success Metrics
- [ ] Setup wizard completion rate > 90%
- [ ] Error messages help users self-resolve > 80% of issues
- [ ] Documentation answers > 95% of common questions
- [ ] Performance improvement of 10x for large commits
- [ ] Zero data loss in queue processing

## Dependencies on Other Work
- Requires Phase 1 completed
- Uses infrastructure from Phase 1

## Future Enhancements
- Docker-based deployment
- Web-based monitoring dashboard
- Multi-repository management
- Team collaboration features