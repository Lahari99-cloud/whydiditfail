from __future__ import annotations

from wdif.extractors import SpanExtractor, extract_documents, extract_prompt
from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan
from wdif.tokenization import TokenCounter, TokenizerRegistry


class LostInTheMiddleHeuristic:
    """Detects retrieved evidence buried in the weakest region of long prompts."""

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
        token_counter: TokenCounter | None = None,
        min_prompt_tokens: int = 4000,
        blindspot_start_pct: float = 20.0,
        blindspot_end_pct: float = 80.0,
        max_prompt_chars: int = 100_000,
        extractor: SpanExtractor | None = None,
        tokenizer_registry: TokenizerRegistry | None = None,
    ):
        self.tokenizer = token_counter or TokenCounter(encoding_name)
        self.min_prompt_tokens = min_prompt_tokens
        self.blindspot_start_pct = blindspot_start_pct
        self.blindspot_end_pct = blindspot_end_pct
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
        total_tokens = tokenizer.count(prompt)
        if total_tokens < self.min_prompt_tokens:
            return None

        for idx, chunk in enumerate(extract_documents(span, self.extractor)):
            chunk_text = str(chunk.get("content") or chunk.get("text") or "")
            if not chunk_text:
                continue

            start_char_idx = prompt.find(chunk_text)
            if start_char_idx == -1:
                continue

            leading_text = prompt[:start_char_idx]
            chunk_end_char_idx = start_char_idx + len(chunk_text)
            chunk_start_token = self._estimate_prefix_tokens(
                tokenizer,
                prompt,
                start_char_idx,
                total_tokens,
            )
            chunk_tokens = tokenizer.count(chunk_text)
            chunk_center_token = chunk_start_token + (chunk_tokens // 2)
            position_percentage = (chunk_center_token / total_tokens) * 100

            if self.blindspot_start_pct <= position_percentage <= self.blindspot_end_pct:
                doc_id = str(chunk.get("id") or f"chunk_idx_{idx}")
                return FailureDiagnostic(
                    failure_type=FailureType.LOST_IN_THE_MIDDLE,
                    severity="CRITICAL",
                    target_span_id=span.span_id,
                    message=(
                        f"Critical chunk '{doc_id}' is buried at the "
                        f"{position_percentage:.1f}% mark of a {total_tokens}-token prompt."
                    ),
                    metadata={
                        "total_prompt_tokens": total_tokens,
                        "chunk_id": doc_id,
                        "chunk_position_percentage": round(position_percentage, 2),
                        "chunk_start_token": chunk_start_token,
                        "token_count_mode": (
                            "estimated" if len(prompt) > self.max_prompt_chars else "exact"
                        ),
                        **(token_resolution.to_metadata() if token_resolution else {}),
                        "prompt_excerpt": prompt[:4000],
                        "layout_excerpt": self._layout_excerpt(
                            prompt,
                            start_char_idx,
                            chunk_end_char_idx,
                        ),
                        "chunk_excerpt": chunk_text[:1000],
                    },
                    suggested_fix=(
                        f"Move chunk '{doc_id}' into the first or last 10% of the prompt, "
                        "or reorder retrieved context by answer-criticality."
                    ),
                )

        return None

    def _estimate_prefix_tokens(
        self,
        tokenizer: TokenCounter,
        prompt: str,
        char_index: int,
        total_tokens: int,
    ) -> int:
        if len(prompt) <= self.max_prompt_chars:
            return tokenizer.count(prompt[:char_index])
        return int(total_tokens * (char_index / len(prompt)))

    @staticmethod
    def _layout_excerpt(prompt: str, start: int, end: int, radius: int = 700) -> str:
        excerpt_start = max(0, start - radius)
        excerpt_end = min(len(prompt), end + radius)
        return prompt[excerpt_start:excerpt_end]
