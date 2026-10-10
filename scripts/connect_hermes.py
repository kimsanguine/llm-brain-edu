"""Run from the Brain folder: check first, register only with explicit approval."""
import sys
from pathlib import Path

# Keep this entry point independent of macOS/Windows activation commands.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_app.hermes_bundle_setup import main

if __name__ == "__main__":
    main()
