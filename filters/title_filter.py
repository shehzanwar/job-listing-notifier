class TitleFilter:
    def __init__(self, roles_config: dict):
        self.tier_1 = [t.lower() for t in roles_config["tier_1"]]
        self.tier_2 = [t.lower() for t in roles_config["tier_2"]]
        self.tier_3 = [t.lower() for t in roles_config["tier_3"]]
        self.all_titles = self.tier_1 + self.tier_2 + self.tier_3

        self.exclude_seniority = [
            e.lower() for e in roles_config["exclude_titles"]["seniority"]
        ]
        self.exclude_unrelated = [
            e.lower() for e in roles_config["exclude_titles"]["unrelated_roles"]
        ]
        self.exceptions = [
            e.lower() for e in roles_config["exclude_exceptions"]
        ]

    def check(self, title: str):
        """Returns (passes, reason, tier)."""
        title_lower = title.lower()

        # Check exclusions first
        has_exception = any(exc in title_lower for exc in self.exceptions)

        if not has_exception:
            for exc in self.exclude_seniority:
                if exc in title_lower:
                    return False, f"Seniority exclusion: '{exc}'", 0
            for exc in self.exclude_unrelated:
                if exc in title_lower:
                    return False, f"Unrelated role: '{exc}'", 0

        # Check tier matches
        for t in self.tier_1:
            if t in title_lower:
                return True, f"Tier 1 match: '{t}'", 1
        for t in self.tier_2:
            if t in title_lower:
                return True, f"Tier 2 match: '{t}'", 2
        for t in self.tier_3:
            if t in title_lower:
                return True, f"Tier 3 match: '{t}'", 3

        return False, "No title keyword match", 0
