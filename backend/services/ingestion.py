"""Offline ingestion of the reviewed bundle; no retrieval index or provider calls."""

from collections import Counter
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import unicodedata

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUIDE_ID = "najah_student_guide_2026_2027"
TARGETS = {
    "computer_engineering": ("10636", "2021-1", 125, 162),
    "medicine": ("10702", "2025-1", 123, 266),
    "physical_education": ("11350", "2025-1", 64, 131),
    "vehicle_engineering": ("10624", "2026-1", 60, 137),
}
# Boundaries checked against the original guide, not inferred from course plans.
GUIDE_SECTIONS = {
    35: ("bachelor_instructions_and_program_summaries", None, None),
    75: ("general_student_provisions", None, None),
    93: ("biomedical_bachelor_instructions", "medicine", "biomedical_basic"),
    97: ("doctor_of_medicine_instructions", "medicine", "clinical"),
    111: ("student_discipline", None, None),
    118: ("student_services_and_guidance", None, None),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_for_check(text: str) -> str:
    # Only quality/heading checks use normalization; evidence stays verbatim.
    return unicodedata.normalize("NFKC", text).replace("ـ", "")


def page_quality(text: str) -> str:
    body = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.strip().isdigit()
        and "An-Najah National University" not in line
        and not ("دليل الطالب" in line and "2026" in line)
    )
    if not text.strip():
        return "empty_or_image_only"
    if not body.strip():
        return "header_only"
    checked = normalized_for_check(body)
    letters = [c for c in checked if c.isalpha()]
    arabic = [c for c in letters if "ARABIC" in unicodedata.name(c, "")]
    bad = sum(c == "\ufffd" or unicodedata.category(c) in {"Co", "Cc"}
              for c in checked if not c.isspace())
    if "(cid:" in checked or bad > max(1, len(checked) * 0.01):
        return "corrupt_text"
    if len(arabic) < 20 or len(arabic) / max(1, len(letters)) < 0.2:
        return "insufficient_arabic_body"
    return "usable_text_layer"


