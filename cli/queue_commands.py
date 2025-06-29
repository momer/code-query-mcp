"""Queue management CLI commands."""

import click
import sys
import os
import json
from typing import Optional
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.queue_manager import QueueManager


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


def format_time_ago(iso_time: str) -> str:
    """Format ISO timestamp as relative time."""
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


@click.group()
def queue():
    """Manage the file documentation queue."""
    pass


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
def status(project_root: str):
    """Show queue status and statistics."""
    manager = QueueManager(os.path.abspath(project_root))
    status = manager.get_queue_status()
    
    if status['status'] == 'empty':
        print("✓ Queue is empty")
        return
    
    print(f"📊 Queue Status")
    print(f"  Files waiting: {status['queued_files']}")
    print(f"  Total size: {format_size(status['total_size'])}")
    
    if status['oldest_entry']:
        print(f"  Oldest entry: {format_time_ago(status['oldest_entry'])}")
    
    if status['by_commit']:
        print("\n  By commit:")
        for commit, count in sorted(status['by_commit'].items(), key=lambda x: x[1], reverse=True):
            short_commit = commit[:7] if len(commit) > 7 else commit
            print(f"    {short_commit}: {count} file(s)")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.option('--limit', '-n', type=int, help='Number of files to show')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
def list(project_root: str, limit: Optional[int], verbose: bool):
    """List files in the queue."""
    manager = QueueManager(os.path.abspath(project_root))
    files = manager.list_queued_files(limit)
    
    if not files:
        print("✓ No files in queue")
        return
    
    print(f"📄 {len(files)} file(s) in queue:")
    
    for file_info in files:
        status_icon = "✓" if file_info['exists'] else "✗"
        print(f"\n  {status_icon} {file_info['filepath']}")
        
        if verbose:
            print(f"     Commit: {file_info['commit_hash']}")
            print(f"     Queued: {format_time_ago(file_info['queued_at'])}")
            
            if file_info['exists'] and 'size' in file_info:
                print(f"     Size: {format_size(file_info['size'])}")
                print(f"     Modified: {format_time_ago(file_info['modified'])}")
            elif not file_info['exists']:
                print("     ⚠️  File no longer exists")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.argument('files', nargs=-1, type=click.Path(exists=True, resolve_path=True))
def add(project_root: str, files):
    """Add files to the queue."""
    if not files:
        print("✗ No files specified")
        sys.exit(1)
    
    manager = QueueManager(os.path.abspath(project_root))
    
    # Get current commit
    import subprocess
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        commit_hash = result.stdout.strip() if result.returncode == 0 else 'HEAD'
    except:
        commit_hash = 'HEAD'
    
    # Validate and add files
    abs_project_root = os.path.abspath(project_root)
    files_to_add = []
    
    for abs_filepath in files:
        try:
            # Ensure the file is within the project root
            relative_path = os.path.relpath(abs_filepath, abs_project_root)
            if relative_path.startswith('..'):
                raise ValueError("Path is outside the project root.")
            files_to_add.append((relative_path, commit_hash))
        except ValueError:
            print(f"⚠️  Skipping file outside of project root: {abs_filepath}")
            continue
    
    if not files_to_add:
        print("✗ No valid files to add.")
        sys.exit(1)
    
    added = manager.add_files(files_to_add)
    
    print(f"✓ Added {added} file(s) to queue")
    if added < len(files_to_add):
        print(f"  ({len(files_to_add) - added} already in queue)")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.argument('files', nargs=-1)
def remove(project_root: str, files):
    """Remove specific files from the queue."""
    if not files:
        print("✗ No files specified")
        sys.exit(1)
    
    manager = QueueManager(os.path.abspath(project_root))
    removed = manager.remove_files(list(files))
    
    print(f"✓ Removed {removed} file(s) from queue")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation')
def clear(project_root: str, force: bool):
    """Clear all files from the queue."""
    manager = QueueManager(os.path.abspath(project_root))
    
    # Check current status
    status = manager.get_queue_status()
    if status['queued_files'] == 0:
        print("✓ Queue is already empty")
        return
    
    # Confirm
    if not force:
        click.confirm(f"Clear {status['queued_files']} file(s) from queue?", abort=True)
    
    cleared = manager.clear_queue()
    print(f"✓ Cleared {cleared} file(s) from queue")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.option('--batch-size', default=10, help='Number of files to process')
@click.option('--dry-run', is_flag=True, help='Show what would be processed')
def process(project_root: str, batch_size: int, dry_run: bool):
    """Process the next batch of files from the queue."""
    manager = QueueManager(os.path.abspath(project_root))
    
    if dry_run:
        files = manager.list_queued_files(batch_size)
        if not files:
            print("✓ No files to process")
            return
        
        print(f"Would process {len(files)} file(s):")
        for f in files:
            print(f"  - {f['filepath']}")
        return
    
    batch = manager.process_next_batch(batch_size)
    if not batch:
        print("✓ No files to process")
        return
    
    print(f"✓ Retrieved {len(batch)} file(s) for processing")
    
    # Output as JSON for potential piping
    if not sys.stdout.isatty():
        print(json.dumps(batch, indent=2))


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
def cleanup(project_root: str):
    """Remove entries for files that no longer exist."""
    manager = QueueManager(os.path.abspath(project_root))
    
    cleaned, files = manager.cleanup_missing_files()
    
    if cleaned == 0:
        print("✓ No missing files in queue")
        return
    
    print(f"✓ Removed {cleaned} missing file(s) from queue:")
    for f in files[:10]:  # Show first 10
        print(f"  - {f}")
    
    if len(files) > 10:
        print(f"  ... and {len(files) - 10} more")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
@click.option('--limit', '-n', default=20, help='Number of entries to show')
def history(project_root: str, limit: int):
    """Show queue operation history."""
    manager = QueueManager(os.path.abspath(project_root))
    
    entries = manager.get_history(limit)
    
    if not entries:
        print("✓ No history available")
        return
    
    print(f"📜 Recent queue operations:")
    
    for entry in entries:
        timestamp = format_time_ago(entry['timestamp'])
        operation = entry['operation']
        count = entry['count']
        
        # Format operation nicely
        op_display = {
            'processed_batch': '⚙️  Processed',
            'removed': '🗑️  Removed',
            'cleared': '🧹 Cleared',
            'cleanup_missing': '🔧 Cleaned up'
        }.get(operation, operation)
        
        print(f"\n  {timestamp}: {op_display} {count} file(s)")
        
        if 'details' in entry and entry['details']:
            for detail in entry['details'][:3]:
                print(f"    - {detail}")
            if len(entry['details']) > 3:
                print(f"    ... and {len(entry['details']) - 3} more")


@queue.command()
@click.option('--project-root', default='.', help='Project root directory')
def watch(project_root: str):
    """Watch queue status in real-time."""
    import time
    
    manager = QueueManager(os.path.abspath(project_root))
    
    print("👀 Watching queue (Ctrl+C to stop)...")
    print("-" * 50)
    
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


if __name__ == '__main__':
    queue()