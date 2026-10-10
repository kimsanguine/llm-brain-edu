"""Private fixed-operation worker. Note bodies arrive on stdin, not process arguments."""
import contextlib
import io
import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    payload = json.load(sys.stdin)
    sys.path.insert(0, str(root / "scripts"))
    import ingest
    from lib import pii
    # Reuse the existing note writer, including its exclusive file creation.
    with contextlib.redirect_stdout(io.StringIO()):
        saved = ingest.save_note(payload["text"])
    print(json.dumps({"source": saved.relative_to(root).as_posix(),
                      "privacy_warnings": pii.find_pii(payload["text"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
