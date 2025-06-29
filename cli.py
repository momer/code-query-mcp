#!/usr/bin/env python3
"""Code Query MCP Server CLI - Main entry point for all commands."""

import argparse
import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def positive_int(value):
    """Custom argparse type for positive integers."""
    try:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError(f"{value} is an invalid positive int value")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer")

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
        type=positive_int,
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


def add_queue_commands(subparsers):
    """Add queue-related subcommands to the argument parser."""
    # Queue command group
    queue_parser = subparsers.add_parser(
        'queue',
        help='Manage the file documentation queue'
    )
    queue_subparsers = queue_parser.add_subparsers(
        dest='queue_command',
        help='Queue commands'
    )
    
    # queue status
    status_parser = queue_subparsers.add_parser(
        'status',
        help='Show queue statistics'
    )
    
    # queue list
    list_parser = queue_subparsers.add_parser(
        'list',
        help='List files in the queue'
    )
    list_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )
    list_parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    
    # queue add
    add_parser = queue_subparsers.add_parser(
        'add',
        help='Add files to the queue'
    )
    add_parser.add_argument(
        'files',
        nargs='+',
        help='Files to add to the queue'
    )
    add_parser.add_argument(
        '--commit',
        type=str,
        help='Associate files with a specific commit'
    )
    
    # queue remove
    remove_parser = queue_subparsers.add_parser(
        'remove',
        help='Remove files from the queue'
    )
    remove_parser.add_argument(
        'files',
        nargs='+',
        help='Files to remove from the queue'
    )
    
    # queue clear
    clear_parser = queue_subparsers.add_parser(
        'clear',
        help='Clear all files from the queue'
    )
    clear_parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    # queue process
    process_parser = queue_subparsers.add_parser(
        'process',
        help='Get next batch of files for processing'
    )
    process_parser.add_argument(
        '--batch-size',
        type=positive_int,
        default=5,
        help='Number of files to retrieve (default: 5)'
    )
    process_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without removing from queue'
    )
    process_parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    
    # queue cleanup
    cleanup_parser = queue_subparsers.add_parser(
        'cleanup',
        help='Remove entries for missing files'
    )
    cleanup_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be cleaned up without removing'
    )
    
    # queue history
    history_parser = queue_subparsers.add_parser(
        'history',
        help='Show queue operation history'
    )
    history_parser.add_argument(
        '--lines', '-n',
        type=positive_int,
        default=20,
        help='Number of history entries to show (default: 20)'
    )
    
    # queue watch
    watch_parser = queue_subparsers.add_parser(
        'watch',
        help='Watch queue status in real-time'
    )


def handle_worker_command(args, project_root: str):
    """
    Handle worker subcommands.
    
    Args:
        args: Parsed command line arguments
        project_root: Path to project root
    """
    from cli.worker_manager import WorkerManager
    from storage.config_manager import ConfigManager
    from helpers.git_helper import install_git_hooks
    
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
    
    else:
        print("Please specify a worker command. Use 'worker --help' for options.")
        sys.exit(1)


def handle_worker_start(worker_manager, args):
    """Handle worker start command."""
    success = worker_manager.start_worker()
    sys.exit(0 if success else 1)


def handle_worker_stop(worker_manager, args):
    """Handle worker stop command."""
    success = worker_manager.stop_worker()
    sys.exit(0 if success else 1)


def handle_worker_status(worker_manager, args):
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


def handle_worker_restart(worker_manager):
    """Handle worker restart command."""
    success = worker_manager.restart_worker()
    sys.exit(0 if success else 1)


def handle_worker_logs(worker_manager, args):
    """Handle worker logs command."""
    log_file = worker_manager.log_file
    
    if not os.path.exists(log_file):
        print(f"No log file found at {log_file}")
        sys.exit(1)
    
    if args.follow:
        # Follow mode - implemented in Python to avoid subprocess
        import time
        print(f"Following log file: {log_file} (Ctrl+C to stop)")
        try:
            with open(log_file, 'r') as f:
                # Go to the end of the file
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)  # Wait for new lines
                        continue
                    print(line.rstrip())
        except FileNotFoundError:
            print(f"No log file found at {log_file}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nStopped following log.")
            pass
    else:
        # Show last N lines
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for line in lines[-args.lines:]:
                print(line.rstrip())


