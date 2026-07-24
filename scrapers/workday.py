import httpx
import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    url: str
    req_id: str
    posted_date: str
    description: str = ""
    department: str = ""
    raw_json: dict = None


class WorkdayScraper:
    def __init__(self, config: dict):
        self.config = config
        self.delay = config.get("request_delay", 1.5)
        self.client = httpx.Client(
            timeout=30,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Accept-Language": "en-US",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
            }
        )

    def fetch_jobs(self, company: dict, search_text: str = "",
                    offset: int = 0, limit: int = 20) -> dict:
        """Fetch job listings from Workday CXS API."""
        url = company["endpoint"]
        referer = company["career_url"]

        self.client.headers["Referer"] = referer

        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": search_text,
        }

        response = self.client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def fetch_job_detail(self, company: dict, external_path: str) -> dict:
        """Fetch full job description (second API call)."""
        url = f"{company['detail_endpoint']}/{external_path}"
        referer = company["career_url"]

        self.client.headers["Referer"] = referer

        response = self.client.get(url)
        response.raise_for_status()
        return response.json()

    def scrape_company(self, company: dict, search_queries: list) -> list:
        """Scrape all matching jobs for a company across search queries."""
        all_jobs = {}  # Dedup by req_id within this run

        for query in search_queries:
            offset = 0
            limit = 20

            while True:
                try:
                    data = self.fetch_jobs(company, search_text=query,
                                            offset=offset, limit=limit)
                except httpx.HTTPStatusError as e:
                    logger.error(f"HTTP {e.response.status_code} for "
                                 f"{company['name']} query='{query}' offset={offset}")
                    break
                except Exception as e:
                    logger.error(f"Error fetching {company['name']}: {e}")
                    break

                postings = data.get("jobPostings", [])
                total = data.get("total", 0)

                for posting in postings:
                    req_id = posting.get("externalPath", "").split("/")[-1]
                    if req_id and req_id not in all_jobs:
                        all_jobs[req_id] = JobListing(
                            title=posting.get("title", ""),
                            company=company["name"],
                            location=posting.get("locationsText", ""),
                            url=f"{company['career_url']}/job/{posting['externalPath']}",
                            req_id=req_id,
                            posted_date=posting.get("postedOn", ""),
                            raw_json=posting,
                        )

                offset += limit
                time.sleep(self.delay)

                if offset >= total or not postings:
                    break

        # Fetch full descriptions for all found jobs
        jobs = list(all_jobs.values())
        for job in jobs:
            try:
                detail = self.fetch_job_detail(company, job.req_id)
                job.description = detail.get("jobPostingInfo", {}).get(
                    "jobDescription", "")
                job.department = detail.get("jobPostingInfo", {}).get(
                    "department", "")
                time.sleep(self.delay)
            except Exception as e:
                logger.warning(f"Failed to fetch detail for {job.req_id}: {e}")

        logger.info(f"{company['name']}: found {len(jobs)} jobs "
                    f"across {len(search_queries)} queries")
        return jobs
