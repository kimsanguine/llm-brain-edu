"""Run in the real Brain folder. Preview first, then approve the target profile."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wiki_app.hermes_bundle_setup import main

if __name__ == "__main__":
    main()