def handle_worker_setup(project_root: str, args):
    """Handle worker setup command."""
    from storage.config_manager import ConfigManager
    from helpers.git_helper import install_git_hooks
    
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
        print("Interactive setup wizard not yet implemented.")
        print("Use --mode to set processing mode directly.")
        sys.exit(1)


def handle_worker_config(project_root: str, args):
    """Handle worker config command."""
    from storage.config_manager import ConfigManager
    import json
    
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    config_manager = ConfigManager(config_path)
    
    if args.show:
        # Show current configuration
        try:
            config = config_manager.load_config()
            print(json.dumps(config, indent=2))
        except Exception as e:
            logging.error(f"Error loading configuration: {e}", exc_info=True)
            print(f"✗ Error: Failed to load configuration. See logs for details.")
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
                # Ensure the key exists and points to a dictionary
                if not isinstance(target, dict) or k not in target or not isinstance(target.get(k), dict):
                    print(f"Error: Invalid configuration key path. '{k}' is not a valid section.")
                    sys.exit(1)
                target = target[k]
            
            # Ensure the final target is a dictionary
            if not isinstance(target, dict):
                print(f"Error: Invalid configuration key path. Cannot set key on a non-object.")
                sys.exit(1)
            
            # Convert value types
            raw_value = value
            if raw_value.lower() == 'true':
                value = True
            elif raw_value.lower() == 'false':
                value = False
            else:
                try:
                    # Try to convert to integer first
                    value = int(raw_value)
                except ValueError:
                    try:
                        # If not an int, try float
                        value = float(raw_value)
                    except ValueError:
                        # Otherwise, keep as a string
                        value = raw_value
            
            target[keys[-1]] = value
            
            config_manager.save_config(config)
            print(f"✓ Set {key} = {value}")
            
        except Exception as e:
            logging.error(f"Error setting configuration for key '{key}': {e}", exc_info=True)
            print(f"✗ Error: Failed to set configuration value. See logs for details.")
            sys.exit(1)
    
    else:
        print("Use --show to view config or --set KEY VALUE to modify")


def handle_worker_diagnose(project_root: str, args):
    """Handle worker diagnose command."""
    from cli.worker_manager import WorkerManager
    from helpers.queue_manager import QueueManager
    from storage.config_manager import ConfigManager
    import os
    
    print("Running diagnostics...")
    print("=" * 50)
    
    # Check configuration
    config_path = os.path.join(project_root, '.code-query', 'config.json')
    try:
        config_manager = ConfigManager(config_path)
        config = config_manager.load_config()
        print(f"✓ Configuration loaded successfully")
        print(f"  - Processing mode: {config['processing']['mode']}")
        print(f"  - Dataset: {config['dataset_name']}")
    except Exception as e:
        print(f"✗ Configuration error: {e}")
        if args.fix:
            print("  → Creating default configuration...")
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            config_manager = ConfigManager(config_path)
            config_manager.create_default_config()
    
    # Check worker status
    worker_manager = WorkerManager(project_root)
    is_running, pid = worker_manager.get_worker_status()
    if is_running:
        print(f"✓ Worker is running (PID: {pid})")
    else:
        print("✗ Worker is not running")
    
    # Check queue
    queue_manager = QueueManager(project_root)
    status = queue_manager.get_queue_status()
    print(f"✓ Queue status:")
    print(f"  - Files in queue: {status['queued_files']}")
    print(f"  - Queue size: {status['total_size'] / 1024:.1f} KB")
    
    # Check directories
    dirs_to_check = [
        os.path.join(project_root, '.code-query'),
        os.path.join(project_root, '.code-query', 'queue'),
        os.path.join(project_root, '.code-query', 'logs')
    ]
    
    for dir_path in dirs_to_check:
        if os.path.exists(dir_path):
            print(f"✓ Directory exists: {dir_path}")
        else:
            print(f"✗ Directory missing: {dir_path}")
            if args.fix:
                print(f"  → Creating directory...")
                os.makedirs(dir_path, exist_ok=True)
    
    print("=" * 50)
    print("Diagnostics complete.")


