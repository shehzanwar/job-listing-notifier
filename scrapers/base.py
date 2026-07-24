from abc import ABC, abstractmethod


class BaseScraper(ABC):
    """Interface every ATS-specific scraper implements."""

    @abstractmethod
    def scrape_company(self, company: dict, search_queries: list) -> list:
        """Return a list of JobListing objects for the given company."""
        raise NotImplementedError
