from __future__ import annotations

from wdif.extractors import SpanExtractor, extract_prompt
from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan
from wdif.tokenization import TokenCounter, TokenizerRegistry


class ContextStuffingHeuristic:
    """Flags prompts that are likely overfilled relative to a configured context limit."""

    def __init__(
        self,
        max_context_tokens: int = 8192,
        warning_ratio: float = 0.9,
        token_counter: TokenCounter | None = None,
        max_prompt_chars: int = 100_000,
        extractor: SpanExtractor | None = None,
        tokenizer_registry: TokenizerRegistry | None = None,
    ):
        self.max_context_tokens = max_context_tokens
        self.warning_ratio = warning_ratio
        self.tokenizer = token_counter or TokenCounter()
        self.max_prompt_chars = max_prompt_chars
        self.extractor = extractor
        self.tokenizer_registry = tokenizer_registry

    def analyze_span(self, span: TraceSpan) -> FailureDiagnostic | None:
        if span.span_type != SpanType.LLM:
            return None

        prompt = extract_prompt(span, self.extractor)
        if not prompt:
            return None

        token_resolution = self.tokenizer_registry.resolve(span) if self.tokenizer_registry else None
        tokenizer = token_resolution.counter if token_resolution else self.tokenizer
        token_count = tokenizer.count(prompt)
        if token_count < int(self.max_context_tokens * self.warning_ratio):
            return None

        severity = "CRITICAL" if token_count >= self.max_context_tokens else "WARNING"
        return FailureDiagnostic(
            failure_type=FailureType.CONTEXT_STUFFING,
            severity=severity,
            target_span_id=span.span_id,
            message=(
                f"Prompt uses {token_count} tokens against a "
                f"{self.max_context_tokens}-token diagnostic budget."
            ),
            metadata={
                "prompt_tokens": token_count,
                "max_context_tokens": self.max_context_tokens,
                "usage_ratio": round(token_count / self.max_context_tokens, 3),
                "token_count_mode": "estimated" if len(prompt) > self.max_prompt_chars else "exact",
                **(token_resolution.to_metadata() if token_resolution else {}),
            },
            suggested_fix=(
                "Reduce retrieved chunk count, compress context, or reserve explicit "
                "budget for instructions and the final user question."
            ),
        )
