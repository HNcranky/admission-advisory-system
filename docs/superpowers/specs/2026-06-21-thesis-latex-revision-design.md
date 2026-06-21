# Thesis LaTeX Revision Design

## Scope

Revise the thesis content under `latex/` without changing the mandated six-chapter skeleton, `main.tex` preamble, or template formatting.
The revision responds to supervisor feedback on concision, data preparation, contribution framing, prompt appendix, and a clearer system architecture diagram.

## Chapter 2 Architecture Diagram

Add one system-level diagram to Chapter 2 using PlantUML, consistent with the existing files in `latex/Figure/src`.
The diagram will summarize the runtime flow from student message to final response:

- chat interface and anonymous session;
- intent routing and profile update;
- advisory branch through the fixed pipeline: profile, retrieval, conflict, reasoning, policy, explanation;
- knowledge branch through embedding, pgvector similarity search, grounded answer generation, and citations;
- ingestion branch feeding canonical records and knowledge chunks;
- trace persistence for operator inspection.

The accompanying prose will explain how the system is designed, how answers are generated, and how semantic similarity is computed through embeddings and vector search.

## Chapter 3 Concision Rewrite

Rewrite Chapter 3 around the decision logic requested by the user: what the system needs, which approach satisfies that need, and why the selected approach was chosen over alternatives.

The chapter keeps the existing sections but makes each shorter:

- LLMs and structured output: explain hosted Gemini through the inference gateway, structured JSON, and fallback behavior.
- RAG and vector search: explain grounded answers, embeddings, cosine similarity in pgvector, and the choice of PostgreSQL-integrated vector storage over a dedicated vector database.
- Agentic pipelines: compare fixed LangGraph graph with an open-ended function-calling loop and justify determinism and traceability.
- Document processing and OCR: reduce OCR internals; compare multimodal hosted LLM OCR with a separate OCR engine using cost, implementation effort, Vietnamese admission-document fit, and gateway reuse.
- Web stack: keep only the parts needed to justify non-blocking chat and typed service boundaries.

No new unverified metrics will be introduced.

## Chapter 4 Data Preparation

Add a new `Data preparation` subsection under `Application building`, before `Libraries and tools`.
This subsection will show what data was collected and how it became usable:

- canonical admission/cutoff data from `ingestion/registry/seeds/initial_sources.json` and cutoff seeds;
- knowledge-corpus sources from `ingestion/knowledge/registry/seeds/knowledge_sources.json`, `ingestion/knowledge/seeds/national_sources.json`, `ingestion/knowledge/crawler/seeds/crawler_targets.json`, and `data/knowledge/manifest.json`;
- local PDF organization into `data/knowledge/pdf_text` and `data/knowledge/pdf_scanned`;
- processing steps: discovery, manifest filtering, text-layer extraction or OCR, chunking, embedding, and database insertion;
- measured corpus counts already recorded in `latex/FACTS.md`.

The `Achievement` subsection will remain the place for final numeric totals, avoiding duplicated evaluation claims.

## Chapter 5 Contribution Framing

Add a short opening section that summarizes the problems solved before the detailed contributions:

- contradictory official admission data;
- external LLM failures and malformed structured outputs;
- heterogeneous source formats, including scanned PDFs.

The existing contribution sections will remain, but their first paragraphs may be tightened so each section clearly follows problem, solution, and result without repeating Chapter 4 implementation details.

## Appendix Prompt Templates

Extend Appendix A or add a new appendix section for prompt templates.
Use academic, reproducible templates rather than full production prompts.
Each template will include role, task, required input placeholders, output format, and safety constraints.

Include templates for:

- intent routing;
- profile state update;
- knowledge question answering;
- OCR transcription;
- hybrid synthesis or policy ambiguity, depending on which reads most useful and compact in the final appendix.

Prompt templates will use placeholders such as `{{message}}`, `{{profile_state}}`, `{{retrieved_chunks}}`, and `{{image_page}}`.

## Files To Update

- `latex/Chapter/2_Survey.tex`
- `latex/Chapter/3_Methodology.tex`
- `latex/Chapter/4_Experiment_evaluation.tex`
- `latex/Chapter/5_Solution_contribution.tex`
- `latex/Chapter/Appendix_A.tex`
- `latex/OUTLINE.md`
- `latex/Figure/src/system_architecture_flow.puml`

If generated diagram PNGs can be produced locally with an existing tool, add `latex/Figure/system_architecture_flow.png`.
If not, add the PlantUML source and include an explicit external-rendering note rather than inventing a missing image file.

## Verification

Because the project notes that no local LaTeX toolchain is available, verification will be structural:

- check labels and figure references for the new diagram;
- scan `latex/Chapter/*.tex` for `TODO-VERIFY`;
- scan references, citations, and glossary usages;
- inspect changed files for unintended Vietnamese prose in chapter text except prompt templates and proper nouns;
- ensure `OUTLINE.md` matches the revised chapter contents.
