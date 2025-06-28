# Automated Queue Processing Implementation Plan

## Executive Summary

This document outlines the implementation plan for automated queue processing in the code-query MCP server. The solution addresses the need to automatically process documentation updates triggered by git commits while maintaining excellent developer experience through graceful degradation and flexible configuration.

## Problem Statement

Currently, the code-query MCP uses git hooks to queue files for documentation updates, but requires manual intervention to process the queue. We want to automate this processing using `claude --prompt --model ${configured_model}` while ensuring:

1. **Non-blocking git operations** - Commits should complete instantly
2. **Excellent developer experience** - No mandatory daemon management
3. **Graceful degradation** - Always works, works better with background processing
4. **Configurable behavior** - Users control sync vs async processing

## Architecture Overview

### Core Design Principles

Based on comprehensive analysis with zen, our approach follows these key principles:

1. **Decoupled Producer-Consumer Pattern**: Git hooks (producer) → SQLite queue (broker) → Background worker (consumer)
2. **Graceful Degradation**: Three-tier experience from zero-config to fully automated
3. **User-Controlled Lifecycle**: Optional background processing with clear upgrade paths
4. **Platform-Native Integration**: Systemd/launchd services for auto-start capabilities

### Technology Stack

- **Queue System**: Huey with SQLite backend
- **Worker Detection**: psutil for process monitoring
- **Service Management**: systemd --user (Linux), launchd (macOS)
- **Configuration**: Extended .code-query/config.json
- **CLI Interface**: Extended server.py with worker management commands

## Two-Tier Developer Experience

### Tier 1: Zero-Config (Default)
```bash
git commit -m "changes"
# Hook runs synchronously, takes 2-3 seconds
# Output: "✓ Documentation updated (synchronous mode)"
```

**Characteristics:**
- Works immediately after installation
- No setup required
- Slower but reliable
- Clear messaging about current mode

### Tier 2: Managed Background Worker
```bash
python server.py worker start  # User-managed process
git commit -m "changes" 
# Hook queues instantly
# Output: "✓ Files queued for background processing"
```

**Characteristics:**
- User starts/stops worker manually
- Instant git operations
- Background processing with retry logic
- Process survives restarts (jobs persist in queue)
- No service installation complexity

## Implementation Details

### Database Architecture

**Two Separate SQLite Databases:**
1. `huey_jobs.db` - Huey's job queue management
2. `code_data.db` - Existing code-query application data

This separation prevents locking conflicts and maintains clean separation of concerns.

### Configuration Schema

Extended `.code-query/config.json`:
```json
{
  "dataset_name": "my-project",
  "model": "claude-3-5-sonnet-20240620",
  "processing": {
    "mode": "auto",              // "manual" | "auto"
    "worker_command": "huey_consumer tasks.huey",
    "check_interval": 5,
    "fallback_to_sync": true,
    "batch_size": 5,
    "delay_seconds": 300,
    "max_retries": 2
  }
}
```

### Git Hook Logic

**Python-based post-commit hook:**
```python
#!/usr/bin/env python3
import sys
import os
# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.git_hook_handler import handle_post_commit
sys.exit(handle_post_commit())
```

The hook logic is handled in `helpers/git_hook_handler.py` which:
- Loads configuration using native Python JSON parsing
- Checks processing mode (auto/manual)
- Detects if worker is running
- Enqueues tasks or processes synchronously
- Provides clear user feedback

### Worker Detection Implementation

**Process-based detection (most reliable):**
```python
# .code-query/check_worker.py
import psutil
import sys

def is_worker_running():
    """Check if our huey worker is running"""
    for proc in psutil.process_iter(['cmdline', 'pid']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if 'huey_consumer' in cmdline and 'code-query' in cmdline:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

if __name__ == '__main__':
    sys.exit(0 if is_worker_running() else 1)
```

### Task Definition

**Background processing tasks:**
```python
# tasks.py
from huey import SqliteHuey
import subprocess
import json

# Huey creates its own SQLite database for job queue management
huey = SqliteHuey(filename='.code-query/huey_jobs.db')

@huey.task(retries=2, retry_delay=60)
def process_file_documentation(filepath, dataset_name, commit_hash):
    """Background task that calls claude and updates documentation"""
    print(f"Processing documentation for {filepath}...")
    
    # Load configuration
    with open('.code-query/config.json', 'r') as f:
        config = json.load(f)
    
    model = config.get('model', 'claude-3-5-sonnet-20240620')
    
    # Call Claude to analyze the file
    result = subprocess.run([
        'claude', '--prompt', f'Analyze and document {filepath}', 
        '--model', model
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        # Update the main code-query database
        update_file_documentation_in_db(filepath, dataset_name, result.stdout, commit_hash)
        print(f"✓ Completed documentation for {filepath}")
    else:
        print(f"✗ Failed to document {filepath}: {result.stderr}")
        raise Exception(f"Claude processing failed: {result.stderr}")
```

### CLI Interface