def page_spans(text: str, size: int = 1400, overlap: int = 160):
    """Exact page slices; prefer line breaks and never cross PDF pages."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary >= 0:
                end = boundary + 1
        yield start, end
        if end == len(text):
            break
        boundary = text.find("\n", max(start + 1, end - overlap), end - 1)
        start = boundary + 1 if boundary >= 0 else end - overlap


def headings(text: str) -> list[dict]:
    result, offset = [], 0
    for line in text.splitlines(keepends=True):
        checked = normalized_for_check(line).strip()
        if len(checked) <= 180 and re.search(
            r"(?:المادة|مادة)\s*[:(]*\s*\d|\d+\s*[():]*\s*(?:المادة|مادة)\b"
            r"|^(?:الباب|الفصل|تعليمات|أحكام|نظام)\b", checked
        ):
            result.append({"offset": offset, "text": line.strip()})
        offset += len(line)
    return result


def load_records(root: Path):
    knowledge = root / "data/data/knowledge"
    programs = read_json(knowledge / "programs.json")
    sources = read_json(knowledge / "sources.json")
    courses = [json.loads(line) for line in
               (knowledge / "courses.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    require(isinstance(programs, list) and len(programs) == 4, "Expected four programs")
    require(isinstance(sources, list) and len(sources) == 5, "Expected five sources")
    program_map = {p["program_id"]: p for p in programs}
    source_map = {s["document_id"]: s for s in sources}
    require(set(program_map) == set(TARGETS), "Unexpected or duplicate target program")
    require(len(source_map) == 5 and GUIDE_ID in source_map, "Invalid source IDs")
    require({p["source_document_id"] for p in programs} | {GUIDE_ID} == set(source_map),
            "Only target program sources and the original guide are allowed")

    catalog, pdfs = [], {}
    raw_root = (root / "data/data/raw").resolve()
    require(raw_root.is_relative_to(root), "Raw sources must stay inside the project")
    for source in sources:
        relative = Path(source["relative_path"])
        require(relative.parts == ("data", "raw", source["filename"]), "Invalid raw source path")
        path = (root / "data" / relative).resolve()
        require(path.is_relative_to(raw_root) and path.is_file(), "Missing or unsafe source file")
        require(path.suffix.lower() in {".pdf", ".htm"}, "Only declared PDF/HTML sources are allowed")
        require(nonblank(source["source_type"]) and nonblank(source["index_policy"]),
                "Source provenance and policy are required")
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        page_count = None
        if path.suffix.lower() == ".pdf":
            pdfs[source["document_id"]] = PdfReader(path)
            page_count = len(pdfs[source["document_id"]].pages)
        else:
            require(path.suffix.lower() == ".htm" and source.get("encoding") == "windows-1256",
                    "Expected the saved Windows-1256 HTML source")
            path.read_text(encoding="cp1256")
        catalog.append({**source, "relative_path": path.relative_to(root).as_posix(),
                        "page_count": page_count, "sha256": checksum,
                        "title": "دليل الطالب 2026/2027" if source["document_id"] == GUIDE_ID
                        else next(p["program_name_ar"] for p in programs
                                  if p["source_document_id"] == source["document_id"]),
                        "content_indexing": "page_text" if source["document_id"] == GUIDE_ID
                        else "normalized_course_rows_only"})
    require(GUIDE_ID in pdfs and len(pdfs[GUIDE_ID].pages) == 135,
            "Original guide must contain 135 PDF pages")
    require(source_map[GUIDE_ID].get("source_type") == "original_university_student_guide_pdf"
            and source_map[GUIDE_ID].get("edition") == "2026/2027"
            and source_map[GUIDE_ID].get("page_count") == 135, "Invalid guide metadata")
    for pid, (major, plan, count, credits) in TARGETS.items():
        program = program_map[pid]
        require((program["major_code"], program["plan_version"], program["course_rows"],
                 program["total_required_credits"]) == (major, plan, count, credits),
                f"Unexpected plan metadata: {pid}")
        require(nonblank(program["program_name_ar"]) and
                program["source_filename"] == source_map[program["source_document_id"]]["filename"],
                f"Invalid program source: {pid}")
        require(isinstance(program["credit_groups"], list) and bool(program["credit_groups"]),
                "Missing program credit groups")
        for group in program["credit_groups"]:
            require(nonblank(group["name_ar"]) and type(group["required_credits"]) is int
                    and group["required_credits"] >= 0, "Invalid credit group")

    ids = set()
    for row in courses:
        pid = row["program_id"]
        require(pid in program_map, "Course belongs to an excluded program")
        program = program_map[pid]
        require(row["record_type"] == "course" and nonblank(row["id"]) and row["id"] not in ids,
                "Invalid or duplicate course ID")
        ids.add(row["id"])
        require(isinstance(row["course_code"], str) and row["course_code"].isascii()
                and row["course_code"].isdigit(), "Course codes must remain digit strings")
        for field in ("major_code", "plan_version", "program_name_ar"):
            require(row[field] == program[field], f"Course/program mismatch: {field}")
        require(nonblank(row["course_name_ar"]) and nonblank(row["requirement_group_ar"]),
                "Missing course name or requirement group")
        require(type(row["credits"]) in (int, float) and math.isfinite(row["credits"])
                and row["credits"] >= 0, "Invalid course credits")
        minimum = row["minimum_completed_credits"]
        require(minimum is None or (type(minimum) is int and minimum >= 0),
                "Invalid source-row completed-credit constraint")
        require(row["passing_grade_raw"] is None or isinstance(row["passing_grade_raw"], str),
                "Passing-grade source text must remain a string")
        citation = row["citation"]
        require(citation["document_id"] == program["source_document_id"] and
                citation["filename"] == program["source_filename"], "Invalid course source")
        require(nonblank(citation["quote"]) and nonblank(citation["article"])
                and row["course_code"] in citation["quote"], "Missing source excerpt or locator")
        expression = row["prerequisite_expression_raw"]
        require(expression is None or isinstance(expression, str), "Invalid prerequisite expression")
        if pid == "vehicle_engineering":
            require(expression is None and row["prerequisite_status"] == "not_provided_for_this_plan"
                    and row["index_as_official"] is False
                    and row["index_for_course_catalog_with_provenance"] is True
                    and row["evidence_status"] ==
                    "prior_pack_transcription_not_fully_reverified_against_original_images"
                    and row["minimum_completed_credits"] is None and row["passing_grade_raw"] is None,
                    "Vehicle rows must not contain official or inferred prerequisites")
            require("derived_transcription" in source_map[citation["document_id"]]["source_type"],
                    "Vehicle source must retain derived provenance")
            page = citation["page"]
            pdf = pdfs[citation["document_id"]]
            require(type(page) is int and 1 <= page <= len(pdf.pages), "Invalid vehicle PDF page")
            require(citation["quote"] in (pdf.pages[page - 1].extract_text() or ""),
                    "Vehicle quote is not supplied PDF text")
        else:
            require(citation["page"] is None and row["index_as_official"] is True
                    and row["evidence_status"] == "direct_source_row", "Invalid HTML evidence metadata")
            require(source_map[citation["document_id"]]["source_type"] ==
                    "official_public_zajel_html_saved_by_user", "Expected original public HTML")
            expected = "listed_in_this_plan" if expression and expression.strip() else "not_listed_in_source_row"
            require(row["prerequisite_status"] == expected, "Blank is not confirmed absence of prerequisites")
            require(not expression or not expression.strip() or expression in citation["quote"],
                    "Prerequisite expression must be verbatim source-row text")
    require(len(courses) == 372, "Expected 372 course rows")
    require(Counter(r["program_id"] for r in courses) ==
            Counter({pid: target[2] for pid, target in TARGETS.items()}), "Unexpected course distribution")
    require(len({(r["program_id"], r["plan_version"], r["course_code"]) for r in courses}) == 372,
            "Duplicate program-plan-course identity")
    return programs, courses, catalog, pdfs[GUIDE_ID]


def course_chunk(row: dict) -> dict:
    # Keep every supplied constraint and provenance field, including unofficial translations.
    text = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in row.items()
                     if key != "citation")
    return {**row, "chunk_id": row["id"] + ":chunk:001", "chunk_type": "course",
            "document_id": row["citation"]["document_id"], "text": text,
            "source_locator": {"page": row["citation"]["page"],
                               "section": row["requirement_group_ar"],
                               "course_code": row["course_code"],
                               "article": row["citation"]["article"]}}


def guide_records(pdf: PdfReader):
    pages, chunks = [], []
    section = None
    for number, pdf_page in enumerate(pdf.pages, 1):
        error = None
        try:
            text = pdf_page.extract_text() or ""
            quality = page_quality(text)
        except Exception as exc:
            text, quality, error = "", "extraction_error", type(exc).__name__
        if number in GUIDE_SECTIONS:
            name, program, phase = GUIDE_SECTIONS[number]
            section = {"id": name, "heading_page": number, "program_id": program,
                       "academic_phase": phase,
                       "heading_text": "\n".join(text.splitlines()[2:5]).strip()}
        page_headings = headings(text)
        pages.append({"document_id": GUIDE_ID, "page": number, "text": text,
                      "quality": quality, "error": error, "headings": page_headings,
                      "section": deepcopy(section)})
        if quality != "usable_text_layer":
            continue
        for index, (start, end) in enumerate(page_spans(text), 1):
            quote = text[start:end]
            previous = [h["text"] for h in page_headings if h["offset"] <= start]
            article = previous[-1] if previous else None
            chunks.append({
                "chunk_id": f"{GUIDE_ID}:page:{number:03d}:chunk:{index:03d}",
                "chunk_type": "guide_page", "document_id": GUIDE_ID,
                "program_id": section["program_id"] if section else None,
                "major_code": "10702" if section and section["program_id"] == "medicine" else None,
                "plan_version": None, "edition": "2026/2027",
                "academic_phase": section["academic_phase"] if section else None,
                "section": deepcopy(section), "headings": [h for h in page_headings
                                                           if start <= h["offset"] < end],
                "scope_status": "section_context_only; consult_source_for_applicability_and_effective_years",
                "evidence_status": "original_university_pdf_text_layer",
                "text": quote, "citation": {"document_id": GUIDE_ID,
                    "filename": "dlyl_ltlb_25.pdf", "page": number, "article": article, "quote": quote},
                "source_locator": {"page": number, "char_start": start, "char_end": end},
            })
    require(bool(chunks), "No usable Arabic guide pages; OCR or extraction review is required")
    return pages, chunks


def encode_json(value, *, lines=False) -> bytes:
    text = ("\n".join(json.dumps(row, ensure_ascii=False, allow_nan=False) for row in value)
            if lines else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    return (text + "\n").encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class SourceText(HTMLParser):
    """Extract visible text without running any saved HTML or script."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"br", "tr", "td", "th", "div", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip -= 1

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


