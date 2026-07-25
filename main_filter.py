import os
import yaml
import time
import logging
import subprocess
from pathlib import Path
from filters.title_filter import TitleFilter
from filters.regex_extractor import RegexExtractor
from filters.llm_judge import LLMJudge
from notifiers.discord import DiscordNotifier
from storage.database import JobDatabase
from storage.models import JobListing

logging.basicConfig(level=logging.INFO,
                     format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("filter")


def load_config():
    config_dir = Path("config")
    with open(config_dir / "roles.yaml") as f:
        roles = yaml.safe_load(f)
    with open(config_dir / "filters.yaml") as f:
        filters = yaml.safe_load(f)
    with open(config_dir / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    return roles, filters, settings


def start_llama_server(settings):
    """Start llama.cpp server as a subprocess."""
    llm_cfg = settings["llm"]
    cmd = [
        llm_cfg.get("llama_server_path", "llama-server"),
        "-m", llm_cfg["model_path"],
        "--host", llm_cfg["server_host"],
        "--port", str(llm_cfg["server_port"]),
        "-ngl", str(llm_cfg["gpu_layers"]),
        "-c", str(llm_cfg["context_size"]),
        "--flash-attn", "on" if llm_cfg.get("flash_attn", True) else "off",
        "-t", str(llm_cfg["threads"]),
        "--temp", str(llm_cfg["temperature"]),
        "--top-p", str(llm_cfg["top_p"]),
    ]

    logger.info("Starting llama.cpp server...")
    # llama-server logs verbosely per request. subprocess.PIPE has a small
    # OS buffer (~64KB on Windows) -- if nothing reads it, the buffer fills
    # after a few dozen requests and the child process blocks on its next
    # write() call, silently freezing generation (confirmed live: GPU usage
    # dropped to ~7% and every request after that timed out identically).
    # Redirect to a file instead so the child is never blocked on output.
    Path("logs").mkdir(exist_ok=True)
    log_file = open("logs/llm_server.log", "a")
    process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

    # Wait for server to be ready
    import httpx
    for _ in range(llm_cfg.get("startup_wait", 15)):
        time.sleep(1)
        try:
            r = httpx.get(f"http://{llm_cfg['server_host']}:{llm_cfg['server_port']}/health")
            if r.status_code == 200:
                logger.info("llama.cpp server ready")
                return process
        except Exception:
            pass

    logger.warning("Server may not be fully ready, proceeding anyway")
    return process


def get_webhook_url(settings_cfg: dict) -> str:
    """Prefer the DISCORD_WEBHOOK_URL env var over the value in settings.yaml."""
    url = os.environ.get("DISCORD_WEBHOOK_URL") or settings_cfg["discord"]["webhook_url"]
    if not url:
        raise RuntimeError(
            "No Discord webhook configured. Set the DISCORD_WEBHOOK_URL "
            "environment variable or config/settings.yaml -> discord.webhook_url"
        )
    return url


def main():
    roles_cfg, filters_cfg, settings_cfg = load_config()
    db = JobDatabase(settings_cfg["database"]["path"])

    title_filter = TitleFilter(roles_cfg)
    regex_extractor = RegexExtractor()
    discord = DiscordNotifier(
        get_webhook_url(settings_cfg),
        settings_cfg["discord"]["rate_limit_delay"]
    )

    # Start LLM server
    server_process = start_llama_server(settings_cfg)
    llm_judge = LLMJudge(settings_cfg["llm"])

    try:
        unfiltered = db.get_unfiltered_listings()
        logger.info(f"Processing {len(unfiltered)} unfiltered listings")

        pass_jobs = []
        flag_jobs = []
        reject_count = 0

        for listing in unfiltered:
            # ── Layer 1: Title filter ──
            passes, reason, tier = title_filter.check(listing["title"])
            if not passes:
                db.mark_filtered(listing["id"], {
                    "req_id": listing["req_id"],
                    "company": listing["company"],
                    "title": listing["title"],
                    "location": listing["location"],
                    "url": listing["url"],
                    "verdict": "REJECT",
                    "fit_score": 0,
                    "one_line_reason": f"Title filter: {reason}",
                })
                reject_count += 1
                continue

            # ── Layer 2: Regex extraction ──
            reqs = regex_extractor.extract(listing.get("description", "") or "")
            should_reject, reject_reason = regex_extractor.hard_reject(
                reqs, filters_cfg)

            if should_reject:
                db.mark_filtered(listing["id"], {
                    "req_id": listing["req_id"],
                    "company": listing["company"],
                    "title": listing["title"],
                    "location": listing["location"],
                    "url": listing["url"],
                    "verdict": "REJECT",
                    "fit_score": 0,
                    "one_line_reason": f"Regex filter: {reject_reason}",
                })
                reject_count += 1
                continue

            # ── Layer 3: LLM judgment ──
            start = time.time()

            job = JobListing(
                title=listing["title"],
                company=listing["company"],
                location=listing["location"],
                url=listing["url"],
                req_id=listing["req_id"],
                posted_date=listing.get("posted_date", ""),
                description=listing.get("description", "") or "",
                department=listing.get("department", "") or "",
            )

            result = llm_judge.judge(job)
            inference_time = time.time() - start

            result["req_id"] = listing["req_id"]
            result["company"] = listing["company"]
            result["title"] = listing["title"]
            result["location"] = listing["location"]
            result["url"] = listing["url"]

            db.mark_filtered(listing["id"], result)

            verdict = result.get("verdict", "FLAG")
            if verdict == "PASS":
                pass_jobs.append((job, result))
            elif verdict == "FLAG":
                flag_jobs.append((job, result))
            else:
                reject_count += 1

            logger.info(f"  {listing['title']} @ {listing['company']}: "
                        f"{verdict} (score={result.get('fit_score')}, "
                        f"{inference_time:.1f}s)")

        # ── Send Discord notifications ──
        all_notify = pass_jobs + flag_jobs

        if len(all_notify) > settings_cfg["discord"]["batch_threshold"]:
            discord.send_batch_alert(all_notify)
        else:
            for job, result in all_notify:
                discord.send_job_alert(job, result)

        logger.info(f"Filter complete: {len(pass_jobs)} PASS, "
                    f"{len(flag_jobs)} FLAG, {reject_count} REJECT")

    finally:
        # Shut down LLM server
        logger.info("Shutting down llama.cpp server...")
        server_process.terminate()
        server_process.wait(timeout=10)
        logger.info("Server stopped. VRAM released.")


if __name__ == "__main__":
    main()
