import time
import logging
import httpx
import yaml
from pathlib import Path
from storage.database import JobDatabase
from notifiers.discord import DiscordNotifier
from main_filter import start_llama_server, get_webhook_url

logging.basicConfig(level=logging.INFO,
                     format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger("digest")

DIGEST_PROMPT = """Summarize this week's job listings for an early-career data
professional (MS Analytics, Python/SQL/Bayesian modeling/Monte Carlo focus,
looking for entry/junior data analyst, data scientist, or AI-integration roles
at defense/federal contractors).

LISTINGS (verdict, fit score, title, company, location, reason):
{listings}

Write a short ranked Discord message (plain text, no markdown headers) that:
- Leads with the top 3-5 highest-fit listings and why they stand out
- Groups the rest briefly by company
- Flags anything with clearance or experience concerns worth double-checking
Keep it under 300 words."""


def load_config():
    config_dir = Path("config")
    with open(config_dir / "settings.yaml") as f:
        return yaml.safe_load(f)


def build_digest_text(llm_cfg: dict, listings: list) -> str:
    lines = []
    for row in listings:
        lines.append(
            f"[{row['verdict']}] {row['fit_score']}/100 — {row['title']} @ "
            f"{row['company']} ({row['location']}): {row['one_line_reason']}"
        )
    prompt = DIGEST_PROMPT.format(listings="\n".join(lines))

    full_prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
    response = httpx.post(
        f"http://{llm_cfg['server_host']}:{llm_cfg['server_port']}/completion",
        json={
            "prompt": full_prompt,
            "temperature": llm_cfg.get("temperature", 0.1),
            "n_predict": 600,
            "stop": ["<|im_end|>"],
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["content"].strip()


def main():
    settings_cfg = load_config()
    db = JobDatabase(settings_cfg["database"]["path"])
    discord = DiscordNotifier(
        get_webhook_url(settings_cfg),
        settings_cfg["discord"]["rate_limit_delay"]
    )

    listings = db.get_weekly_pass_flag(days=7)
    if not listings:
        logger.info("No PASS/FLAG listings in the past 7 days — skipping digest")
        return

    server_process = start_llama_server(settings_cfg)
    try:
        digest_text = build_digest_text(settings_cfg["llm"], listings)
        discord.send_weekly_digest(digest_text)
        logger.info(f"Digest sent covering {len(listings)} listings")
    finally:
        server_process.terminate()
        server_process.wait(timeout=10)


if __name__ == "__main__":
    main()
