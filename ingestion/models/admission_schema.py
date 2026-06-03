from pydantic import BaseModel
from typing import List, Optional

class AdmissionMethod(BaseModel):
    method_name: str
    quota: Optional[int]
    subject_combinations: Optional[List[str]]
    conditions: Optional[str]

class ProgramAdmission(BaseModel):
    university: str
    program_name: str
    admission_methods: List[AdmissionMethod]

class AdmissionDocument(BaseModel):
    source_url: str
    university: str
    year: int
    programs: List[ProgramAdmission]