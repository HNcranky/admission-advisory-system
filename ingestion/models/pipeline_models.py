from enum import Enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
import hashlib


                                                                  

class DocumentType(str, Enum):
    """Type of document after routing."""
    HTML_ARTICLE = "html_article"
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    DOCX = "docx"
    IMAGE = "image"
    FACEBOOK_POST = "facebook_post"
    UNKNOWN = "unknown"


class DiscoveryStatus(str, Enum):
    """Processing status of a discovered resource."""
    NEW = "new"
    QUEUED = "queued"
    FETCHED = "fetched"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    FAILED = "failed"
    SKIPPED = "skipped"


                                                                 

class FetchResult(BaseModel):
    """Result from fetching a URL."""
    url: str
    final_url: str = Field(description="URL after redirects")
    raw_content: bytes
    content_type: str
    http_status: int
    headers: Dict[str, str] = {}
    fetched_at: datetime = Field(default_factory=datetime.now)
    content_hash: str = Field(default="")
    fetch_strategy_used: str = "http"
    fetch_duration_ms: int = 0

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def compute_hash(self) -> str:
        """Compute SHA256 hash of raw_content."""
        self.content_hash = hashlib.sha256(self.raw_content).hexdigest()
        return self.content_hash


                                                                 

class DiscoveredResource(BaseModel):
    """A resource discovered by the discovery layer."""
    url: str
    source_id: str = Field(description="Source that led to discovery")
    discovered_at: datetime = Field(default_factory=datetime.now)
    predicted_type: DocumentType = DocumentType.UNKNOWN
    priority_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Higher = more relevant"
    )
    status: DiscoveryStatus = DiscoveryStatus.NEW
    content_hash: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


                                                                 

class ParsedContent(BaseModel):
    """Output from a parser."""
    text: str = Field(description="Full extracted text")
    title: Optional[str] = None
    headings: List[str] = Field(
        default_factory=list,
        description="Extracted headings"
    )
    tables: List[List[List[str]]] = Field(
        default_factory=list,
        description="Extracted tables as list of rows of cells"
    )
    links: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Extracted links: [{url, text}]"
    )
    images: List[str] = Field(
        default_factory=list,
        description="Image URLs found"
    )
    document_type: DocumentType = DocumentType.UNKNOWN
    parser_used: str = ""
    parsed_at: datetime = Field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None


                                                                 

class SourceReference(BaseModel):
    """Reference back to the original source."""
    source_id: str
    source_url: str
    school_id: str
    fetched_at: Optional[datetime] = None
    trust_level: int = 3


class ExtractedAdmissionFact(BaseModel):
    """
    A single fact extracted from a document.
    Fields are kept as raw strings - normalization happens later.
    """
    school_name: str
    admission_year: int
    program_name: Optional[str] = None
    program_code: Optional[str] = None
    admission_method_raw: Optional[str] = None
    subject_combinations_raw: Optional[List[str]] = None
    quota_raw: Optional[str] = None
    deadline_raw: Optional[str] = None
    additional_conditions_raw: Optional[str] = None
    tuition_raw: Optional[str] = None
    source_reference: SourceReference
    confidence_score: float = Field(
        default=0.5, ge=0.0, le=1.0
    )
    extraction_method: str = "unknown"


                                                                 

class QuotaInfo(BaseModel):
    """Normalized quota information."""
    value: Optional[int] = None
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    quota_type: str = "exact"                                      


class DeadlineInfo(BaseModel):
    """Normalized deadline information."""
    start: Optional[str] = None            
    end: Optional[str] = None              
    deadline_type: str = "unknown"                          


class SubjectCombination(BaseModel):
    """A normalized subject combination."""
    code: str              
    subjects: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class NormalizedAdmissionRecord(BaseModel):
    """
    Final normalized admission record.
    This is what gets stored in canonical_admission_records.
    """
    school_id: str
    school_name_canonical: str
    admission_year: int
    program_id: Optional[str] = None
    program_name_canonical: Optional[str] = None
    program_name_raw: Optional[str] = None
    admission_method: Optional[str] = None
    admission_method_raw: Optional[str] = None
    subject_combinations: List[SubjectCombination] = Field(
        default_factory=list
    )
    quota: Optional[QuotaInfo] = None
    deadline: Optional[DeadlineInfo] = None
    metadata: Optional[Dict[str, Any]] = None
    tuition: Optional[Dict[str, Any]] = None
    source_url: Optional[str] = None
    source_trust_level: int = 3
    confidence_score: float = 0.5
    normalized_at: datetime = Field(default_factory=datetime.now)

                                 
    extracted_fact_id: Optional[int] = None
