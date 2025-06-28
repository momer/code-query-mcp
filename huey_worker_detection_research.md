# Huey Worker Detection Research Summary

## Overview

This document provides comprehensive information on detecting if a Huey worker process is running from within a git hook script, based on research of Huey's documentation, source code, and community resources.

## Key Findings

### 1. Built-in Worker Detection Methods

**Huey does NOT provide built-in methods to check if a worker is active** from external scripts. There is no `huey.is_consumer_running()` or similar API method. However, Huey provides several internal mechanisms:

- **Health Check System**: Configurable health checks with `check_worker_health=True` and `health_check_interval=1`
- **Process Monitoring**: Internal `is_alive()` checks for worker threads/processes
- **Stop Flag Mechanism**: Consumer uses stop flags to track running state

### 2. Standard Approaches for Detecting Running Consumers

#### A. Process-Based Detection
```python
import psutil
import subprocess

def is_huey_consumer_running():
    """Check if huey consumer process is running by process name"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if 'huey_consumer' in cmdline or 'huey.bin.consumer' in cmdline:
                return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False, None

def check_consumer_by_pid_file(pid_file_path):
    """Check if consumer is running using PID file"""
    try:
        with open(pid_file_path, 'r') as f:
            pid = int(f.read().strip())
        return psutil.pid_exists(pid)
    except (FileNotFoundError, ValueError):
        return False
```

#### B. Redis-Based Detection
```python
import redis

def check_huey_consumer_via_redis(redis_host='localhost', redis_port=6379, queue_name='huey'):
    """Check if consumer is active by monitoring Redis activity"""
    try:
        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        
        # Check if there are pending tasks
        queue_length = r.llen(queue_name)
        
        # Check Redis connection (if consumer is connected, Redis should be accessible)
        r.ping()
        
        return {
            'redis_accessible': True,
            'queue_length': queue_length,
            'likely_consumer_available': True  # Redis is accessible
        }
    except redis.ConnectionError:
        return {
            'redis_accessible': False,
            'queue_length': None,
            'likely_consumer_available': False
        }
```

#### C. Signal-Based Monitoring (Advanced)
```python
from huey import RedisHuey
from huey.constants import EmptyData
from huey.signals import SIGNAL_EXECUTING, SIGNAL_COMPLETE, SIGNAL_ERROR, SIGNAL_REVOKED
import os

EXECUTING_PREFIX = "executing"
redis_addr = os.getenv("REDIS", "localhost")
huey = RedisHuey('my-app', host=redis_addr)

def get_executing_task_count():
    """Get count of currently executing tasks"""
    try:
        matching = list(
            filter(
                lambda key: key.decode().startswith(f"{EXECUTING_PREFIX}-"),
                huey.storage.conn.hgetall(huey.storage.result_key).keys()
            )
        )
        return len(matching)
    except Exception:
        return 0

def is_consumer_processing_tasks():
    """Check if consumer is actively processing tasks"""
    return get_executing_task_count() > 0

# Signal handlers to track executing tasks
@huey.signal(SIGNAL_EXECUTING)
def task_signal_executing(signal, task):
    huey.storage.put_data(f"{EXECUTING_PREFIX}-{task.id}", 1)

@huey.signal(SIGNAL_COMPLETE)
def task_signal_complete(signal, task):
    huey.storage.delete_data(f"{EXECUTING_PREFIX}-{task.id}")

@huey.signal(SIGNAL_ERROR, SIGNAL_REVOKED)
def task_signal_error(signal, task, exc=None):
    huey.storage.delete_data(f"{EXECUTING_PREFIX}-{task.id}")
```

### 3. PID Files, Lock Files, and Mechanisms

#### PID File Management
```python
import os
import fcntl
import atexit

class HueyPidFile:
    def __init__(self, pid_file_path):
        self.pid_file_path = pid_file_path
        self.pid_file = None
    
    def acquire(self):
        """Acquire PID file lock"""
        try:
            self.pid_file = open(self.pid_file_path, 'w')
            fcntl.lockf(self.pid_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.pid_file.write(str(os.getpid()))
            self.pid_file.flush()
            atexit.register(self.release)
            return True
        except IOError:
            return False
    
    def release(self):
        """Release PID file lock"""
        if self.pid_file:
            fcntl.lockf(self.pid_file.fileno(), fcntl.LOCK_UN)
            self.pid_file.close()
            try:
                os.unlink(self.pid_file_path)
            except OSError:
                pass

def check_huey_pid_lock(pid_file_path):
    """Check if Huey consumer is running via PID file"""
    temp_pid = HueyPidFile(pid_file_path)
    if temp_pid.acquire():
        temp_pid.release()
        return False  # No consumer running
    else:
        return True  # Consumer is running
```

