# Background Processing Implementation Review - Phase 3

## Project Context
We're implementing background processing for the Code Query MCP Server. We've completed:
- Phase 1: Huey task definitions (with security fixes)
- Phase 2: Worker management (with RCE fix)
- Phase 3: Git hook logic (NEW - needs review)

## Phase 3: Git Hook Logic

### What We Built
1. **GitHookHandler** (`helpers/git_hook_handler.py`):
   - Manages post-commit hook execution
   - Decides between sync/async processing based on configuration
   - Handles queue operations atomically
   - Never blocks git commits (always returns 0)

2. **Hook Installation** (`helpers/git_helper.py`):
   - Added `install_git_hooks()` function
   - Properly handles git worktrees
   - Creates executable Python-based hooks

### Key Design Decisions
- **Cross-platform process checking**: Uses `os.kill(pid, 0)` instead of psutil
- **Atomic queue operations**: temp file + rename pattern
- **Import safety**: Try/except around Huey imports with fallback
- **User feedback**: Clear messages for all scenarios
- **Never block commits**: All paths return 0

### Security Considerations
- Hook adds project root to PYTHONPATH - is this safe?
- Subprocess calls use list format (no shell injection)
- Queue file operations are atomic
- Config loading has error handling

### Architecture Notes
- Sync processing calls `python server.py document-file` (placeholder command)
- Async processing imports tasks.py and enqueues directly
- Queue format: JSON with 'files' array containing filepath/commit_hash
- Worker detection via PID file existence and os.kill check

## Files to Review
1. `/home/momer/projects/dcek/code-query-mcp/helpers/git_hook_handler.py` (NEW)
2. `/home/momer/projects/dcek/code-query-mcp/helpers/git_helper.py` (modified - added install_git_hooks)
3. `/home/momer/projects/dcek/code-query-mcp/bg-processing/phase3_implementation_summary.md`

## Critical Questions
1. Is adding project root to PYTHONPATH in the hook safe?
2. Should we validate file paths in the queue before processing?
3. Is the worker detection method reliable enough?
4. Any race conditions in queue handling we missed?
5. Should hooks have rate limiting or other protections?

## Testing Performed
- Module imports successfully
- Hook installation creates executable file
- Basic function calls work
- Haven't tested full end-to-end flow yet

Please review for:
- Security vulnerabilities (especially path injection)
- Race conditions in queue handling
- Error handling completeness
- Cross-platform compatibility issues
- Any design flaws in the sync/async decision logic