import httpx
import json
import re
import logging

logger = logging.getLogger(__name__)

FILTER_PROMPT = """You are a job listing filter for an early-career data professional.

CANDIDATE PROFILE:
- MS in Analytics (Georgia Tech)
- Skills: Python, SQL, pandas, Bayesian modeling, Monte Carlo simulation,
  ETL pipelines, data visualization, LLM integration, GitHub Actions CI/CD
- Positioning: designs, validates, and ships AI-enabled data systems
- NOT a traditional software engineer
- Looking for: entry-level / junior / associate roles (0-3 years experience)
- Open to: data analyst, data scientist, analytics, operations research,
  AI integration, BI analyst, systems analyst roles
- NOT looking for: senior/principal/staff roles, pure software engineering,
  management, roles requiring 5+ years experience

JOB LISTING:
Title: {title}
Company: {company}
Location: {location}
Department: {department}
Description:
{description}

Respond with ONLY a JSON object in this exact format (no markdown, no explanation):
{{"verdict": "PASS" | "FLAG" | "REJECT", "effective_level": "entry" | "junior" | "mid" | "senior" | "lead" | "unclear", "years_required": <number or -1 if unclear>, "is_data_role": true | false, "clearance_needed": "none" | "public_trust" | "secret" | "top_secret" | "ts_sci" | "unclear", "clearance_sponsorable": true | false | "unclear", "red_flags": ["list of concerns, empty if none"], "fit_score": <0-100>, "one_line_reason": "<brief explanation>"}}

RULES:
- PASS: genuinely entry/junior level, data/analytics focused, no hard blockers
- FLAG: mostly fits but has concerns (e.g., "3-5 years preferred", unclear seniority, adjacent role, clearance uncertainty)
- REJECT: clearly senior, pure SWE, requires 5+ years, PhD required, or completely unrelated field
- If the title says "entry level" or "junior" but the description contradicts this, trust the DESCRIPTION over the title
- "Preferred" requirements are softer than "required" — note them but don't auto-reject
- "Must be able to obtain clearance" is different from "must have active clearance" — the former is usually fine for new grads at defense contractors
- A "laundry list" of 8+ technical skills on an entry-level posting is a red flag but not an auto-reject"""


class LLMJudge:
    def __init__(self, config: dict):
        self.host = config["server_host"]
        self.port = config["server_port"]
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 400)
        self.thinking_threshold = config.get("thinking_mode_threshold", 65)
        self.base_url = f"http://{self.host}:{self.port}"

    def _call_llm(self, prompt: str, thinking: bool = False) -> str:
        """Call llama.cpp server."""
        if thinking:
            # Qwen3.5 thinking mode: prepend <think> to assistant turn
            full_prompt = (
                f"<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n<think>\n"
            )
        else:
            full_prompt = (
                f"<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )

        response = httpx.post(
            f"{self.base_url}/completion",
            json={
                "prompt": full_prompt,
                "temperature": self.temperature,
                "n_predict": self.max_tokens,
                "stop": ["<|im_end|>", "\n\n\n"],
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["content"]

    def _parse_response(self, text: str) -> dict:
        """Parse JSON from LLM response with fallbacks."""
        # Direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Extract from markdown code block
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Find any JSON object
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Fallback
        return {
            "verdict": "FLAG",
            "effective_level": "unclear",
            "years_required": -1,
            "is_data_role": True,
            "clearance_needed": "unclear",
            "clearance_sponsorable": "unclear",
            "red_flags": ["LLM response parse error — manual review needed"],
            "fit_score": 50,
            "one_line_reason": "Could not parse LLM output",
        }

    def judge(self, job, thinking: bool = False) -> dict:
        """Run LLM judgment on a single job listing."""
        prompt = FILTER_PROMPT.format(
            title=job.title,
            company=job.company,
            location=job.location,
            department=getattr(job, 'department', ''),
            description=job.description[:3000],  # Cap description length
        )

        raw_response = self._call_llm(prompt, thinking=thinking)
        result = self._parse_response(raw_response)

        # Two-pass: if borderline, re-run with thinking mode
        if (not thinking and
                (result.get("verdict") == "FLAG" or
                 50 <= result.get("fit_score", 50) <= self.thinking_threshold)):
            logger.info(f"Borderline score ({result.get('fit_score')}) "
                       f"for {job.title} — re-running with thinking mode")
            raw_response = self._call_llm(prompt, thinking=True)
            result = self._parse_response(raw_response)

        return result