### 4. Git Hook Script Detection

#### Complete Git Hook Example
```bash
#!/bin/bash
# Git hook script to detect Huey worker availability

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/check_huey_worker.py"

# Create Python checker script
cat > "$PYTHON_SCRIPT" << 'EOF'
#!/usr/bin/env python3
import sys
import psutil
import redis
import json

def check_huey_worker():
    results = {
        'process_running': False,
        'redis_accessible': False,
        'queue_length': 0,
        'worker_available': False
    }
    
    # Check for running processes
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if 'huey_consumer' in cmdline:
                results['process_running'] = True
                break
        except:
            continue
    
    # Check Redis connectivity
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        results['redis_accessible'] = True
        results['queue_length'] = r.llen('huey')  # Default queue name
    except:
        pass
    
    results['worker_available'] = results['process_running'] and results['redis_accessible']
    return results

if __name__ == '__main__':
    result = check_huey_worker()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['worker_available'] else 1)
EOF

chmod +x "$PYTHON_SCRIPT"

# Run the checker
if python3 "$PYTHON_SCRIPT"; then
    echo "Huey worker is available - proceeding with task enqueueing"
    # Add your task enqueueing logic here
else
    echo "Huey worker not available - skipping background tasks"
    # Handle the case where no worker is available
fi

# Cleanup
rm -f "$PYTHON_SCRIPT"
```

### 5. Task Enqueueing Without Workers

**When you enqueue tasks with no worker running:**

- ✅ **Tasks are safely stored** in Redis LIST and won't be lost
- ✅ **FIFO order preserved** - tasks processed in order when worker comes online
- ✅ **No immediate failure** - enqueue operation succeeds
- ✅ **Tasks persist** until processed or Redis is restarted (without persistence)
- ✅ **Workers automatically pick up queued tasks** when they start

#### Example Queue Monitoring
```python
def monitor_task_queue(redis_host='localhost', queue_name='huey'):
    """Monitor task queue status"""
    try:
        r = redis.Redis(host=redis_host, decode_responses=True)
        queue_length = r.llen(queue_name)
        
        return {
            'status': 'healthy' if queue_length >= 0 else 'error',
            'pending_tasks': queue_length,
            'can_enqueue': True
        }
    except redis.ConnectionError:
        return {
            'status': 'redis_down',
            'pending_tasks': None,
            'can_enqueue': False
        }
```

## Recommended Approach for Git Hooks

### Option 1: Simple Process Check (Recommended)
```python
#!/usr/bin/env python3
def quick_huey_check():
    """Quick check if Huey consumer is likely running"""
    import psutil
    
    for proc in psutil.process_iter(['cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if 'huey_consumer' in cmdline or 'huey/bin/consumer' in cmdline:
                return True
        except:
            continue
    return False

if __name__ == '__main__':
    import sys
    sys.exit(0 if quick_huey_check() else 1)
```

### Option 2: Redis Health Check
```python
#!/usr/bin/env python3
def redis_health_check():
    """Check if Redis is accessible for task enqueueing"""
    import redis
    
    try:
        r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=1)
        r.ping()
        return True
    except:
        return False

if __name__ == '__main__':
    import sys
    sys.exit(0 if redis_health_check() else 1)
```

## Key Takeaways

1. **No built-in API** for external worker detection
2. **Process monitoring** is the most reliable approach
3. **Redis connectivity** indicates queue availability
4. **Tasks queue safely** even without active workers
5. **Multiple detection strategies** should be combined for reliability
6. **PID files/locks** require manual implementation
7. **Health monitoring** should be implemented at the application level

## Dependencies Required

```bash
pip install psutil redis
```

For git hooks, ensure these packages are available in the environment where the hooks execute.