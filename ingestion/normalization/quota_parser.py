import re
import logging
from typing import Optional

from ingestion.models.pipeline_models import QuotaInfo

logger = logging.getLogger(__name__)


def parse_quota(raw: Optional[str]) -> Optional[QuotaInfo]:
    if not raw:
        return None

    raw = raw.strip()

                                                                  
    if raw.isdigit():
        return QuotaInfo(value=int(raw), quota_type="exact")

                                                                
    exact_match = re.search(r"(\d+)\s*(?:chỉ tiêu)?", raw)
    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", raw)

    if range_match:
        return QuotaInfo(
            min_value=int(range_match.group(1)),
            max_value=int(range_match.group(2)),
            quota_type="range",
        )

    if exact_match:
        return QuotaInfo(
            value=int(exact_match.group(1)),
            quota_type="exact",
        )

                                                                 
    approx_match = re.search(r"khoảng\s+(\d+)", raw, re.IGNORECASE)
    if approx_match:
        return QuotaInfo(
            value=int(approx_match.group(1)),
            quota_type="approximate",
        )

                                                                  
    if any(kw in raw.lower() for kw in ["chưa", "không", "null", "n/a"]):
        return QuotaInfo(quota_type="unknown")

    logger.debug(f"Could not parse quota: '{raw}'")
    return QuotaInfo(quota_type="unknown")
