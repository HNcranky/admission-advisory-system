import json

import pytest

from ingestion.knowledge.neu_api import curriculum_text_from_json

SAMPLE = json.dumps({
    "data": [{
        "id": 1,
        "attributes": {
            "name": "Khoa học máy tính",
            "admissionCode": "7480101",
            "year": "K66 - 2024",
            "trainingObjectivesHtml": "<p><strong>Mục tiêu:</strong> đào tạo cử nhân.</p>",
            "careerOpportunitiesHtml": "<p>Lập trình viên, kỹ sư AI.</p>",
            "graduationConditionsHtml": "",          # empty → skipped
            "referenceProgramsHtml": "<p>RMIT, ASU reference programs</p>",  # noise → excluded
        },
    }],
    "meta": {},
}).encode("utf-8")


def test_extracts_name_and_section_prose():
    text, name = curriculum_text_from_json(SAMPLE)
    assert name == "Khoa học máy tính"
    # Populated sections become '## <heading>' blocks with tags stripped.
    assert "## Mục tiêu đào tạo" in text
    assert "đào tạo cử nhân." in text
    assert "## Cơ hội việc làm" in text
    assert "Lập trình viên, kỹ sư AI." in text
    assert "<p>" not in text and "<strong>" not in text


def test_empty_sections_are_skipped():
    text, _ = curriculum_text_from_json(SAMPLE)
    assert "Điều kiện tốt nghiệp" not in text  # graduationConditionsHtml was empty


def test_reference_programs_excluded():
    text, _ = curriculum_text_from_json(SAMPLE)
    assert "RMIT" not in text and "ASU" not in text


def test_no_data_raises():
    with pytest.raises(ValueError):
        curriculum_text_from_json(json.dumps({"data": []}).encode("utf-8"))
