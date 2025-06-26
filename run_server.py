#!/usr/bin/env python3
import os
import sys

# Add the server directory to Python path for imports without changing working directory
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Import and run the server
from server import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())