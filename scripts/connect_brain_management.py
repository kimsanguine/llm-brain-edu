"""From the real Brain folder, preview or explicitly approve management setup."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_app.brain_management_setup import main

if __name__ == "__main__":
    main()
