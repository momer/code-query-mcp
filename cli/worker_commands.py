"""Worker management CLI commands."""

import click
import sys
import os
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.worker_manager import WorkerManager
from helpers.worker_detector import get_worker_info, cleanup_stale_pid_file


@click.group()
def worker():
    """Manage the background worker process."""
    pass


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
def start(project_root: str):
    """Start the background worker."""
    manager = WorkerManager(os.path.abspath(project_root))
    success = manager.start_worker()
    sys.exit(0 if success else 1)


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
def stop(project_root: str):
    """Stop the background worker."""
    manager = WorkerManager(os.path.abspath(project_root))
    success = manager.stop_worker()
    sys.exit(0 if success else 1)


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
def restart(project_root: str):
    """Restart the background worker."""
    manager = WorkerManager(os.path.abspath(project_root))
    success = manager.restart_worker()
    sys.exit(0 if success else 1)


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.option('--detailed', '-d', is_flag=True, help='Show detailed status')
def status(project_root: str, detailed: bool):
    """Check worker status."""
    project_root = os.path.abspath(project_root)
    
    if detailed:
        # Use the full status display from WorkerManager
        manager = WorkerManager(project_root)
        manager.display_worker_status()
    else:
        # Use lightweight detection for quick status
        info = get_worker_info(project_root)
        
        if not info:
            print("✗ Worker not configured")
            sys.exit(1)
        
        if info['running']:
            print(f"✓ Worker running (PID: {info['pid']})")
            print(f"  Started: {info['started_at']}")
            if info['uptime_seconds'] > 0:
                hours = info['uptime_seconds'] // 3600
                minutes = (info['uptime_seconds'] % 3600) // 60
                print(f"  Uptime: {hours}h {minutes}m")
        else:
            print(f"✗ Worker not running (stale PID: {info['pid']})")
            if cleanup_stale_pid_file(project_root):
                print("  Cleaned up stale PID file")
    
    sys.exit(0 if info and info['running'] else 1)


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
def logs(project_root: str):
    """Tail worker logs."""
    log_file = os.path.join(project_root, '.code-query', 'worker.log')
    
    if not os.path.exists(log_file):
        print("✗ No log file found")
        print(f"  Expected at: {log_file}")
        sys.exit(1)
    
    # Use tail command if available
    try:
        import subprocess
        subprocess.run(['tail', '-f', log_file])
    except (FileNotFoundError, KeyboardInterrupt):
        # Fallback to Python implementation
        try:
            import time  # Move import out of the loop
            with open(log_file, 'r') as f:
                # Go to end of file
                f.seek(0, 2)
                print("Following worker logs (Ctrl+C to stop)...")
                print("-" * 50)
                
                while True:
                    line = f.readline()
                    if line:
                        print(line.rstrip())
                    else:
                        time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nStopped following logs")


@worker.command()
@click.option('--project-root', default='.', help='Project root directory')
def cleanup(project_root: str):
    """Clean up stale worker files."""
    project_root = os.path.abspath(project_root)
    
    cleaned = False
    
    # Clean up stale PID file
    if cleanup_stale_pid_file(project_root):
        print("✓ Removed stale PID file")
        cleaned = True
    
    # Clean up empty directories
    code_query_dir = os.path.join(project_root, '.code-query')
    if os.path.exists(code_query_dir):
        for item in os.listdir(code_query_dir):
            item_path = os.path.join(code_query_dir, item)
            if os.path.isdir(item_path) and not os.listdir(item_path):
                os.rmdir(item_path)
                print(f"✓ Removed empty directory: {item}")
                cleaned = True
    
    if not cleaned:
        print("✓ Nothing to clean up")


if __name__ == '__main__':
    worker()