"""National-scope sentinel for knowledge documents that apply to every school
(e.g. Bộ GD&ĐT admission regulations). Kept in a leaf module so both the
ingestion pipeline and the chat fan-out can import it without a cycle."""

# Stored in the `school` column as a sentinel "scope" tag (not a real school).
NATIONAL_SCHOOL = "MOET"

# document_type distinguishing national regulations from per-school PDFs.
NATIONAL_DOCUMENT_TYPE = "national_regulation"
