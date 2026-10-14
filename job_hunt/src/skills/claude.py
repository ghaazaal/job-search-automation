"""The one place this feature talks to the Claude API.

Everything else depends on `JsonModel` — a callable that takes a system
prompt, a user prompt and a JSON schema and returns the parsed object — so
tests hand in a fake and never touch the network.

The key comes from the environment (ANTHROPIC_API_KEY, which main.py loads
from job_hunt/.env), never from config.yaml and never from a log line.
"""
import json
import os

DEFAULT_MODEL = "claude-opus-5-5"

# Models that accept the server-side refusal fallback. On a safety decline
# the API re-runs the request on a fallback model inside the same call, so
# a false positive on one posting does not fail the whole analysis.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                    "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelError(RuntimeError):
    """The model answered, but not with something usable."""


class ClaudeJson:
    """Structured-output calls: the response is JSON matching `schema`."""

    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        if client is None:
            if not (os.environ.get("ANTHROPIC_API_KEY")
                    or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set. Add it to job_hunt/.env "
                    "or set it in your shell, then try again.")
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError("The anthropic package is not installed. "
                                   "Run: pip install anthropic") from exc
            client = anthropic.Anthropic()
        self._client = client
        self.model = model

    def _params(self, system: str, prompt: str, schema: dict, effort: str,
                max_tokens: int) -> dict:
        return dict(
            model=self.model,
            max_tokens=max_tokens,
            # The system prompt is identical across every call of one kind,
            # so it is cached; only the postings change.
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort,
                           "format": {"type": "json_schema",
                                      "schema": schema}},
        )

    def __call__(self, *, system: str, prompt: str, schema: dict,
                 effort: str = "low", max_tokens: int = 16000) -> dict:
        kwargs = self._params(system, prompt, schema, effort, max_tokens)
        if self.model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["extra_body"] = {"fallbacks": "default"}
            response = self._client.beta.messages.create(**kwargs)
        else:
            response = self._client.messages.create(**kwargs)
        return _parse(response)

    def batch(self, requests: list[tuple[str, str, str]], *, schema: dict,
              effort: str = "low", max_tokens: int = 16000,
              on_wait=None, poll_seconds: float = 30.0) -> dict:
        """Run many requests through the Message Batches API: half price,
        answered within minutes to an hour (24 at most).

        `requests` is [(custom_id, system, prompt)]. Returns custom_id ->
        parsed dict, or the exception for that request. The server-side
        refusal fallback is not available on batches, so a declined
        request simply comes back as an error and is retried next time.
        """
        import time

        created = self._client.messages.batches.create(requests=[
            {"custom_id": cid,
             "params": self._params(system, prompt, schema, effort,
                                    max_tokens)}
            for cid, system, prompt in requests])
        while True:
            status = self._client.messages.batches.retrieve(created.id)
            if status.processing_status == "ended":
                break
            if on_wait:
                counts = status.request_counts
                on_wait(counts.succeeded + counts.errored + counts.canceled
                        + counts.expired, len(requests))
            time.sleep(poll_seconds)

        out: dict = {}
        for item in self._client.messages.batches.results(created.id):
            result = item.result
            if result.type != "succeeded":
                out[item.custom_id] = ModelError(
                    f"batch request {result.type}")
                continue
            try:
                out[item.custom_id] = _parse(result.message)
            except ModelError as exc:
                out[item.custom_id] = exc
        return out


def _parse(response) -> dict:
    if response.stop_reason == "refusal":
        raise ModelError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise ModelError("Claude's answer was cut off at the length limit.")
    text = next((b.text for b in response.content
                 if getattr(b, "type", "") == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelError("Claude's answer was not valid JSON.") from exc