def program_chunks(root: Path, programs: list, catalog: list) -> list:
    result = []
    for program in programs:
        doc = next(d for d in catalog if d["document_id"] == program["source_document_id"])
        path = root / doc["relative_path"]
        derived = program["program_id"] == "vehicle_engineering"
        if derived:
            quote = PdfReader(path).pages[0].extract_text()
            # Source instructions are quoted evidence only; they never govern execution.
            start, end = quote.index("Total required:"), quote.index("This extract includes")
            quote = quote[start:end].strip()
            page = 1
        else:
            parser = SourceText()
            parser.feed(path.read_text(encoding="cp1256"))
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
            start = text.index("الخطة: سنة")
            match = re.search(r"مجموع الساعات المطلوبة:\s*" + str(program["total_required_credits"]) + r"\b", text[start:])
            require(match is not None, "Program total requires an original source excerpt")
            quote, page = text[start:start + match.end()], None
        result.append({
            **program, "chunk_id": program["source_document_id"] + ":program_summary",
            "chunk_type": "program_summary", "document_id": program["source_document_id"],
            "evidence_status": "derived_transcription_partial_coverage" if derived else "direct_source_program_header",
            "index_as_official": not derived,
            "text": json.dumps(program, ensure_ascii=False) + "\n" + quote,
            "citation": {"document_id": program["source_document_id"], "filename": program["source_filename"],
                         "page": page, "article": "ملخص الخطة ومجموع الساعات المطلوبة", "quote": quote},
            "source_locator": {"page": page, "section": "program_header", "major_code": program["major_code"]},
        })
    return result