def handle_queue_command(args, project_root: str):
    """Handle queue subcommands."""
    from helpers.queue_manager import QueueManager
    import json
    import time
    
    manager = QueueManager(project_root)
    
    if args.queue_command == 'status':
        status = manager.get_queue_status()
        print(f"📊 Queue Status")
        print(f"═══════════════")
        print(f"Files in queue: {status['queued_files']}")
        print(f"Total size: {format_size(status['total_size'])}")
        print(f"Unique commits: {len(status['by_commit'])}")
        
        if status['queued_files']:
            print(f"\nOldest file: {format_time_ago(status['oldest_entry'])}")
            print(f"Newest file: {format_time_ago(status['newest_entry'])}")
        
    elif args.queue_command == 'list':
        files = manager.list_queued_files()
        
        if args.json:
            print(json.dumps(files, indent=2))
        elif not files:
            print("📭 Queue is empty")
        else:
            if args.verbose:
                # Detailed view
                for file in files:
                    print(f"\n📄 {file['filepath']}")
                    print(f"   Size: {format_size(file['size'])}")
                    print(f"   Exists: {'✓' if file['exists'] else '✗'}")
                    print(f"   Added: {format_time_ago(file['timestamp'])}")
                    if file.get('commit'):
                        print(f"   Commit: {file['commit'][:8]}")
            else:
                # Simple list
                for file in files:
                    status = "✓" if file['exists'] else "✗"
                    print(f"{status} {file['filepath']} ({format_time_ago(file['timestamp'])})")
        
    elif args.queue_command == 'add':
        from helpers.git_helper import get_current_commit
        
        commit = args.commit or get_current_commit(project_root)
        files_to_add = []
        
        for filepath in args.files:
            # Check if file exists before realpath
            if not os.path.exists(filepath):
                print(f"⚠️  Skipping non-existent file: {filepath}")
                continue
            
            try:
                # Resolve the real path of the file, following symlinks
                real_file_path = os.path.realpath(filepath)
                
                # Securely check if the file is within the project root
                # Adding os.sep ensures we don't match partial directory names
                if not real_file_path.startswith(os.path.join(project_root, '')):
                    print(f"⚠️  Skipping file outside project: {filepath}")
                    continue
                
                rel_path = os.path.relpath(real_file_path, project_root)
                files_to_add.append((rel_path, commit))
            except Exception as e:
                print(f"⚠️  Skipping invalid path: {filepath} ({e})")
                continue
        
        if files_to_add:
            success = manager.add_files(files_to_add)
            if success:
                print(f"✓ Added {len(files_to_add)} file(s) to queue")
            else:
                print("✗ Failed to add files to queue")
                sys.exit(1)
    
    elif args.queue_command == 'remove':
        rel_paths = []
        for filepath in args.files:
            try:
                real_file_path = os.path.realpath(filepath)
                
                # Securely check if the file is within the project root
                if not real_file_path.startswith(os.path.join(project_root, '')):
                    print(f"⚠️  Skipping file outside project: {filepath}")
                    continue
                
                rel_path = os.path.relpath(real_file_path, project_root)
                rel_paths.append(rel_path)
            except Exception as e:
                print(f"⚠️  Skipping invalid path: {filepath} ({e})")
        
        if rel_paths:
            removed = manager.remove_files(rel_paths)
            print(f"✓ Removed {len(removed)} file(s) from queue")
    
    elif args.queue_command == 'clear':
        if not args.force:
            status = manager.get_queue_status()
            if status['queued_files'] > 0:
                response = input(f"Clear {status['queued_files']} file(s) from queue? [y/N]: ")
                if response.lower() != 'y':
                    print("Cancelled")
                    return
        
        if manager.clear_queue():
            print("✓ Queue cleared")
        else:
            print("✗ Failed to clear queue")
            sys.exit(1)
    
    elif args.queue_command == 'process':
        batch = manager.process_next_batch(
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )
        
        if args.json:
            print(json.dumps(batch, indent=2))
        else:
            if not batch:
                print("📭 No files to process")
            else:
                action = "Would process" if args.dry_run else "Processing"
                print(f"📦 {action} {len(batch)} file(s):")
                for file in batch:
                    print(f"  - {file['filepath']}")
    
    elif args.queue_command == 'cleanup':
        removed = manager.cleanup_missing_files(dry_run=args.dry_run)
        
        if args.dry_run:
            if removed:
                print(f"Would remove {len(removed)} missing file(s):")
                for path in removed:
                    print(f"  - {path}")
            else:
                print("✓ No missing files to clean up")
        else:
            if removed:
                print(f"✓ Removed {len(removed)} missing file(s) from queue")
            else:
                print("✓ No missing files to clean up")
    
    elif args.queue_command == 'history':
        history = manager.get_history(limit=args.lines)
        
        if not history:
            print("📜 No history available")
        else:
            print(f"📜 Queue History (last {args.lines} operations)")
            print("═" * 60)
            
            for entry in history:
                print(f"\n{entry['timestamp']} - {entry['operation']}")
                if entry.get('details'):
                    if isinstance(entry['details'], list):
                        for detail in entry['details'][:5]:
                            print(f"  - {detail}")
                        if len(entry['details']) > 5:
                            print(f"  ... and {len(entry['details']) - 5} more")
                    else:
                        print(f"  {entry['details']}")
    
    elif args.queue_command == 'watch':
        print("👀 Watching queue (Ctrl+C to stop)...")
        last_status = None
        
        try:
            while True:
                status = manager.get_queue_status()
                
                # Only update if something changed
                if status != last_status:
                    # Clear line and print new status
                    print(f"\r📊 Files: {status['queued_files']} | "
                          f"Size: {format_size(status['total_size'])} | "
                          f"Commits: {len(status['by_commit'])}", end='', flush=True)
                    
                    last_status = status
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\nStopped watching")
    
    else:
        print("Please specify a queue command. Use 'queue --help' for options.")
        sys.exit(1)


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


