# Code Query MCP Server

A Model Context Protocol (MCP) server for searching and querying code review JSON files. This server provides RAG-like capabilities to efficiently search through large codebases without loading all data into context.

## Quick Start

1. Install the MCP server:
   ```bash
   claude mcp add code-query -s user -- python ~/mcp-servers/code-query-mcp/server.py
   ```

2. Restart Claude

3. Ask Claude to use the MCP:
   ```
   "Use the code-query MCP to import data from 'tmp/index' directory as 'my_project'"
   "Use the code-query MCP to search for 'authentication' in my_project"
   ```

## Features

- **Dynamic Data Loading**: Import JSON files during conversation, not at startup
- **Persistent Storage**: SQLite database persists between MCP calls
- **Multi-Dataset Support**: Load and query multiple datasets with unique names
- **Efficient Search**: Query specific files without loading entire dataset
- **Security**: Path validation prevents directory traversal attacks
- **Cross-Project Usage**: Works from any directory once installed

## Installation

### Prerequisites
- Python 3.11 or higher
- pip package manager

### Option 1: Claude Code CLI (Recommended)

1. Copy the server to a permanent location:
   ```bash
   # Create a directory for MCP servers
   mkdir -p ~/mcp-servers
   
   # Copy or clone this repository
   cp -r /path/to/code-query-mcp ~/mcp-servers/
   # OR
   git clone <repository-url> ~/mcp-servers/code-query-mcp
   
   # Install dependencies
   cd ~/mcp-servers/code-query-mcp
   pip install -r requirements.txt
   ```

2. Add the MCP server to Claude Code (use absolute path):
   ```bash
   claude mcp add code-query -s user -- python ~/mcp-servers/code-query-mcp/server.py
   ```
   
   **Note**: The path to `server.py` must be absolute. The `~` expands to your home directory.

3. Verify installation:
   ```bash
   claude mcp list
   # Should show 'code-query' in the list
   ```

4. Test it's working:
   ```bash
   claude "Use the code-query MCP to check its status"
   ```

### Option 2: Claude Desktop

1. Copy the server to a permanent location (same as Option 1, step 1)

2. Configure Claude Desktop:
   - Open Claude Desktop settings
   - Navigate to Developer → Model Context Protocol
   - Edit the configuration file:
     - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
     - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
     - Linux: `~/.config/Claude/claude_desktop_config.json`

3. Add the MCP server configuration:
   ```json
   {
     "mcpServers": {
       "code-query": {
         "command": "python",
         "args": ["/absolute/path/to/code-query-mcp/server.py"]
       }
     }
   }
   ```

4. Restart Claude Desktop for changes to take effect

## Usage

### Important: How to Use in Claude

After installing the MCP server, you need to ask Claude to use the code-query MCP tools. Here are two ways to do this:

#### Method 1: Direct Request (Recommended)
Simply ask Claude to use the specific tool:

```
"Use the code-query MCP to import data from the 'tmp/index' directory as 'my_project'"
"Use the code-query MCP to search for 'authentication' in the my_project dataset"
"Use the code-query MCP to get details for src/auth/login.ts from my_project"
```

#### Dataset Discovery
If you don't know what datasets are available or forget the dataset name:

```
"Use the code-query MCP to list all datasets"
"Use the code-query MCP to search for 'authentication'" (Claude will automatically list datasets first)
```

The MCP will guide Claude to use the `list_datasets` tool whenever a dataset name is needed but unknown.

#### Method 2: Explicit Tool Names
If Claude doesn't automatically recognize the request, you can be more explicit:

```
"Call the mcp code-query import_data tool with dataset_name='my_project' and directory='tmp/index'"
"Call the mcp code-query search_files tool with query='authentication' and dataset_name='my_project'"
```

### Tool Reference

#### 1. Import Your Data

Import your code review JSON files from your current working directory:

