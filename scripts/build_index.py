"""Build a local, versioned BM25 index from validated ingestion outputs."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.retrieval import build_index

if __name__ == "__main__":
    try:
        print(build_index())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Index build failed: {type(exc).__name__}. Re-run ingestion and review the local sources.", file=sys.stderr)
        raise SystemExit(1)
