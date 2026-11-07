"""Local BM25, exact course lookup and conservative scope resolution; no embeddings."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from backend.schemas import AcademicContext

from backend.services.ingestion import PROJECT_ROOT, atomic_write, encode_json, read_json, require

INDEX_VERSION = "bm25-ar-1"
STORAGE = PROJECT_ROOT / "storage"
# Search vocabulary only: these aliases do not supply course or university facts.
QUERY_ALIASES = {"شو": "ما", "قديش": "كم", "بدها": "متطلبات سابقة", "بده": "متطلبات سابقة",
                 "بتحتاج": "متطلبات سابقة", "بدي": "اريد", "ماده": "مساق", "مواد": "مساقات",
                 "كمبيوتر": "حاسوب", "رياضه": "رياضة", "ساعه": "ساعة", "ساعاتها": "ساعات",
                 "متطلبها": "متطلبات سابقة", "متطلباتها": "متطلبات سابقة"}
PROGRAM_ALIASES = {
    "computer_engineering": ("هندسة الحاسوب", "الحاسوب", "حاسوب", "كمبيوتر", "computer engineering", "10636"),
    "medicine": ("الطب البشري", "الطب", "طب", "medicine", "10702"),
    "physical_education": ("التربية الرياضية", "الرياضة", "رياضة", "sports", "11350"),
    "vehicle_engineering": ("هندسة المركبات", "المركبات", "مركبات", "vehicle", "10624"),
}
STOP_WORDS = set("ما ماذا كم هل من في على عن الى ان او و هو هي هذا هذه انا اريد عندي لي لو ممكن وين كيف شو قديش الذي التي تخصص خطة نسخه سنة فصل جامعة النجاح الوطنية".split())
ACADEMIC_WORDS = set("مساق مساقات مادة مواد متطلب متطلبات السابقة سابق ساعات ساعة تسجيل اسجل دراسه دراسة معدل امتحان امتحانات قبول تخرج جامعه جامعة منحه منحة رسوم خطة تخصص بكالوريوس سريري سريرية حيويه حيوية انسحاب رسوب نجاح علامات".split())
ACADEMIC_WORDS |= {"ال" + word for word in ACADEMIC_WORDS}
INTENT_WORDS = set("متطلب متطلبات سابق سابقة السابق السابقة ساعة ساعات مجموع اجمالي مطلوب المطلوبة تخرج انهاء".split())


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("ـ", "")
    text = "".join(str(unicodedata.digit(c)) if c.isdecimal() else c
                   for c in text if unicodedata.category(c) != "Mn")
    return text.translate(str.maketrans("أإآٱ", "اااا"))


def tokens(text: str, aliases=False) -> list[str]:
    words = re.findall(r"[^\W_]+", normalize(text), re.UNICODE)
    if aliases:
        words = [part for word in words for part in QUERY_ALIASES.get(word, word).split()]
    return [word for word in words if word not in STOP_WORDS]


def phrase(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", normalize(text)))


def explicit_scope(question: str):
    text = " " + phrase(question) + " "
    programs = {pid for pid, aliases in PROGRAM_ALIASES.items()
                if any(" " + phrase(alias) + " " in text for alias in aliases)}
    text = normalize(question)
    plans = {f"{year}-{semester}" for year, semester in re.findall(r"\b(20\d{2})\s*[-/]\s*([1-9])\b", text)}
    plans.update(re.findall(r"(?:خطة|خطه|plan)\s+(20\d{2})\b(?!\s*[-/])", text))
    return programs, plans


def searchable(chunk: dict) -> str:
    if chunk["chunk_type"] == "course":
        # Avoid indexing schema keys, flags and provenance boilerplate as academic content.
        fields = ("course_code", "course_name_ar", "course_name_en", "program_name_ar", "plan_version",
                  "requirement_group_ar", "prerequisite_expression_raw")
        return " ".join(str(chunk.get(key) or "") for key in fields) + " " + chunk["citation"]["quote"]
    return " ".join(str(chunk.get(k) or "") for k in ("program_name_ar", "plan_version", "text"))


def checked_catalog(root: Path, storage: Path):
    report = read_json(storage / "ingestion_report.json")
    require(set(report.get("knowledge_sha256", {})) == {"courses.jsonl", "programs.json", "sources.json"},
            "Re-run ingestion to fingerprint the original records")
    for name, expected in report["knowledge_sha256"].items():
        require(hashlib.sha256((root / "data/data/knowledge" / name).read_bytes()).hexdigest() == expected,
                "Knowledge records changed; re-run ingestion")
    for name, expected in report["artifacts_sha256"].items():
        require(name in {"documents.json", "programs.json", "chunks.jsonl", "guide_pages.jsonl"}, "Unexpected artifact")
        require(hashlib.sha256((storage / name).read_bytes()).hexdigest() == expected, "Stale ingestion artifacts")
    require(set(report["artifacts_sha256"]) == {"documents.json", "programs.json", "chunks.jsonl", "guide_pages.jsonl"},
            "Incomplete ingestion artifacts")
    documents = read_json(storage / "documents.json")
    raw_root = (root / "data/data/raw").resolve()
    require(raw_root.is_relative_to(root.resolve()), "Unsafe raw directory")
    for doc in documents:
        relative = Path(doc["relative_path"])
        require(relative.parts == ("data", "data", "raw", doc["filename"]), "Unsafe catalog path")
        path = (root / relative).resolve()
        require(path.is_relative_to(raw_root) and path.is_file() and path.suffix in {".htm", ".pdf"}, "Unsafe source")
        with path.open("rb") as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == doc["sha256"], "Source file changed")
    chunks = [json.loads(line) for line in (storage / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    require(len(chunks) == report["chunks_count"] and bool(chunks), "Invalid chunk count")
    docmap = {d["document_id"]: d for d in documents}
    require(len(docmap) == len(documents), "Duplicate documents")
    require(len({c["chunk_id"] for c in chunks}) == len(chunks), "Duplicate chunks")
    for chunk in chunks:
        doc = docmap[chunk["document_id"]]
        require(chunk["chunk_type"] in {"course", "program_summary", "guide_page"}, "Unexpected chunk type")
        citation = chunk["citation"]
        require(citation["quote"].strip() and citation["document_id"] == doc["document_id"]
                and citation["filename"] == doc["filename"], "Invalid evidence")
        page = citation["page"]
        require((page is None and doc["page_count"] is None and bool(citation["article"])) or
                (type(page) is int and type(doc["page_count"]) is int and 1 <= page <= doc["page_count"]),
                "Invalid source locator")
        if chunk.get("program_id") == "vehicle_engineering":
            require(chunk.get("index_as_official") is False and "transcription" in chunk["evidence_status"],
                    "Vehicle provenance was lost")
            if chunk["chunk_type"] == "course":
                require(chunk["prerequisite_expression_raw"] is None
                        and chunk["prerequisite_status"] == "not_provided_for_this_plan", "Inferred prerequisite")
    return report, documents, chunks


def term_index(chunks):
    postings = defaultdict(list)
    lengths = []
    for ordinal, chunk in enumerate(chunks):
        counts = Counter(tokens(searchable(chunk)))
        lengths.append(sum(counts.values()))
        for term, count in counts.items():
            postings[term].append([ordinal, count])
    return dict(postings), lengths


def build_index(root: Path = PROJECT_ROOT, storage: Path = STORAGE) -> dict:
    report, documents, chunks = checked_catalog(root, storage)
    require(sum(c["chunk_type"] == "program_summary" for c in chunks) == 4, "Re-run ingestion for four source-backed program summaries")
    postings, lengths = term_index(chunks)
    data = {"version": INDEX_VERSION, "ingestion_report_sha256": hashlib.sha256((storage / "ingestion_report.json").read_bytes()).hexdigest(),
            "postings": postings, "lengths": lengths}
    atomic_write(storage / "retrieval_index.json", encode_json(data))
    _cached_index.cache_clear()
    return {"index_ready": True, "documents_count": len(documents), "chunks_count": len(chunks)}


@dataclass
class SearchResult:
    status: str = "evidence"
    message: str = ""
    program_id: str | None = None
    plan_version: str | None = None
    hits: list[dict] = field(default_factory=list)


class RetrievalIndex:
    def __init__(self, root: Path, storage: Path):
        self.root, self.storage = root, storage
        self.report, documents, self.chunks = checked_catalog(root, storage)
        self.documents = {doc["document_id"]: doc for doc in documents}
        data = read_json(storage / "retrieval_index.json")
        require(data["version"] == INDEX_VERSION and data["ingestion_report_sha256"] ==
                hashlib.sha256((storage / "ingestion_report.json").read_bytes()).hexdigest(), "Stale retrieval index")
        # This corpus is small: recomputing verifies persisted postings and prevents partial/corrupt loads.
        postings, lengths = term_index(self.chunks)
        require(data["postings"] == postings and data["lengths"] == lengths, "Invalid BM25 data")
        self.postings, self.lengths = postings, lengths
        self.average_length = sum(lengths) / len(lengths)
        require(self.average_length > 0, "Empty search index")
        self.courses = [c for c in self.chunks if c["chunk_type"] == "course"]
        self.programs = {c["program_id"]: c for c in self.chunks if c["chunk_type"] == "program_summary"}

    def search(self, question: str, history=(), limit=6, *, academic_context: AcademicContext | None = None) -> SearchResult:
        programs, plans = explicit_scope(question)
        if len(programs) > 1 or len(plans) > 1:
            return SearchResult("needs_clarification", "حدّد تخصصاً واحداً ونسخة خطة واحدة للسؤال.")
        pid, plan = next(iter(programs), None), next(iter(plans), None)
        if pid is None:
            for message in reversed(history):
                if message.role != "user":
                    continue
                old_programs, old_plans = explicit_scope(message.content)
                if len(old_programs) == 1:
                    pid = next(iter(old_programs))
                    if plan is None and len(old_plans) == 1:
                        plan = next(iter(old_plans))
                    break
        if pid is None and academic_context is not None:
            pid = academic_context.program_id
            if plan is None:
                plan = academic_context.plan_version
        if plan and len(plan) == 4:
            return SearchResult("needs_clarification", "حدّد نسخة الخطة بالسنة والفصل، مثل 2021-1.", pid, plan)
        query_tokens = set(tokens(question, aliases=True))
        canonical = " " + phrase(question) + " "
        codes = set(re.findall(r"\b\d{7,9}\b", normalize(question)))
        followup = set(re.findall(r"[^\W_]+", normalize(question))) & {
            "بدها", "بده", "متطلبها", "متطلباتها", "ساعاتها", "ساعاته", "نفسها", "نفسه"}
        if not codes and followup:
            recent = next((m.content for m in reversed(history) if m.role == "user"), "")
            previous_codes = set(re.findall(r"\b\d{7,9}\b", normalize(recent)))
            if not previous_codes:
                previous_codes = {c["course_code"] for c in self.courses
                                  if " " + phrase(c["course_name_ar"]) + " " in " " + phrase(recent) + " "
                                  and (not pid or c["program_id"] == pid)}
            if len(previous_codes) == 1:
                codes = previous_codes
                query_tokens |= codes
        exact = [c for c in self.courses if c["course_code"] in codes] if codes else []
        named = [c for c in self.courses if " " + phrase(c["course_name_ar"]) + " " in canonical]
        matches = exact if codes else named
        if pid:
            matches = [c for c in matches if c["program_id"] == pid]
        if plan:
            matches = [c for c in matches if c["plan_version"] == plan]
        identities = {(c["program_id"], c["plan_version"]) for c in matches}
        if not pid and len(identities) > 1:
            return SearchResult("needs_clarification", "المساق موجود في أكثر من تخصص/خطة؛ ما تخصصك ونسخة خطتك؟")
        if not pid and len(identities) == 1:
            pid = next(iter(identities))[0]
        if pid and plan and self.programs[pid]["plan_version"] != plan:
            return SearchResult("insufficient_evidence", "نسخة الخطة المطلوبة غير متوفرة في المصادر الحالية.", pid, plan)
        if codes and not matches:
            return SearchResult("insufficient_evidence", "لم أجد المساق بهذا الرمز ضمن التخصص والخطة المحددين.", pid, plan)
        if pid and plan is None:
            plan = self.programs[pid]["plan_version"]
        prereq = bool(query_tokens & {"متطلب", "متطلبات", "سابق", "سابقة", "السابقة", "قبل", "تفتح", "افتح"})
        rule_words = {"العبء", "للعبء", "الحد", "الاعلى", "مسموح", "اقصى", "السريرية", "الفصل", "السنة"}
        total = not matches and (bool(query_tokens & {"مجموع", "اجمالي", "تخرج"}) or
                                (bool(query_tokens & {"ساعة", "ساعات"}) and not query_tokens & rule_words))
        academic = bool(programs or codes or matches or followup or query_tokens & ACADEMIC_WORDS)
        if not academic:
            return SearchResult("out_of_scope", "أساعد في الأسئلة الأكاديمية التي تغطيها مصادر جامعة النجاح المتاحة.")
        if total and not pid:
            return SearchResult("needs_clarification", "لأي تخصص ونسخة خطة تريد معرفة مجموع الساعات؟")
        if pid == "vehicle_engineering" and (prereq or query_tokens & {"اختياري", "الاختياري", "اختيارية"}):
            return SearchResult("insufficient_evidence", "المتاح لخطة المركبات 10624 / 2026-1 تفريغ مشتق جزئي؛ المتطلبات السابقة الرسمية وخيارات الاختياري غير متوفرة. لا يعني ذلك عدم وجود متطلبات.", pid, plan)
        if prereq and matches and all(not c.get("prerequisite_expression_raw") for c in matches):
            return SearchResult("insufficient_evidence", "حقل المتطلبات السابقة غير مدرج في صف المساق المتاح؛ لا يمكن تأكيد عدم وجود متطلب.", pid, plan)
        if pid == "medicine" and not matches and not total and not query_tokens & {"سريري", "السريرية", "سريرية", "الحيوية", "حيوية", "bbms"}:
            return SearchResult("needs_clarification", "هل تقصد مرحلة العلوم الطبية الحيوية أم المرحلة السريرية في الطب؟", pid, plan)

        allowed = set()
        phase = "clinical" if query_tokens & {"سريري", "السريرية", "سريرية"} else (
            "biomedical_basic" if query_tokens & {"الحيوية", "حيوية", "bbms"} else None)
        matched_ids = {c["chunk_id"] for c in matches}
        for ordinal, chunk in enumerate(self.chunks):
            if pid and chunk.get("program_id") not in {None, pid}:
                continue
            if plan and chunk.get("plan_version") not in {None, plan}:
                continue
            if phase and not total and chunk.get("academic_phase") != phase:
                continue
            if matched_ids and chunk["chunk_id"] not in matched_ids:
                continue
            conflict = total and pid == "computer_engineering" and chunk["chunk_type"] == "guide_page" and (
                chunk["citation"]["page"] == 47 and "163" in chunk["citation"]["quote"])
            if total and chunk["chunk_type"] != "program_summary" and not conflict:
                continue
            allowed.add(ordinal)
        context_terms = set(STOP_WORDS) | INTENT_WORDS
        for aliases in PROGRAM_ALIASES.values():
            for alias in aliases:
                context_terms.update(tokens(alias))
        context_terms.update({"المرحلة", "السريرية", "السريري", "سريري", "حيوية", "الحيوية", "العلوم", "الطبية"})
        useful = query_tokens - context_terms
        # shortcut: reject unknown content words instead of guessing synonyms; expand documented aliases when needed.
        unknown = {term for term in useful if term not in self.postings and len(term) > 3}
        if not matches and not total and (unknown or not any(useful & set(tokens(searchable(self.chunks[i]))) for i in allowed)):
            return SearchResult("insufficient_evidence", "لا تتوفر أدلة مناسبة لهذا السؤال الأكاديمي في المصادر الحالية.", pid, plan)
        scores = defaultdict(float)
        count = len(self.chunks)
        for term in query_tokens:
            postings = self.postings.get(term, ())
            idf = math.log(1 + (count - len(postings) + 0.5) / (len(postings) + 0.5))
            for ordinal, frequency in postings:
                if ordinal in allowed:
                    denominator = frequency + 1.5 * (0.25 + 0.75 * self.lengths[ordinal] / self.average_length)
                    scores[ordinal] += idf * frequency * 2.5 / denominator * (0.15 if term in context_terms else 1)
        for ordinal in allowed:
            if self.chunks[ordinal]["chunk_id"] in matched_ids:
                scores[ordinal] += 100 if codes else 30
            if total:
                scores[ordinal] += 40 if self.chunks[ordinal]["chunk_type"] == "program_summary" else 10
        hits, seen = [], set()
        for ordinal, score in sorted(scores.items(), key=lambda item: (-item[1], self.chunks[item[0]]["chunk_id"])):
            chunk = self.chunks[ordinal]
            key = (chunk["document_id"], chunk["citation"]["page"], chunk["citation"]["quote"])
            if score <= 0 or key in seen:
                continue
            # Adjacent page slices overlap; one excerpt per guide page keeps the context bounded.
            if chunk["chunk_type"] == "guide_page" and any(h["chunk"]["source_locator"]["page"] == chunk["source_locator"]["page"]
                                                                      and h["chunk"]["chunk_type"] == "guide_page" for h in hits):
                continue
            hits.append({"score": round(score, 6), "chunk": chunk})
            seen.add(key)
            if len(hits) == min(limit, 6):
                break
        return SearchResult("evidence" if hits else "insufficient_evidence",
                            "" if hits else "لم أجد دليلاً مناسباً في المصادر الحالية.", pid, plan, hits)


@lru_cache(maxsize=1)
def _cached_index(signature):
    return RetrievalIndex(PROJECT_ROOT, STORAGE)


def get_index() -> RetrievalIndex | None:
    try:
        # Detect edits, replacements and rebuilds without repeatedly hashing the 36 MB guide.
        files = [STORAGE / name for name in ("retrieval_index.json", "ingestion_report.json", "chunks.jsonl",
                                              "documents.json", "programs.json", "guide_pages.jsonl")]
        files += list((PROJECT_ROOT / "data/data/raw").glob("*"))
        files += [PROJECT_ROOT / "data/data/knowledge" / name for name in ("courses.jsonl", "programs.json", "sources.json")]
        signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size) for p in files)
        return _cached_index(signature)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def get_catalog():
    """A validated catalog stays available even before an index has been built."""
    try:
        report, documents, chunks = checked_catalog(PROJECT_ROOT, STORAGE)
        return {d["document_id"]: d for d in documents}, len(chunks)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}, 0