**Ask Claude:**
```
"Use code-query MCP to import data from 'tmp/index' directory as 'claude-acorn-gui'"
```

**Tool call:** `import_data(dataset_name, directory, replace?)`
- `dataset_name`: A unique name for your dataset
- `directory`: Path to directory containing JSON files (relative to current directory)
- `replace`: Optional boolean to replace existing dataset

**Response:**
```json
{
  "success": true,
  "files_loaded": 135,
  "source": "tmp/index"
}
```

#### 2. Search for Files

Search for files containing specific keywords:

**Ask Claude:**
```
"Use code-query MCP to search for 'temperature' in the claude-acorn-gui dataset"
```

**Tool call:** `search_files(query, dataset_name, limit?)`
- `query`: Search term
- `dataset_name`: Which dataset to search
- `limit`: Optional max results (default: 10)

**Response:**
```json
[
  {
    "filepath": "src/features/device-management/hooks/useTemperatureData.ts",
    "filename": "useTemperatureData.ts",
    "overview": "Hook for managing temperature sensor data",
    "ddd_context": "device-management"
  }
]
```

#### 3. Get File Details

Get complete details for a specific file. Now supports partial path matching!

**Ask Claude:**
```
"Use code-query MCP to get details for login.ts from claude-acorn-gui"
"Use code-query MCP to get details for auth/login from claude-acorn-gui"
"Use code-query MCP to get details for src/auth/login.ts from claude-acorn-gui"
```

**Tool call:** `get_file(filepath, dataset_name, limit?)`
- `filepath`: Full or partial path to the file (use % for wildcards)
- `dataset_name`: Which dataset contains the file
- `limit`: Optional max results for partial matches (default: 10)

**Response:**
```json
{
  "filepath": "src/features/auth/login.ts",
  "filename": "login.ts",
  "overview": "Authentication login component",
  "functions": {...},
  "exports": {...},
  "imports": {...},
  "types_interfaces_classes": {...},
  "constants": {...},
  "dependencies": [...],
  "other_notes": [...]
}
```

If multiple files match, returns an array of results.

#### 4. List Domains

See all DDD domains in your project:

**Ask Claude:**
```
"Use code-query MCP to list all domains in claude-acorn-gui"
```

**Tool call:** `list_domains(dataset_name)`

#### 5. List Datasets

See all loaded datasets:

**Ask Claude:**
```
"Use code-query MCP to list all datasets"
```

**Tool call:** `list_datasets()`

#### 6. Check Status

See database status and statistics:

**Ask Claude:**
```
"Use code-query MCP to check status"
```

**Tool call:** `get_status()`

#### 7. Clear Dataset

Remove a dataset when no longer needed:

**Ask Claude:**
```
"Use code-query MCP to clear the old_project dataset"
```

**Tool call:** `clear_dataset(dataset_name)`

#### 8. Document Directory (NEW!)

Generate orchestration instructions for documenting a codebase:

**Ask Claude:**
```
"Use code-query MCP to document the src directory as 'my-project'"
"Use code-query MCP to document the src directory as 'my-project', excluding test files and node_modules"
```

**Tool call:** `document_directory(dataset_name, directory, exclude_patterns?, batch_size?)`
- `dataset_name`: Name for the dataset
- `directory`: Directory to document
- `exclude_patterns`: Optional patterns to exclude (e.g., ["*.test.js", "temp/*"])
- `batch_size`: Files per agent batch (default: 20)

**Response:** Returns orchestration instructions for Claude to create subagents that will analyze the code and use the `insert_file_documentation` tool to store results.

**Workflow:**
1. Claude calls `document_directory` to get instructions
2. Claude creates multiple subagents based on the batches
3. Each agent analyzes their assigned files
4. Agents use `insert_file_documentation` to store results
5. Progress is tracked until completion

## MCP Tools Reference

