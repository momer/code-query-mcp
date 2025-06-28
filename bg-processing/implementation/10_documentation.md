# Step 10: Documentation

## Overview
Create basic documentation for the queue processing feature including setup instructions and troubleshooting.

## References
- phase1_pr_plan.md:219

## Implementation Tasks

### 10.1 Update README.md

Add the following section to the main README:

```markdown
## Background Queue Processing

Code Query MCP now supports automated background processing of documentation updates, providing:

- ⚡ **Instant commits** - No waiting for documentation generation
- 🔄 **Background processing** - Updates happen asynchronously
- 📈 **Better performance** - Handle large codebases efficiently
- 🛡️ **Graceful fallback** - Works even if background worker isn't running

### Quick Start

1. **Setup queue processing:**
   ```bash
   python server.py worker setup
   ```

2. **Start the background worker:**
   ```bash
   python server.py worker start
   ```

3. **Make commits as usual:**
   ```bash
   git add .
   git commit -m "Your changes"
   # Files are queued for background processing automatically
   ```

### Configuration

Queue processing is configured in `.code-query/config.json`:

```json
{
  "processing": {
    "mode": "auto",         // "manual" for sync, "auto" for background
    "fallback_to_sync": true,  // Process synchronously if worker isn't running
    "batch_size": 5,        // Files to process per batch
    "delay_seconds": 300    // Delay between batches
  }
}
```

### Worker Commands

- `python server.py worker start` - Start background worker
- `python server.py worker stop` - Stop background worker
- `python server.py worker status` - Check worker status
- `python server.py worker logs` - View processing logs
- `python server.py worker queue` - View pending files

See [Queue Processing Guide](docs/queue-processing.md) for detailed documentation.
```

### 10.2 Create docs/queue-processing.md

```markdown
# Queue Processing Guide

This guide covers the background queue processing feature in Code Query MCP.

## Table of Contents
- [Overview](#overview)
- [Setup](#setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)

## Overview

Queue processing allows documentation updates to happen in the background, making git commits instant while ensuring your code documentation stays up to date.

### How It Works

1. **Pre-commit hook** detects changed files and adds them to a queue
2. **Post-commit hook** either:
   - Processes files synchronously (manual mode)
   - Enqueues them for background processing (auto mode)
3. **Background worker** (if running) processes queued files using Claude

## Setup

### Prerequisites

```bash
pip install huey psutil
```

### Interactive Setup

Run the setup wizard to configure queue processing:

```bash
python server.py worker setup
```

The wizard will guide you through:
1. Choosing processing mode (manual/auto)
2. Selecting Claude model
3. Configuring advanced options
4. Installing git hooks

### Manual Setup

1. **Create configuration** in `.code-query/config.json`:
   ```json
   {
     "dataset_name": "your-project",
     "model": "claude-3-5-sonnet-20240620",
     "processing": {
       "mode": "auto"
     }
   }
   ```

2. **Install git hooks**:
   ```bash
   python server.py worker setup --mode auto
   ```

## Configuration

### Processing Modes

#### Manual Mode (Default)
- Documentation updates happen during git commit
- No background worker needed
- Commits take longer but always complete

#### Auto Mode
- Documentation updates are queued for background processing
- Requires background worker to be running
- Instant commits

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `mode` | `"manual"` | Processing mode: `"manual"` or `"auto"` |
| `fallback_to_sync` | `true` | Process synchronously if worker isn't running |
| `batch_size` | `5` | Number of files to process together |
| `delay_seconds` | `300` | Seconds between processing batches |
| `max_retries` | `2` | Retry attempts for failed files |

### Environment Variables

Override configuration with environment variables:

- `CODEQUERY_MODEL` - Override Claude model
- `CODEQUERY_PROCESSING_MODE` - Override processing mode
- `CODEQUERY_BATCH_SIZE` - Override batch size

## Usage

### Starting the Worker

```bash
# Start in foreground
python server.py worker start

# Check status
python server.py worker status --verbose

