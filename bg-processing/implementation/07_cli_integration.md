# Step 7: CLI Integration

## Overview
Extend server.py with worker management subcommands for starting, stopping, and monitoring the background worker.

## References
- phase1_pr_plan.md:179-204

## Implementation Tasks

### 7.1 Extend server.py with worker subcommands

Add to the existing `server.py`:

```python
import argparse
import sys
import os
from typing import Optional

# Add imports for worker management
from cli.worker_manager import WorkerManager
from storage.config_manager import ConfigManager
from helpers.git_hook_handler import install_git_hooks

def add_worker_commands(subparsers):
    """Add worker-related subcommands to the argument parser."""
    
    # Worker command group
    worker_parser = subparsers.add_parser(
        'worker',
        help='Manage background worker for queue processing'
    )
    worker_subparsers = worker_parser.add_subparsers(
        dest='worker_command',
        help='Worker commands'
    )
    
    # worker start
    start_parser = worker_subparsers.add_parser(
        'start',
        help='Start the background worker'
    )
    start_parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run worker as daemon (detached from terminal)'
    )
    
    # worker stop
    stop_parser = worker_subparsers.add_parser(
        'stop',
        help='Stop the background worker'
    )
    stop_parser.add_argument(
        '--force',
        action='store_true',
        help='Force stop if graceful shutdown fails'
    )
    
    # worker status
    status_parser = worker_subparsers.add_parser(
        'status',
        help='Check worker status'
    )
    status_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed status information'
    )
    
    # worker restart
    restart_parser = worker_subparsers.add_parser(
        'restart',
        help='Restart the background worker'
    )
    
    # worker logs
    logs_parser = worker_subparsers.add_parser(
        'logs',
        help='View worker logs'
    )
    logs_parser.add_argument(
        '--lines', '-n',
        type=int,
        default=20,
        help='Number of log lines to show (default: 20)'
    )
    logs_parser.add_argument(
        '--follow', '-f',
        action='store_true',
        help='Follow log output (like tail -f)'
    )
    
    # worker setup
    setup_parser = worker_subparsers.add_parser(
        'setup',
        help='Run interactive setup wizard'
    )
    setup_parser.add_argument(
        '--mode',
        choices=['manual', 'auto'],
        help='Set processing mode directly'
    )
    
    # worker config
    config_parser = worker_subparsers.add_parser(
        'config',
        help='View or modify worker configuration'
    )
    config_parser.add_argument(
        '--show',
        action='store_true',
        help='Show current configuration'
    )
    config_parser.add_argument(
        '--set',
        nargs=2,
        metavar=('KEY', 'VALUE'),
        help='Set a configuration value (e.g., --set processing.mode auto)'
    )
    
    # worker diagnose
    diagnose_parser = worker_subparsers.add_parser(
        'diagnose',
        help='Run diagnostic checks'
    )
    diagnose_parser.add_argument(
        '--fix',
        action='store_true',
        help='Attempt to fix issues automatically'
    )
    
    # worker queue
    queue_parser = worker_subparsers.add_parser(
        'queue',
        help='View queue information'
    )
    queue_parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear all items from queue'
    )
    queue_parser.add_argument(
        '--stats',
        action='store_true',
        help='Show queue statistics'
    )

def handle_worker_command(args, project_root: str):
    """
    Handle worker subcommands.
    
    Args:
        args: Parsed command line arguments
        project_root: Path to project root
    """
    worker_manager = WorkerManager(project_root)
    
    if args.worker_command == 'start':
        handle_worker_start(worker_manager, args)
    
    elif args.worker_command == 'stop':
        handle_worker_stop(worker_manager, args)
    
    elif args.worker_command == 'status':
        handle_worker_status(worker_manager, args)
    
    elif args.worker_command == 'restart':
        handle_worker_restart(worker_manager)
    
    elif args.worker_command == 'logs':
        handle_worker_logs(worker_manager, args)
    
    elif args.worker_command == 'setup':
        handle_worker_setup(project_root, args)
    
    elif args.worker_command == 'config':
        handle_worker_config(project_root, args)
    
    elif args.worker_command == 'diagnose':
        handle_worker_diagnose(project_root, args)
    
    elif args.worker_command == 'queue':
        handle_worker_queue(project_root, args)
    
    else:
        print("Please specify a worker command. Use 'worker --help' for options.")
        sys.exit(1)

def handle_worker_start(worker_manager: WorkerManager, args):
    """Handle worker start command."""
    success = worker_manager.start_worker()
    sys.exit(0 if success else 1)

def handle_worker_stop(worker_manager: WorkerManager, args):
    """Handle worker stop command."""
    success = worker_manager.stop_worker()
    sys.exit(0 if success else 1)

def handle_worker_status(worker_manager: WorkerManager, args):
    """Handle worker status command."""
    if args.verbose:
        worker_manager.display_worker_status()
    else:
        is_running, pid = worker_manager.get_worker_status()
        if is_running:
            print(f"✓ Worker is running (PID: {pid})")
        else:
            print("✗ Worker is not running")
    sys.exit(0)

def handle_worker_restart(worker_manager: WorkerManager):
    """Handle worker restart command."""
    success = worker_manager.restart_worker()
    sys.exit(0 if success else 1)

def handle_worker_logs(worker_manager: WorkerManager, args):
    """Handle worker logs command."""
    log_file = worker_manager.log_file
    
    if not os.path.exists(log_file):
        print(f"No log file found at {log_file}")
        sys.exit(1)
    
    if args.follow:
        # Follow mode (like tail -f)
        import subprocess
        try:
            subprocess.run(['tail', '-f', log_file])
        except KeyboardInterrupt:
            pass
    else:
        # Show last N lines
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-args.lines:]:
                print(line.rstrip())

def handle_worker_setup(project_root: str, args):
    """Handle worker setup command."""
    from cli.setup_wizard import SetupWizard
    
    wizard = SetupWizard(project_root)
    
    if args.mode:
        # Direct mode setting
        config_path = os.path.join(project_root, '.code-query', 'config.json')
        config_manager = ConfigManager(config_path)
        config_manager.update_processing_mode(args.mode)
        print(f"✓ Processing mode set to: {args.mode}")
        
        # Install git hooks
        if install_git_hooks(project_root):
            print("✓ Git hooks installed")
    else:
        # Run interactive wizard
        success = wizard.run()
        sys.exit(0 if success else 1)

def handle_worker_config(project_root: str, args):
    """Handle worker config command."""
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    config_manager = ConfigManager(config_path)
    
    if args.show:
        # Show current configuration
        try:
            config = config_manager.load_config()
            import json
            print(json.dumps(config, indent=2))
        except Exception as e:
            print(f"Error loading configuration: {e}")
            sys.exit(1)
    
    elif args.set:
        # Set configuration value
        key, value = args.set
        try:
            config = config_manager.load_config()
            
            # Navigate nested keys (e.g., "processing.mode")
            keys = key.split('.')
            target = config
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            
            # Convert value types
            if value.lower() in ['true', 'false']:
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            
            target[keys[-1]] = value
            
            config_manager.save_config(config)
            print(f"✓ Set {key} = {value}")
            
        except Exception as e:
            print(f"Error setting configuration: {e}")
            sys.exit(1)
    
    else:
        print("Use --show to view config or --set KEY VALUE to modify")

def handle_worker_diagnose(project_root: str, args):
    """Handle worker diagnose command."""
    from cli.diagnostics import Diagnostics
    
    diagnostics = Diagnostics(project_root)
    success = diagnostics.run()
    
    if args.fix and not success:
        print("\nAttempting to fix issues...")
        # Implement auto-fix logic here
        # For example: create missing directories, fix permissions, etc.
    
    sys.exit(0 if success else 1)

def handle_worker_queue(project_root: str, args):
    """Handle worker queue command."""
    from storage.queue_manager import QueueManager
    
    queue_manager = QueueManager(project_root)
    
    if args.clear:
        if queue_manager.clear_queue():
            print("✓ Queue cleared")
        else:
            print("✗ Failed to clear queue")
            sys.exit(1)
    
    elif args.stats:
        stats = queue_manager.get_queue_stats()
        print("Queue Statistics")
        print("=" * 40)
        print(f"Total files: {stats.get('total_files', 0)}")
        print(f"Queue size: {stats.get('queue_size_bytes', 0) / 1024:.1f} KB")
        
        if stats.get('file_types'):
            print("\nFile types:")
            for ext, count in sorted(stats['file_types'].items()):
                print(f"  {ext or '(no extension)'}: {count}")
        
        if stats.get('oldest_timestamp'):
            print(f"\nOldest item: {stats['oldest_timestamp']}")
        if stats.get('newest_timestamp'):
            print(f"Newest item: {stats['newest_timestamp']}")
    
    else:
        # Show queue contents
        files = queue_manager.get_snapshot()
        if not files:
            print("Queue is empty")
        else:
            print(f"Queue contains {len(files)} file(s):")
            for i, file_info in enumerate(files[:10]):  # Show first 10
                print(f"  {i+1}. {file_info['filepath']}")
                if 'timestamp' in file_info:
                    print(f"     Added: {file_info['timestamp']}")
            
            if len(files) > 10:
                print(f"  ... and {len(files) - 10} more")

# Update main function to include worker commands
def main():
    parser = argparse.ArgumentParser(
        description='Code Query MCP Server'
    )
    
    # Existing server arguments...
    parser.add_argument(
        '--http',
        type=int,
        metavar='PORT',
        help='Run in HTTP mode on specified port'
    )
    
    subparsers = parser.add_subparsers(
        dest='command',
        help='Available commands'
    )
    
    # Add worker commands
    add_worker_commands(subparsers)
    
    # Parse arguments
    args = parser.parse_args()
    
    # Get project root
    project_root = os.getcwd()
    
    # Handle commands
    if args.command == 'worker':
        handle_worker_command(args, project_root)
    else:
        # Default to MCP server mode
        if args.http:
            # Run HTTP server
            from http_server import run_http_server
            run_http_server(args.http)
        else:
            # Run stdio server
            from server import run_stdio_server
            run_stdio_server()

if __name__ == '__main__':
    main()
```

## Testing Checklist
- [ ] All worker commands are accessible
- [ ] Start command launches worker successfully
- [ ] Stop command terminates worker gracefully
- [ ] Status command shows accurate information
- [ ] Logs command displays recent entries
- [ ] Setup command runs wizard
- [ ] Config command shows/modifies settings
- [ ] Queue command displays queue info
- [ ] Help text is clear for all commands
- [ ] Error handling provides useful feedback

## Usage Examples

```bash
# Start worker
python server.py worker start

# Check status
python server.py worker status --verbose

# View logs
python server.py worker logs -n 50
python server.py worker logs --follow

# Modify configuration
python server.py worker config --show
python server.py worker config --set processing.mode auto
python server.py worker config --set processing.batch_size 10

# Manage queue
python server.py worker queue
python server.py worker queue --stats
python server.py worker queue --clear

# Run diagnostics
python server.py worker diagnose
```