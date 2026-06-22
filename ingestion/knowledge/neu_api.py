"""Parse NEU (courses.neu.edu.vn) Strapi program-curriculum API JSON into
program-overview prose.

NEU publishes undergraduate programs through a Next.js SPA whose prose lives only
inside RSC <script> data — invisible to the HTML parser. The same host exposes an
open, unauthenticated Strapi REST API whose per-program record carries the
overview prose as HTML fields. A seed's source_url points at the single-program
query, e.g.
    https://courses.neu.edu.vn/api/curriculum-curricula?filters[slug][$eq]=<slug>&populate=*
and this module turns that JSON response into '## <section>' markdown so the
by_section chunker splits one chunk per section, each tagged with the program.

Pick slugs whose record already has populated prose (the ORIGINAL/source
curriculum). INHERITED records leave the *Html fields empty and point at a
sourceCurriculumId — seed the source slug directly so no runtime pointer-follow
is needed.
"""

import json

from bs4 import BeautifulSoup

# Prose fields in reading order → (json key, Vietnamese section heading). These
# are the student-facing overview sections. `referenceProgramsHtml` is omitted
# on purpose: it lists OTHER universities' programs (RMIT/ASU/…), i.e. noise.
PROSE_FIELDS = (
    ("trainingObjectivesHtml", "Mục tiêu đào tạo"),
    ("programOutcomesHtml", "Chuẩn đầu ra"),
    ("careerOpportunitiesHtml", "Cơ hội việc làm"),
    ("trainingProcessHtml", "Tiến trình đào tạo"),
    ("graduationConditionsHtml", "Điều kiện tốt nghiệp"),
    ("subjectDescriptionsHtml", "Mô tả học phần"),
    ("teachingAndAssessmentHtml", "Giảng dạy và đánh giá"),
    ("teachingStaffStandardsHtml", "Đội ngũ giảng viên"),
    ("facilitiesTechnologyLearningResourcesHtml", "Cơ sở vật chất"),
    ("implementationGuidanceHtml", "Hướng dẫn thực hiện"),
)


def _strip_html(html) -> str:
    if not html:
        return ""
    return BeautifulSoup(str(html), "html.parser").get_text(" ", strip=True)


def curriculum_text_from_json(raw: bytes) -> tuple[str, str | None]:
    """(overview_text, program_name) from a single-program Strapi API response.

    The prose fields become '## <heading>\\n<text>' blocks so by_section chunking
    emits one chunk per populated section. Raises ValueError if the payload has
    no program record (so the pipeline surfaces a bad seed rather than ingesting
    an empty document).
    """
    payload = json.loads(raw)
    data = payload.get("data")
    if not data:
        raise ValueError("NEU curriculum API returned no data")
    record = data[0] if isinstance(data, list) else data
    attrs = record.get("attributes", record)

    name = attrs.get("name") or None
    blocks: list[str] = []
    for key, heading in PROSE_FIELDS:
        text = _strip_html(attrs.get(key))
        if text:
            blocks.append(f"## {heading}\n{text}")
    return "\n\n".join(blocks), name