| Tool | Description | Parameters |
|------|-------------|------------|
| `import_data` | Import JSON files from directory | `dataset_name`, `directory`, `replace?` |
| `search_files` | Search within dataset | `query`, `dataset_name`, `limit?` |
| `get_file` | Get full file details (supports partial matching) | `filepath`, `dataset_name`, `limit?` |
| `list_domains` | List DDD contexts | `dataset_name` |
| `list_datasets` | Show all loaded datasets | - |
| `get_status` | Database status and statistics | - |
| `clear_dataset` | Remove a dataset | `dataset_name` |
| `document_directory` | Generate instructions for code documentation | `dataset_name`, `directory`, `exclude_patterns?`, `batch_size?` |
| `insert_file_documentation` | Insert analyzed file data (used by agents) | `dataset_name`, `filepath`, `filename`, `overview`, etc. |
| `update_file_documentation` | Update existing file documentation | `dataset_name`, `filepath`, plus any fields to update |
| `get_project_config` | Get project configuration | - |
| `install_pre_commit_hook` | Install git pre-commit hook | `dataset_name`, `mode?` |
| `create_project_config` | Create/update project configuration | `dataset_name`, `exclude_patterns?` |

**Note**: When a tool requires a `dataset_name` but you don't know it, the tool descriptions will guide Claude to use `list_datasets` first to discover available datasets.

## Data Format

The server expects JSON files containing arrays of objects with the following structure:

```json
{
  "filepath": "src/features/example/file.ts",
  "filename": "file.ts",
  "overview": "Brief description of the file",
  "functions": {
    "functionName": {
      "purpose": "What it does",
      "parameters": ["param1: type"],
      "returns": "ReturnType"
    }
  },
  "exports": {
    "exportName": "export description"
  },
  "imports": {
    "from": ["what", "is", "imported"]
  },
  "types_interfaces_classes": {
    "TypeName": "type definition or description"
  },
  "constants": {
    "CONST_NAME": "value or description"
  },
  "ddd_context": "domain-name",
  "dependencies": ["react", "other-lib"],
  "other_notes": ["Additional observations"]
}
```

## Storage

### Database Location
The server creates a `.mcp_code_query/` directory in your current working directory containing:
- `code_data.db`: SQLite database with all imported data

### Persistence
- Data persists between MCP calls
- Database remains available across Claude conversations
- Import data once per project, query many times
- Database location follows your current working directory

### Multi-Project Support
- Each project's data is stored with a unique dataset name
- Switch between projects by using different dataset names
- No need to reimport data when switching directories

## Security

### Path Validation
- Only relative paths are allowed (no absolute paths)
- Parent directory traversal (`..`) is blocked
- All paths are validated against the current working directory

### Data Isolation
- Each dataset is isolated by name
- Cannot query across datasets
- Clear datasets individually when needed

## Architecture Notes

### Database Design
- Single-table architecture with `dataset_id` column
- Prevents SQL injection from dynamic table creation
- Efficient indexing on `dataset_id` and `filepath`

### Performance
- SQLite provides fast full-text search
- Queries are limited by default to prevent large result sets
- JSON fields are parsed only when retrieving specific files

### Error Handling
- Graceful handling of missing files
- Detailed error messages for troubleshooting
- Logging for debugging import issues

## Troubleshooting

### Claude doesn't recognize the MCP commands
If you try to use `import_data()` directly and Claude doesn't recognize it:
1. **Restart Claude** after installing/updating the MCP server
2. Use explicit requests like: "Use the code-query MCP to import data..."
3. Check the MCP is installed: Run `claude mcp list` in terminal
4. Verify the server has no errors: Check the MCP logs

### MCP tools not appearing
If the MCP tools aren't available in Claude:
1. Ensure the server.py file has no syntax errors
2. Check that all `Tool` imports are correct (not `types.Tool`)
3. Restart Claude to reload the MCP server
4. Try reinstalling the MCP: `claude mcp remove code-query` then add it again