def format_time_ago(iso_time: str) -> str:
    """Format ISO timestamp as relative time."""
    from datetime import datetime
    
    try:
        dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
        delta = datetime.now() - dt
        
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds > 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"
    except (ValueError, TypeError):
        return iso_time


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description='Code Query MCP Server - CLI for server and worker management'
    )
    
    # Top-level arguments
    parser.add_argument(
        '--project-root',
        type=str,
        default=os.getcwd(),
        help='Project root directory (default: current directory)'
    )
    
    # Add subcommands
    subparsers = parser.add_subparsers(
        dest='command',
        help='Available commands'
    )
    
    # Server command (default behavior)
    server_parser = subparsers.add_parser(
        'server',
        help='Run the MCP server'
    )
    server_parser.add_argument(
        '--http',
        type=int,
        metavar='PORT',
        help='Run in HTTP mode on specified port'
    )
    server_parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='Host for HTTP mode (default: 127.0.0.1)'
    )
    
    # Add worker commands
    add_worker_commands(subparsers)
    
    # Add queue commands
    add_queue_commands(subparsers)
    
    # Parse arguments
    args = parser.parse_args()
    
    # Get project root - use realpath to resolve symlinks
    project_root = os.path.realpath(args.project_root)
    
    # Handle commands
    if args.command == 'server' or args.command is None:
        # Run MCP server (default behavior)
        handle_server_command(args)
    elif args.command == 'worker':
        handle_worker_command(args, project_root)
    elif args.command == 'queue':
        handle_queue_command(args, project_root)
    else:
        parser.print_help()
        sys.exit(1)


def handle_server_command(args):
    """Handle server command - run the MCP server."""
    # Import server module
    import sys
    sys.argv = ['server.py']  # Reset argv for server.py
    
    if hasattr(args, 'http') and args.http:
        sys.argv.extend(['--http', str(args.http)])
        if hasattr(args, 'host'):
            sys.argv.append(args.host)
    
    # Import and run the server
    from server import main_sync
    main_sync()


if __name__ == '__main__':
    main()