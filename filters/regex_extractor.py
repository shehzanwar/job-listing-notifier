import re
from dataclasses import dataclass, field


@dataclass
class ExtractedRequirements:
    min_years: int = 0
    max_years: int = 0
    years_is_preferred: bool = False
    clearance_level: str = "none"
    clearance_active_required: bool = False
    clearance_sponsorable: bool = False
    phd_required: bool = False
    us_citizen_required: bool = False
    travel_pct: int = 0
    is_contract: bool = False
    red_flags: list = field(default_factory=list)


class RegexExtractor:

    YOE_PATTERNS = [
        r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)',
        r'(?:minimum|min\.?|at least)\s+(\d+)\s*(?:years?|yrs?)',
        r'(\d+)\s*[-–]\s*(\d+)\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)',
        r'(\d+)\+\s*(?:years?|yrs?)\s*(?:of\s+)?(?:relevant|related|professional)',
    ]

    CLEARANCE_PATTERNS = {
        "ts_sci": r'(?:TS/SCI|Top\s+Secret.*?SCI|TS\s*/\s*SCI)',
        "top_secret": r'(?:Top\s+Secret|TS)\b(?!\s*/\s*SCI)',
        "secret": r'\bSecret\b(?!\s+clearance\s+not)',
        "public_trust": r'(?:Public\s+Trust|MBI|Moderate\s+Background)',
    }

    def extract(self, description: str) -> ExtractedRequirements:
        req = ExtractedRequirements()
        desc_lower = description.lower()

        # Years of experience
        for pattern in self.YOE_PATTERNS:
            matches = re.findall(pattern, description, re.IGNORECASE)
            if matches:
                numbers = []
                for m in matches:
                    if isinstance(m, tuple):
                        numbers.extend([int(x) for x in m if x])
                    else:
                        numbers.append(int(m))
                req.min_years = min(numbers)
                req.max_years = max(numbers)

                # Check if "preferred" vs "required"
                idx = description.lower().find(str(req.min_years))
                context = description[max(0, idx - 100):idx + 100]
                if re.search(r'prefer|desired|nice to have|ideal',
                             context, re.IGNORECASE):
                    req.years_is_preferred = True
                break

        # Clearance
        for level, pattern in self.CLEARANCE_PATTERNS.items():
            if re.search(pattern, description, re.IGNORECASE):
                req.clearance_level = level
                break

        if re.search(r'active\s+(?:TS|Top\s+Secret|Secret|clearance)',
                     description, re.IGNORECASE):
            req.clearance_active_required = True
        if re.search(r'(?:willing|able|must be able)\s+to\s+(?:obtain|get|acquire)',
                     description, re.IGNORECASE):
            req.clearance_sponsorable = True
        if re.search(r'sponsor', desc_lower):
            req.clearance_sponsorable = True

        # Education
        if re.search(r'Ph\.?D\.?\s*(?:required|is required|must have)',
                     description, re.IGNORECASE):
            req.phd_required = True

        # Citizenship
        if re.search(r'(?:US|U\.S\.)\s*(?:Citizen|citizenship)\s*(?:required|is required)',
                     description, re.IGNORECASE):
            req.us_citizen_required = True

        # Travel
        travel_match = re.search(r'(\d+)%\s*travel', desc_lower)
        if travel_match:
            req.travel_pct = int(travel_match.group(1))

        # Contract
        if re.search(r'1099|w2\s+contract|contingent\s+upon', desc_lower):
            req.is_contract = True

        return req

    def hard_reject(self, req: ExtractedRequirements, filters_config: dict):
        """Returns (should_reject, reason)."""
        max_years = filters_config["experience"]["max_years_required"]

        if req.min_years >= max_years + 1 and not req.years_is_preferred:
            return True, f"Requires {req.min_years}+ years experience"

        if req.phd_required:
            return True, "PhD required"

        clearance_rules = filters_config["clearance"]["rules"]
        level = req.clearance_level
        if level in clearance_rules:
            if req.clearance_active_required:
                rule = clearance_rules[level].get("active_required", {})
                if rule.get("action") == "REJECT":
                    return True, f"Active {level} clearance required"

        return False, ""