# View logs
python server.py worker logs --follow
```

### Managing the Queue

```bash
# View pending files
python server.py worker queue

# View queue statistics
python server.py worker queue --stats

# Clear queue (use with caution)
python server.py worker queue --clear
```

### Monitoring

Monitor background processing:

```bash
# Follow worker logs
tail -f .code-query/worker.log

# Check worker health
python server.py worker diagnose
```

## Troubleshooting

### Common Issues

#### Worker won't start

1. **Check for existing worker:**
   ```bash
   python server.py worker status
   ```

2. **Clean up stale PID file:**
   ```bash
   rm .code-query/worker.pid
   python server.py worker start
   ```

3. **Check logs for errors:**
   ```bash
   cat .code-query/worker.log
   ```

#### Files not being processed

1. **Verify worker is running:**
   ```bash
   python server.py worker status
   ```

2. **Check queue status:**
   ```bash
   python server.py worker queue --stats
   ```

3. **Check configuration:**
   ```bash
   python server.py worker config --show
   ```

#### Git hooks not triggering

1. **Verify hooks are installed:**
   ```bash
   ls -la .git/hooks/post-commit
   ```

2. **Reinstall hooks:**
   ```bash
   python server.py worker setup
   ```

### Diagnostic Tool

Run comprehensive diagnostics:

```bash
python server.py worker diagnose
```

This checks:
- Dependencies
- Configuration
- Git hooks
- Worker status
- Queue health
- File permissions

### Error Messages

| Error | Meaning | Solution |
|-------|---------|----------|
| "Background worker not running" | Worker process isn't active | Run `python server.py worker start` |
| "Could not acquire queue lock" | Queue file is locked | Wait and retry, or check for stuck processes |
| "Configuration missing dataset_name" | Invalid config | Run setup wizard or fix config manually |

## Architecture

### Components

1. **Git Hooks** (Python-based)
   - `pre-commit`: Queues changed files
   - `post-commit`: Processes or enqueues files

2. **Queue Manager**
   - Atomic file operations
   - Cross-platform file locking
   - Handles concurrent access

3. **Worker Process**
   - Huey consumer with SQLite backend
   - PID-based detection
   - Graceful shutdown handling

4. **Configuration Manager**
   - Schema validation
   - Default merging
   - Migration support

### File Structure

```
.code-query/
├── config.json         # Configuration
├── file_queue.json     # Pending files
├── huey_jobs.db        # Background job queue
├── worker.pid          # Worker process ID
└── worker.log          # Worker logs
```

### Processing Flow

```
Git Commit
    ↓
Pre-commit Hook
    ↓
Queue Changed Files → file_queue.json
    ↓
Post-commit Hook
    ↓
Check Mode & Worker
    ↓
┌─────────────┬──────────────┐
│  Manual/    │     Auto +   │
│  No Worker  │    Worker    │
└─────────────┴──────────────┘
      ↓              ↓
 Sync Process   Enqueue Task
      ↓              ↓
 Update Docs    Background
                Processing
```

## Best Practices

1. **Start with manual mode** to verify setup
2. **Monitor worker logs** when first using auto mode
3. **Use fallback** for reliability
4. **Set appropriate batch sizes** for your system
5. **Regular queue maintenance** - check for stale items

## Future Enhancements

- Docker-based deployment
- Web monitoring dashboard
- Multi-project support
- Cloud processing options
```

### 10.3 Create docs/troubleshooting.md

