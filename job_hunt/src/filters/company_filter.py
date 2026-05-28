"""Company filter — hard rejects enterprises + staffing, soft warns low growth."""


class CompanyFilter:
    def __init__(self, config: dict):
        cfg = config.get("company_filter", {})
        self._reject_stages: list[str] = cfg.get("reject_stages", ["enterprise"])
        self._min_growth: int = cfg.get("min_growth_score", 4)
        self._reject_kws: list[str] = [
            k.lower() for k in cfg.get("reject_keywords_in_company_name", [])
        ]

    def evaluate(self, company_name: str, intel: dict) -> dict:
        """Return {verdict, reason, warn}.

        verdict: 'PASS' | 'REJECT'
        reason: human-readable string
        warn: optional low-growth warning string or None
        """
        name_lower = (company_name or "").lower()

        # Hard reject: keyword in company name
        for kw in self._reject_kws:
            if kw in name_lower:
                return {
                    "verdict": "REJECT",
                    "reason": f"company name contains '{kw}'",
                    "warn": None,
                }

        stage = (intel.get("stage") or "unknown").lower()
        growth = int(intel.get("growth_score", 5))

        # Hard reject: enterprise stage
        if stage in self._reject_stages:
            return {
                "verdict": "REJECT",
                "reason": f"enterprise (stage={stage})",
                "warn": None,
            }

        # Soft warn: low growth score (don't hide — user decides)
        warn = None
        if growth < self._min_growth:
            warn = f"Low Growth Signal (score={growth})"

        return {"verdict": "PASS", "reason": "passed filter", "warn": warn}
