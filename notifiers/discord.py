import httpx
import time
import logging

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url: str, rate_limit_delay: float = 2.0):
        self.webhook_url = webhook_url
        self.delay = rate_limit_delay

    def send_job_alert(self, job, llm_result: dict):
        """Send a single job alert as a Discord embed."""
        verdict = llm_result.get("verdict", "FLAG")
        fit_score = llm_result.get("fit_score", 50)
        reason = llm_result.get("one_line_reason", "")
        red_flags = llm_result.get("red_flags", [])
        clearance = llm_result.get("clearance_needed", "unclear")
        clearance_sponsorable = llm_result.get("clearance_sponsorable", "unclear")

        if verdict == "PASS":
            color = 0x22C55E  # Green
            emoji = "🟢"
        else:
            color = 0xF59E0B  # Yellow/amber
            emoji = "🟡"

        # Clearance display
        clearance_text = clearance.replace("_", "/").upper()
        if clearance_sponsorable is True:
            clearance_text += " (sponsorable)"
        elif clearance_sponsorable is False:
            clearance_text += " (active required)"

        embed = {
            "title": f"{emoji} {job.title}",
            "description": f"**{job.company}**\n📍 {job.location}",
            "url": job.url,
            "color": color,
            "fields": [
                {"name": "Fit Score", "value": f"{fit_score}/100", "inline": True},
                {"name": "Clearance", "value": clearance_text, "inline": True},
                {"name": "Level", "value": llm_result.get("effective_level", "?").title(), "inline": True},
            ],
            "footer": {"text": f"Req: {job.req_id} | Posted: {job.posted_date}"},
        }

        if reason:
            embed["fields"].append(
                {"name": "💡 Assessment", "value": reason, "inline": False}
            )

        if red_flags:
            flags_text = "\n".join(f"⚠️ {f}" for f in red_flags[:5])
            embed["fields"].append(
                {"name": "Flags", "value": flags_text, "inline": False}
            )

        payload = {"embeds": [embed]}

        response = httpx.post(self.webhook_url, json=payload)
        response.raise_for_status()
        time.sleep(self.delay)

    def send_batch_alert(self, jobs_with_results: list):
        """Send multiple jobs in one message (for high-volume days)."""
        lines = []
        for job, result in jobs_with_results:
            verdict = result.get("verdict", "FLAG")
            emoji = "🟢" if verdict == "PASS" else "🟡"
            score = result.get("fit_score", 50)
            lines.append(
                f"{emoji} **{job.title}** — {job.company} "
                f"({job.location}) | Fit: {score}/100 | "
                f"[Apply]({job.url})"
            )

        content = f"📋 **{len(jobs_with_results)} new listings found:**\n\n"
        content += "\n".join(lines)

        payload = {"content": content}
        response = httpx.post(self.webhook_url, json=payload)
        response.raise_for_status()

    def send_error_alert(self, message: str):
        """Send an error/failure notification."""
        payload = {
            "content": f"🔴 **Job Notifier Error**\n{message}"
        }
        httpx.post(self.webhook_url, json=payload)

    def send_weekly_digest(self, digest_text: str):
        """Send the weekly summary."""
        payload = {
            "content": f"📊 **Weekly Job Digest**\n\n{digest_text}"
        }
        httpx.post(self.webhook_url, json=payload)