### No JSON files found
- Ensure your JSON files match the pattern `agent_*_review.json` or `*.json`
- Check that the directory path is relative to your current working directory
- Verify file permissions

### Import fails
- Check the JSON file format matches the expected structure
- Look for error messages in the import result
- Ensure write permissions for `.mcp_code_query/` directory

### Search returns no results
- Verify the dataset name is correct
- Check that data was successfully imported
- Try broader search terms

### Database location issues
- The database is always created in the current working directory
- If you change directories, the database location changes too
- Use `get_status()` to see the current database path

## Example Workflow

### Option 1: Import Existing JSON Files
1. **Initial Setup** (one time):
   ```
   cd /path/to/your/project
   > import_data("my_project", "tmp/index")
   ```

2. **Daily Usage**:
   ```
   > search_files("authentication", "my_project")
   > get_file("login.ts", "my_project")  # Partial path matching!
   ```

### Option 2: Document Directory Directly (NEW!)
1. **Document your codebase**:
   ```
   cd /path/to/your/project
   > document_directory("my_project", "src", ["*.test.js", "node_modules"])
   ```
   Claude will orchestrate agents to analyze and document all code files.

2. **Query your documented code**:
   ```
   > search_files("authentication", "my_project")
   > get_file("login", "my_project")  # Find any login file
   > list_domains("my_project")       # See DDD structure
   ```

### Cross-Project Usage
```
cd /path/to/another/project
> document_directory("another_project", ".", ["dist/*", "build/*"])
> search_files("api", "another_project")
```

### Cleanup
```
> clear_dataset("old_project")
```

## Git Pre-commit Hook Integration

The MCP includes a git pre-commit hook system that automatically queues changed files for documentation updates.

### Installation

**Ask Claude:**
```
"Use code-query MCP to install pre-commit hook for dataset 'my-project'"
```

This will:
1. Create `.code-query/config.json` with your project settings
2. Install a lightweight pre-commit hook to `.git/hooks/pre-commit`
3. Create `.code-query/git-doc-update` script for processing queued files
4. Set up `.code-query/.gitignore` to exclude the queue file

### How It Works

1. **Commit Changes**: When you commit, the hook automatically queues changed files
   ```bash
   git add src/new-feature.js
   git commit -m "Add new feature"
   # Output: 📄 Code Query: 1 file(s) queued for documentation update.
   ```

2. **Update Documentation**: Run the update script when convenient
   ```bash
   .code-query/git-doc-update
   # Shows queued files, estimates time, asks for confirmation
   # Calls Claude to analyze and update documentation
   ```

3. **Queue Management**: 
   - Files are queued in `.code-query/update_queue.txt`
   - Duplicates are automatically prevented
   - Queue persists until processed
   - Successfully processed files are removed from queue

### Configuration

The `.code-query/config.json` file stores:
```json
{
  "datasetName": "my-project",
  "mode": "queue",
  "excludePatterns": ["*.test.js", "*.spec.ts", "node_modules/*", ".git/*"],
  "createdAt": "2024-01-01T00:00:00.000Z"
}
```

### Tips

- Create an alias for easier access:
  ```bash
  alias git-doc-update='.code-query/git-doc-update'
  ```

- Check project configuration:
  ```
  "Use code-query MCP to get project config"
  ```

- The hook is non-blocking - commits always succeed
- Documentation updates require internet access (for Claude API)
- Each file takes 5-30 seconds to analyze

### Create Project Configuration

If you need to create or update a project configuration file (e.g., data was imported but no config exists):

**Ask Claude:**
```
"Use code-query MCP to create project config for dataset 'my-project'"
"Use code-query MCP to create project config for 'my-project' excluding ['*.log', 'tmp/*']"
```

This creates `.code-query/config.json` with:
- Dataset name
- Exclude patterns (defaults to common patterns like test files, node_modules, build dirs)
- Creation/update timestamps

## License

[Your license here]

## Contributing

[Contributing guidelines if applicable]