**Extended server.py with worker management:**
```python
# Added worker management commands to server.py
def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    
    # Existing MCP server command
    server_parser = subparsers.add_parser('server', help='Start MCP server')
    
    # Worker management commands
    worker_parser = subparsers.add_parser('worker', help='Manage background worker')
    worker_subparsers = worker_parser.add_subparsers(dest='worker_command')
    
    worker_subparsers.add_parser('start', help='Start background worker')
    worker_subparsers.add_parser('stop', help='Stop background worker')
    worker_subparsers.add_parser('status', help='Check worker status')
    worker_subparsers.add_parser('install-service', help='Install auto-start service')
    worker_subparsers.add_parser('uninstall-service', help='Remove auto-start service')
    
    args = parser.parse_args()
    
    if args.command == 'worker':
        handle_worker_command(args.worker_command)
    else:
        # Default to MCP server
        start_mcp_server()
```


## Implementation Phases

### Phase 1: Core Queue Processing
**Timeline: 1-2 weeks**

**Deliverables:**
- [ ] Huey task definitions and SQLite backend setup (SqliteHuey)
- [ ] PID file-based worker detection
- [ ] Python-based git hooks with fallback logic
- [ ] Basic CLI commands for worker start/stop/status
- [ ] Configuration schema extensions
- [ ] Documentation and setup instructions

**Success Criteria:**
- Git hooks work in both sync and async modes
- Background worker processes files correctly
- Graceful degradation when worker not available
- Clear user feedback about current processing mode
- No shell dependencies (pure Python)

### Phase 2: Polish and Documentation
**Timeline: 1 week**

**Deliverables:**
- [ ] Comprehensive user documentation
- [ ] Installation and setup guides
- [ ] Troubleshooting documentation
- [ ] Interactive setup wizard
- [ ] Diagnostic tool
- [ ] Unit test coverage

**Success Criteria:**
- Seamless new user experience
- Clear documentation for both modes
- Excellent error messages and recovery
- Production-ready reliability
- All components unit tested

## Dependencies

### Required Python Packages
```bash
pip install huey psutil
```

### System Dependencies
- None required - pure Python implementation

### Claude CLI Integration
- Requires existing `claude` command-line tool
- Uses `--prompt` and `--model` flags for processing
- Integrates with existing MCP model configuration

## Risk Mitigation

### Developer Experience Risks
**Risk**: Users frustrated by daemon management requirements
**Mitigation**: Three-tier approach with zero-config default mode

**Risk**: Background process resource consumption
**Mitigation**: Configurable processing intervals and batch sizes

### Technical Risks
**Risk**: SQLite database locking under concurrent access
**Mitigation**: Separate databases for queue vs application data

**Risk**: Worker process crashes losing queued jobs
**Mitigation**: Huey's persistent SQLite queue survives worker restarts

**Risk**: Worker process management complexity
**Mitigation**: Simple manual start/stop with clear documentation

**Risk**: Git hook failures breaking commit workflow
**Mitigation**: Always allow commits to succeed, degrade gracefully

## Success Metrics

### Performance Metrics
- Git commit latency in async mode: < 100ms
- Background processing throughput: 5-10 files/minute
- Worker startup time: < 5 seconds
- Worker detection accuracy: > 99%

### User Experience Metrics
- Zero-config success rate: 100% (always works)
- Manual worker management success: > 95%
- User-reported friction points: < 5% of users
- Documentation clarity: User can complete setup in < 5 minutes

### Technical Metrics
- Worker detection accuracy: > 99%
- Job queue persistence: 100% across restarts
- Cross-platform compatibility: Linux + macOS
- Error handling coverage: All failure modes handled gracefully

## Future Enhancements

### Potential Improvements
1. **Web Dashboard**: Browser-based monitoring and control interface
2. **Batch Optimization**: Intelligent batching of related files
3. **Resource Management**: CPU/memory limits and throttling
4. **Integration Ecosystem**: VS Code extension, IDE plugins
5. **Advanced Scheduling**: Time-based processing windows
6. **Metrics and Analytics**: Processing statistics and performance tracking

### Scalability Considerations
1. **Multi-Project Support**: Single worker handling multiple repositories
2. **Distributed Processing**: Multiple workers for large codebases
3. **Cloud Integration**: Remote processing capabilities
4. **Enterprise Features**: Team-wide configuration and policies

## Conclusion

This implementation plan provides a streamlined solution for automated queue processing that balances developer experience, technical robustness, and operational simplicity. The two-tier approach ensures immediate usability with optional background processing.

The architecture leverages proven technologies (Huey with SqliteHuey, Python git hooks) in a lightweight, self-contained package that aligns with the project's philosophy of minimal dependencies and maximum portability.

Key success factors:
- **Graceful degradation** ensures the tool always works
- **Manual worker management** keeps things simple and understandable
- **Pure Python implementation** provides cross-platform compatibility
- **Clear feedback** keeps users informed about system state

The phased implementation approach allows for iterative development and user feedback integration, with a future Docker-based solution for production deployments.