import logging
from ingestion.registry.models import SourceEntry, FetchStrategy
from ingestion.models.pipeline_models import FetchResult, DiscoveredResource
from ingestion.fetchers.http_fetcher import http_fetch

logger = logging.getLogger(__name__)


def dispatch_fetch(
    url: str,
    source: SourceEntry,
) -> FetchResult:
    """
    Choose and execute the appropriate fetcher based on source config.

    Args:
        url: URL to fetch
        source: Source configuration

    Returns:
        FetchResult from the chosen fetcher
    """
    strategy = source.fetch_strategy

    if strategy == FetchStrategy.BROWSER:
                                        
                                               
        logger.info(f"Browser fetch for {url} (falling back to HTTP)")
        return http_fetch(url)

    elif strategy == FetchStrategy.API:
                         
                                           
        logger.info(f"API fetch for {url} (falling back to HTTP)")
        return http_fetch(url)

    else:
                            
        return http_fetch(url)
