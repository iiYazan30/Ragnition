# Step 1: ingest the reviewed university source bundle

You are working in an existing Windows Python 3.14 project at C:\Users\Hp\rag-advisor.
The existing FastAPI scaffold and Groq connection already work. Preserve their public API contract.
Read the repository instructions, contracts/api-v1.md, schemas, config, and current ingestion/retrieval/RAG services before editing.
Never read, print, include in logs, or commit the contents of .env or any API key.

The attached source bundle is extracted under data/najah_v2/. If it is not there, locate the extracted bundle within this project; do not search the Internet or fetch new academic facts.
Read its README_AR.md, validation_summary.json, and data/knowledge/sources.json first.

Implement ingestion only in this step. Do not call an LLM or embedding API, select a new model/provider, or fabricate a working RAG response.

Inputs and scope:
- data/knowledge/courses.jsonl: 372 course rows (125 computer engineering, 123 medicine, 64 physical education, 60 vehicle engineering).
- data/knowledge/programs.json: exactly four target programs. Sports is major 11350, plan 2025-1. Exclude the older 80531 variant.
- data/raw/dlyl_ltlb_25.pdf: original university student guide, edition 2026/2027, 135 PDF pages.
- Three public HTML files contain original course rows, saved with Windows-1256 encoding. Their JSON rows are already extracted; do not duplicate the same facts by indexing HTML again.
- Vehicle rows come from a prior transcription PDF. Preserve their derived-source provenance and partial coverage. Do not label them as independently verified original university text.
- The mechanical engineering 10621/2021-1 plan is reference material, not a fifth target program and not the vehicle plan.

Tasks:
1. Create a repeatable CLI such as scripts/ingest_documents.py, using existing project structure. Use pathlib and the active virtual environment; ensure Windows compatibility.
2. Load and validate course/program/source records. Keep course codes as strings. Preserve exact source prerequisite expressions, including AND groups, OR alternatives and concurrency wording. A blank prerequisite field means not listed, not confirmed absent.
3. Produce stable document and chunk IDs. Course chunks should contain program, plan, code, names, credits, requirement group, and confirmed source-row constraints. Keep the citation quote as actual supplied source text. Attach program_id, major_code, plan_version, evidence_status and source locator metadata.
4. Extract the original guide page by page with a suitable PDF library available for Python 3.14; add only the necessary dependency if missing. Keep actual one-based PDF page numbers. Chunk within a page with modest overlap, preserving article/section headings. Store the actual page text and source excerpts, never synthesized quotes. Check that the Arabic extraction is usable; report unreadable pages instead of indexing empty or corrupt text as successful.
5. Write the document catalog, normalized chunks and ingestion report under storage/. Use UTF-8, stable IDs, idempotent rebuilds and atomic writes where practical. Keep original sources available for later source-file endpoints.
6. Exclude all reference_only/ files, prompts, README, test answers and evaluation materials from the default knowledge index. In particular, NEVER insert inferred vehicle prerequisites into official course facts.
7. Preserve version conflicts as metadata: CE 2021-1 is 162 credits; the guide summary differs. Vehicle shows 137 total plus an unresolved separate free-course panel. Vehicle elective options and official prerequisites are missing. Do not fill these gaps with model knowledge or analogies.
8. Do not extend the current API schema silently. HTML sources have course/section locators rather than PDF pages; store page=null internally. Preserve actual PDF page numbers for PDF sources. Note any citation-contract adjustment needed for the next step.
9. Keep index_ready=false until a functioning retrieval index exists; having extracted chunks alone must not make /api/chat return fabricated grounded answers. The health endpoint may report actual catalog/chunk counts consistent with its existing contract.
10. Run one meaningful ingestion smoke check: 372 unique course IDs, exactly four target programs, the correct 11350 sports code, no inferred prerequisites in indexed vehicle rows, and nonempty source excerpts with valid locators. Do not make live Groq calls.

Finish by reporting changed files, exact PowerShell commands to run ingestion, resulting counts, and remaining issues relevant to retrieval. Keep the explanation short and in Arabic. Stop before implementing retrieval so we can agree on the retrieval approach next.
