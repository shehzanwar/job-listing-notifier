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
- REJECT (not FLAG) if the day-to-day work is not fundamentally data analysis,
  data science, or AI/ML — even if the title contains "Analyst" or "Systems".
  Examples: IT operations/system administration/hardware-network
  troubleshooting, traditional business-systems support for COTS/ERP
  software, RF/radar/signal-processing engineering in MATLAB, or general
  business development/event coordination. If is_data_role would be false,
  the verdict should be REJECT, not FLAG, regardless of clearance or years.
- If the title says "entry level" or "junior" but the description contradicts this, trust the DESCRIPTION over the title
- "Preferred" requirements are softer than "required" — note them but don't auto-reject
- "Must be able to obtain clearance" is different from "must have active clearance" — the former is usually fine for new grads at defense contractors
- A "laundry list" of 8+ technical skills on an entry-level posting is a red flag but not an auto-reject

If you reason step by step before answering, keep it under ~150 words and
reach a decision — do not re-litigate the same point more than once. Then
output the JSON object on its own."""


class LLMJudge:
    def __init__(self, config: dict):
        self.host = config["server_host"]
        self.port = config["server_port"]
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 400)
        # Thinking-mode reasoning blocks routinely run 500-1000+ tokens on
        # their own before the model even starts the JSON answer — reusing
        # the fast-pass budget here truncates mid-reasoning and produces
        # unparseable output. Confirmed live: needs a much bigger budget.
        self.thinking_max_tokens = config.get("thinking_max_tokens", 2500)
        self.base_url = f"http://{self.host}:{self.port}"

    def _call_llm(self, prompt: str, thinking: bool = False) -> str:
        """Call llama.cpp server."""
        if thinking:
            # Qwen3.5 thinking mode: prepend <think> to assistant turn
            full_prompt = (
                f"<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n<think>\n"
            )
            n_predict = self.thinking_max_tokens
            # No "\n\n\n" stop here -- reasoning naturally contains blank
            # lines between steps and would get cut off mid-thought.
            stop = ["<|im_end|>"]
        else:
            # This build defaults to emitting a <think>...</think> reasoning
            # block even when one isn't requested. An empty prefilled think
            # block is the standard way to skip it for the fast pass —
            # confirmed live: ~95ms/clean output vs ~2.3s/full reasoning.
            full_prompt = (
                f"<|im_start|>user\n{prompt}<|im_end|>\n"
                f"<|im_start|>assistant\n<think>\n\n</think>\n\n"
            )
            n_predict = self.max_tokens
            stop = ["<|im_end|>", "\n\n\n"]

        response = httpx.post(
            f"{self.base_url}/completion",
            json={
                "prompt": full_prompt,
                "temperature": self.temperature,
                "n_predict": n_predict,
                "stop": stop,
                "stream": False,
            },
            timeout=180,
        )
        response.raise_for_status()
        return response.json()["content"]

    def _parse_response(self, text: str) -> dict:
        """Parse JSON from LLM response with fallbacks."""
        # Thinking-mode responses lead with a <think>...</think> reasoning
        # block; strip it so the fallback regexes below can't accidentally
        # match JSON-like text mentioned inside the reasoning itself.
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

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

        return None

    def judge(self, job) -> dict:
        """Run LLM judgment on a single job listing."""
        prompt = FILTER_PROMPT.format(
            title=job.title,
            company=job.company,
            location=job.location,
            department=getattr(job, 'department', ''),
            description=job.description[:3000],  # Cap description length
        )

        raw_response = self._call_llm(prompt, thinking=False)
        result = self._parse_response(raw_response)

        # Only escalate to the slower/costlier thinking pass when the fast
        # pass genuinely couldn't decide (verdict FLAG). A fast-pass REJECT
        # or PASS that merely scored in the borderline band already came
        # with reasoning -- re-litigating it via thinking mode was mostly
        # wasted cost and, worse, an unreliable one: on ambiguous listings
        # thinking mode would sometimes loop through the same point
        # repeatedly and blow through the token budget without ever
        # emitting JSON (confirmed live: ~29% of thinking-mode calls failed
        # to parse before this fix).
        if result is not None and result.get("verdict") != "FLAG":
            return result

        fast_pass_result = result  # may be None if even the fast pass failed to parse

        logger.info(f"Fast pass {'unparseable' if result is None else 'FLAG'} "
                    f"for {job.title} — re-running with thinking mode")
        raw_response = self._call_llm(prompt, thinking=True)
        thinking_result = self._parse_response(raw_response)

        if thinking_result is not None:
            return thinking_result

        if fast_pass_result is not None:
            logger.warning(f"Thinking pass unparseable for {job.title} — "
                           f"keeping fast-pass FLAG result instead of a blind placeholder")
            return fast_pass_result

        logger.warning(f"Both fast and thinking passes unparseable for {job.title}")
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
