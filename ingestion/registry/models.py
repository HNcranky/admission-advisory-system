                    

from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class SourceType(str, Enum):
    """Type of admission data source."""
    ADMISSION_HOMEPAGE = "admission_homepage"
    NEWS_LISTING = "news_listing"
    PROPOSAL_PDF = "proposal_pdf"
    DOCX_NOTICE = "docx_notice"
    FACEBOOK_PAGE = "facebook_page"
    PROGRAM_PAGE = "program_page"
    PROGRAM_LISTING = "program_listing"


class FetchStrategy(str, Enum):
    """How to fetch content from this source."""
    HTTP = "http"
    BROWSER = "browser"
    API = "api"


class SourceEntry(BaseModel):
    """
    Represents a registered source of admission data.
    Each source is a specific URL or endpoint that we know
    contains admission information for a school.
    """
    source_id: str = Field(
        description="Unique identifier, e.g. 'hust_admission_homepage'"
    )
    school_id: str = Field(
        description="School identifier, e.g. 'hust'"
    )
    school_name: str = Field(
        description="Human-readable school name"
    )
    source_type: SourceType
    root_url: str = Field(
        description="Root URL of this source"
    )
    trust_level: int = Field(
        default=3,
        ge=1, le=5,
        description="1=lowest, 5=highest trust"
    )
    priority: int = Field(
        default=5,
        ge=1, le=10,
        description="Fetch priority, lower = higher priority"
    )
    fetch_strategy: FetchStrategy = FetchStrategy.HTTP
    parser_profile: str = Field(
        default="default",
        description="Which parser configuration to use"
    )
    update_frequency_hint: str = Field(
        default="weekly",
        description="How often this source typically updates"
    )
    is_official: bool = True
    active: bool = True
    last_fetched_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Extra config specific to this source"
    )

    model_config = ConfigDict(use_enum_values=True)
