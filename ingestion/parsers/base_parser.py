import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Type

from ingestion.models.pipeline_models import ExtractedAdmissionFact

logger = logging.getLogger(__name__)


class BaseSpecializedParser(ABC):
    """
    Abstract base class for school-specific parsers.

    Subclasses should:
    1. Set `parser_profile` to match the profile string in source registry
    2. Implement `parse()` to extract admission facts from raw content
    """

    parser_profile: str = ""

    @abstractmethod
    def parse(
        self,
        content: bytes,
        source_url: str,
        school_id: str,
        school_name: str,
        source_metadata: Optional[dict] = None,
    ) -> List[ExtractedAdmissionFact]:
        """
        Parse raw content and return structured admission facts.

        Args:
            content: Raw bytes (HTML, etc.)
            source_url: URL the content was fetched from
            school_id: School identifier (e.g. "hust")
            school_name: Human-readable school name
            source_metadata: Extra metadata from source registry

        Returns:
            List of extracted admission facts
        """
        ...


class ParserRegistry:
    """
    Registry that maps parser_profile strings to parser instances.

    Usage:
        registry = ParserRegistry()
        registry.register(HustProgramParser())

        parser = registry.get("hust_programs")
        if parser:
            facts = parser.parse(content, url, ...)
    """

    _instance: Optional["ParserRegistry"] = None
    _parsers: Dict[str, BaseSpecializedParser]

    def __init__(self):
        self._parsers = {}

    @classmethod
    def get_instance(cls) -> "ParserRegistry":
        """Get or create the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._auto_discover()
        return cls._instance

    def register(self, parser: BaseSpecializedParser) -> None:
        """Register a specialized parser."""
        profile = parser.parser_profile
        if not profile:
            raise ValueError(
                f"Parser {parser.__class__.__name__} has no parser_profile set"
            )
        self._parsers[profile] = parser
        logger.debug(
            f"Registered parser '{profile}' → {parser.__class__.__name__}"
        )

    def get(self, parser_profile: str) -> Optional[BaseSpecializedParser]:
        """Get a parser by its profile name."""
        return self._parsers.get(parser_profile)

    def has(self, parser_profile: str) -> bool:
        """Check if a parser profile is registered."""
        return parser_profile in self._parsers

    def list_profiles(self) -> List[str]:
        """List all registered parser profile names."""
        return list(self._parsers.keys())

    def _auto_discover(self) -> None:
        """
        Auto-discover and register all built-in specialized parsers.
        New parsers just need to be imported here to be registered.
        """
        try:
            from ingestion.parsers.hust_program_parser import HustProgramParser
            self.register(HustProgramParser())
        except ImportError as e:
            logger.warning(f"Could not load HustProgramParser: {e}")

        try:
            from ingestion.parsers.vnu_uet_admission_parser import VnuUetAdmissionParser
            self.register(VnuUetAdmissionParser())
        except ImportError as e:
            logger.warning(f"Could not load VnuUetAdmissionParser: {e}")

        try:
            from ingestion.parsers.vnu_uet_proposal_pdf_parser import VnuUetProposalPdfParser
            self.register(VnuUetProposalPdfParser())
        except ImportError as e:
            logger.warning(f"Could not load VnuUetProposalPdfParser: {e}")

        try:
            from ingestion.parsers.hust_announcement_html_parser import HustAnnouncementHtmlParser
            self.register(HustAnnouncementHtmlParser())
        except ImportError as e:
            logger.warning(f"Could not load HustAnnouncementHtmlParser: {e}")
