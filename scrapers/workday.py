import httpx
import time
import logging
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def strip_html(html_text: str) -> str:
    """Workday's jobDescription field is raw HTML — plain text is what the LLM needs."""
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(separator="\n", strip=True)


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
    external_path: str = field(default="", repr=False)  # internal use only, not persisted


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
        """Fetch full job description (second API call).

        `external_path` comes straight from the listing response's
        `externalPath` field and already starts with "/job/..." — do not
        prepend another "/job" segment or you'll get a 404.
        `detail_endpoint` must therefore be the bare
        ".../wday/cxs/{tenant}/{site}" base, with no trailing "/job".
        """
        url = f"{company['detail_endpoint']}{external_path}"
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
                    external_path = posting.get("externalPath", "")
                    # bulletFields[0] is the clean req ID (e.g. "R0241239") and
                    # matches jobReqId in the detail response. externalPath's
                    # trailing segment is a title slug + req ID, not reliable
                    # to parse on its own.
                    bullet_fields = posting.get("bulletFields") or []
                    req_id = bullet_fields[0] if bullet_fields else external_path.split("/")[-1]

                    if req_id and req_id not in all_jobs:
                        all_jobs[req_id] = JobListing(
                            title=posting.get("title", ""),
                            company=company["name"],
                            location=posting.get("locationsText", ""),
                            url=f"{company['career_url']}{external_path}",
                            req_id=req_id,
                            posted_date=posting.get("postedOn", ""),
                            raw_json=posting,
                            external_path=external_path,
                        )

                offset += limit
                time.sleep(self.delay)

                if offset >= total or not postings:
                    break

        # Fetch full descriptions for all found jobs
        jobs = list(all_jobs.values())
        for job in jobs:
            try:
                detail = self.fetch_job_detail(company, job.external_path)
                info = detail.get("jobPostingInfo", {})
                job.description = strip_html(info.get("jobDescription", ""))
                # startDate is absolute ("2026-07-23"); postedOn from the
                # listing response is relative ("Posted 2 Days Ago") and
                # useless for date-based filtering.
                job.posted_date = info.get("startDate") or job.posted_date
                # externalUrl is the canonical apply link; falls back to the
                # URL built from the listing if the detail call is missing it.
                job.url = info.get("externalUrl") or job.url
                # Workday's detail payload has no "department" field.
                time.sleep(self.delay)
            except Exception as e:
                logger.warning(f"Failed to fetch detail for {job.req_id}: {e}")

        logger.info(f"{company['name']}: found {len(jobs)} jobs "
                    f"across {len(search_queries)} queries")
        return jobs
