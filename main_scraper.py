import yaml
import time
import logging
from pathlib import Path
from scrapers.workday import WorkdayScraper
from storage.database import JobDatabase

logging.basicConfig(level=logging.INFO,
                     format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("scraper")


def load_config():
    config_dir = Path("config")
    with open(config_dir / "companies.yaml") as f:
        companies = yaml.safe_load(f)
    with open(config_dir / "roles.yaml") as f:
        roles = yaml.safe_load(f)
    with open(config_dir / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    return companies, roles, settings


def main():
    companies_cfg, roles_cfg, settings_cfg = load_config()
    db = JobDatabase(settings_cfg["database"]["path"])
    scraper = WorkdayScraper(settings_cfg["scraper"])
    search_queries = roles_cfg["workday_search_queries"]

    total_new = 0
    total_seen = 0

    for company in companies_cfg["companies"]:
        if company["ats"] != "workday":
            continue  # Phase 1: Workday only

        start = time.time()
        try:
            jobs = scraper.scrape_company(company, search_queries)
            new_count = 0
            for job in jobs:
                if db.insert_raw_listing(job):
                    new_count += 1
                else:
                    total_seen += 1

            total_new += new_count
            duration = time.time() - start
            db.log_scraper_run(company["name"], "all", len(jobs),
                                "SUCCESS", duration=duration)
            logger.info(f"{company['name']}: {new_count} new, "
                        f"{len(jobs) - new_count} already seen")

        except Exception as e:
            duration = time.time() - start
            db.log_scraper_run(company["name"], "all", 0,
                                "ERROR", str(e), duration)
            logger.error(f"{company['name']}: FAILED — {e}")

    logger.info(f"Scrape complete: {total_new} new listings, "
                f"{total_seen} duplicates skipped")


if __name__ == "__main__":
    main()
