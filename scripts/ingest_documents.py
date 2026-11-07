"""Rebuild reviewed local knowledge with the active Python; never loads .env."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.ingestion import ingest


def main() -> int:
    try:
        report = ingest()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Ingestion failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    print(f"Documents: {report['documents_count']}; programs: {report['programs_count']}; "
          f"unique courses: {report['unique_courses_count']}; chunks: {report['chunks_count']}")
    print(f"Guide pages indexed: {report['guide_pages_indexed']}/{report['guide_pages_total']}; "
          f"excluded: {len(report['excluded_guide_pages'])}; index_ready=false")
    print("Outputs: storage/; review ingestion_report.json before implementing retrieval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