def ingest(project_root: Path = PROJECT_ROOT, storage_dir: Path | None = None) -> dict:
    root = project_root.resolve()
    programs, courses, catalog, guide = load_records(root)
    pages, guide_chunks = guide_records(guide)
    programs = deepcopy(programs)
    ce = next(p for p in programs if p["program_id"] == "computer_engineering")
    conflict_quote = next((line for line in pages[46]["text"].splitlines()
                           if "هندسة الحاسوب" in line and "163" in line), None)
    require(conflict_quote is not None, "Guide/CE credit conflict requires source review")
    ce["known_conflicts"] = [{"field": "total_required_credits", "plan_value": 162,
                              "guide_summary_value": 163, "resolution": "unresolved_separate_versions",
                              "citation": {"document_id": GUIDE_ID, "page": 47, "quote": conflict_quote}}]
    summaries = program_chunks(root, programs, catalog)
    chunks = [course_chunk(row) for row in sorted(courses, key=lambda row: row["id"])] + summaries + guide_chunks
    require(len({c["chunk_id"] for c in chunks}) == len(chunks), "Duplicate chunk IDs")
    artifacts = {
        "documents.json": encode_json(catalog),
        "programs.json": encode_json(programs),
        "chunks.jsonl": encode_json(chunks, lines=True),
        "guide_pages.jsonl": encode_json(pages, lines=True),
    }
    report = {
        "schema_version": 1, "status": "extracted_with_review_notes", "index_ready": False,
        "documents_count": len(catalog), "programs_count": len(programs),
        "unique_courses_count": len(courses), "course_chunks_count": len(courses),
        "program_summary_chunks_count": len(summaries),
        "course_rows_by_program": dict(Counter(row["program_id"] for row in courses)),
        "guide_pages_total": len(pages), "guide_pages_indexed": sum(p["quality"] == "usable_text_layer" for p in pages),
        "guide_chunks_count": len(guide_chunks), "chunks_count": len(chunks),
        "guide_page_quality_counts": dict(Counter(p["quality"] for p in pages)),
        "excluded_guide_pages": [{"page": p["page"], "reason": p["quality"], "error": p["error"]}
                                 for p in pages if p["quality"] != "usable_text_layer"],
        "coverage_review": {
            "method": "Local visual review of all 20 excluded PDF pages on 2026-11-07",
            "blank_pages": [2, 134],
            "photographic_pages_without_academic_rules": [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 26, 30],
            "section_divider": [75], "sample_exam_material": [130, 131, 132, 133],
            "back_cover_branding": [135], "substantive_academic_pages_with_failed_extraction": [],
            "limitation": "115/135 pages selected; numeric table layout and mixed-direction text still require source review.",
        },
        "arabic_quality_check": "Heuristic: >=20 Arabic letters, >=20% of letters Arabic; reject empty/header-only/corrupt text. Not full visual or OCR verification.",
        "excluded_inputs": ["data/reference_only/", "README and prompts", "evaluation and test answers",
                            "duplicate HTML/PDF course text"],
        "retrieval_notes": [
            "No retrieval index, embeddings or LLM calls. API readiness remains false.",
            "Citation.page currently requires an integer; HTML needs nullable page plus course/section locators in an agreed next-step contract. DocumentEntry.page_count also needs nullable HTML support.",
            "CE plan 2021-1 is 162 credits; guide summary is 163 (PDF page 47). Keep both versions separate.",
            "Vehicle: derived transcription, 60 required rows only, missing 9-credit elective options and official prerequisites; 137 total conflicts with separate 2-credit free-course panel. Four-year duration is user-declared only.",
            "A blank prerequisite is not listed, not a confirmed absence. Raw AND/OR/concurrency expressions are not interpreted.",
            "Guide tables can concatenate numeric cells and mixed RTL/LTR text can reorder fragments; review original PDF for numeric rules. Exact extracted text is retained, not reconstructed.",
            "Guide edition is not a course-plan version. Medicine biomedical/clinical sections retain separate scope; applicability and effective years require source review.",
            "Excluded guide pages require visual review and possibly local OCR; they are not successful indexed pages.",
        ],
        "artifacts_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in artifacts.items()},
        "knowledge_sha256": {name: hashlib.sha256((root / "data/data/knowledge" / name).read_bytes()).hexdigest()
                             for name in ("courses.jsonl", "programs.json", "sources.json")},
    }
    output = storage_dir if storage_dir is not None else root / "storage"
    output.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        atomic_write(output / name, content)
    # Publish the report last; hashes let future readers reject an interrupted mixed rebuild.
    atomic_write(output / "ingestion_report.json", encode_json(report))
    return report