```markdown
# Troubleshooting Guide

## Quick Diagnostics

Run this first for any issues:

```bash
python server.py worker diagnose
```

## Common Problems

### Installation Issues

#### "Module 'huey' not found"

Install required dependencies:
```bash
pip install huey psutil
```

#### "Permission denied" errors

Check file permissions:
```bash
ls -la .code-query/
chmod 755 .code-query
```

### Worker Issues

#### Worker starts but immediately stops

1. Check the log file:
   ```bash
   tail -50 .code-query/worker.log
   ```

2. Common causes:
   - Import errors in tasks.py
   - Database locking issues
   - Invalid configuration

#### Worker appears running but not processing

1. Check if worker is actually processing:
   ```bash
   python server.py worker status --verbose
   ```

2. Check queue for pending items:
   ```bash
   python server.py worker queue --stats
   ```

3. Try restarting:
   ```bash
   python server.py worker restart
   ```

### Queue Issues

#### Queue file corrupted

1. Back up current queue:
   ```bash
   cp .code-query/file_queue.json .code-query/file_queue.backup
   ```

2. Clear and recreate:
   ```bash
   python server.py worker queue --clear
   ```

#### Files stuck in queue

1. Check file timestamps:
   ```bash
   python server.py worker queue --stats
   ```

2. If files are old, clear queue:
   ```bash
   python server.py worker queue --clear
   ```

### Git Hook Issues

#### Commits are slow (auto mode)

This suggests fallback to synchronous processing:

1. Check worker status:
   ```bash
   python server.py worker status
   ```

2. Start worker if not running:
   ```bash
   python server.py worker start
   ```

#### Hooks not triggering at all

1. Verify hook files exist:
   ```bash
   ls -la .git/hooks/post-commit
   cat .git/hooks/post-commit
   ```

2. Reinstall hooks:
   ```bash
   python server.py worker setup
   ```

3. Check hook permissions:
   ```bash
   chmod +x .git/hooks/post-commit
   ```

## Debug Mode

### Enable verbose logging

1. Edit `.code-query/config.json`:
   ```json
   {
     "processing": {
       "debug": true
     }
   }
   ```

2. Watch logs:
   ```bash
   tail -f .code-query/worker.log
   ```

### Test individual components

```python
# Test queue operations
from storage.queue_manager import QueueManager
qm = QueueManager('.')
print(qm.get_queue_stats())

# Test worker detection
from helpers.worker_detector import is_worker_running
print(is_worker_running())

# Test configuration
from storage.config_manager import ConfigManager
cm = ConfigManager('.code-query/config.json')
print(cm.validate_config_file())
```

## Getting Help

1. Check logs: `.code-query/worker.log`
2. Run diagnostics: `python server.py worker diagnose`
3. Review configuration: `python server.py worker config --show`
4. File an issue with diagnostic output
```

### 10.4 Add inline documentation

Ensure all major functions and classes have docstrings:

```python
def process_file_documentation(filepath: str, dataset_name: str, 
                               commit_hash: str, project_root: str) -> Dict[str, Any]:
    """
    Process documentation for a single file using Claude.
    
    This is the core task that runs in the background worker. It:
    1. Loads the file content
    2. Calls Claude API for analysis
    3. Updates the database with results
    
    Args:
        filepath: Relative path to the file
        dataset_name: Name of the dataset to update
        commit_hash: Git commit hash for tracking
        project_root: Absolute path to project root
        
    Returns:
        Dict containing:
        - success (bool): Whether processing succeeded
        - filepath (str): The processed file path
        - error (str, optional): Error message if failed
        
    Raises:
        Exception: If Claude API call fails after retries
        
    Example:
        >>> result = process_file_documentation(
        ...     filepath='src/main.py',
        ...     dataset_name='my-project',
        ...     commit_hash='abc123',
        ...     project_root='/home/user/project'
        ... )
        >>> print(result)
        {'success': True, 'filepath': 'src/main.py'}
    """
```

## Testing Checklist
- [ ] README section is clear and concise
- [ ] Queue processing guide is comprehensive
- [ ] Troubleshooting covers common issues
- [ ] Code examples work correctly
- [ ] Links between documents work
- [ ] Inline documentation is helpful

## Documentation Structure
```
docs/
├── queue-processing.md    # Main guide
├── troubleshooting.md     # Problem solving
├── getting-started.md     # Quick start (Phase 2)
├── architecture.md        # Technical details (Phase 2)
└── api-reference.md       # Tool documentation (Phase 2)
```