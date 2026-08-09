"""Config loading — personal details come from the environment.

config.yaml is committed to a public repo, so the candidate's name, email,
LinkedIn and resume path live in .env (gitignored) instead. Anything still
present in config.yaml is used as a fallback.
"""
import copy
import os

# env var -> key inside the config's `resume` section
_RESUME_ENV = {
    "CANDIDATE_NAME":     "candidate_name",
    "CANDIDATE_EMAIL":    "email",
    "CANDIDATE_LINKEDIN": "linkedin",
    "RESUME_PATH":        "canonical_path",
}


def apply_env_overrides(config: dict) -> dict:
    """Return a copy of `config` with personal details resolved.

    Precedence: environment variable, then config.yaml, then empty string —
    a fresh clone with no .env must load rather than raise KeyError.
    """
    resolved = copy.deepcopy(config)
    resume = resolved.setdefault("resume", {})
    for env_key, cfg_key in _RESUME_ENV.items():
        value = os.environ.get(env_key, "").strip()
        resume[cfg_key] = value or resume.get(cfg_key) or ""
    return resolved
