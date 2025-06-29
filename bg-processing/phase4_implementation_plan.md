# Phase 4: Worker Detection Implementation Plan

## Overview
Enhance worker detection to ensure hooks can reliably determine if the background worker is available for processing tasks.

## Current State
- Basic PID file checking with os.kill(pid, 0)
- No process name validation
- No handling of stale PID files

## Implementation Tasks

### 1. Enhanced Worker Detection
**File**: `cli/worker_manager.py`
- Add process name/cmdline validation
- Implement stale PID file cleanup
- Add worker health check endpoint

### 2. Update Hook Handler
**File**: `helpers/git_hook_handler.py`
- Use enhanced detection in `_is_worker_running()`
- Add fallback for detection failures
- Better error messages

### 3. Worker Status Command
**File**: `cli/worker_manager.py`
- Add detailed status output
- Show worker uptime
- Display current queue size

## Key Improvements
1. **Process Validation**: Verify PID belongs to our worker
2. **Stale PID Cleanup**: Remove PID files from crashed workers
3. **Health Checks**: Ensure worker is responsive, not just running
4. **Better Diagnostics**: Clear messages about worker state

## Security Considerations
- Validate PID file contents before use
- Prevent PID file tampering
- Safe process inspection

## Testing Plan
- Test with running worker
- Test with stale PID file
- Test with wrong process using same PID
- Test detection performance