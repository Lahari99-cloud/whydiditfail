from __future__ import annotations

import re
from dataclasses import dataclass

from wdif.config.engine import TokenizerPolicy, TokenizerRoute
from wdif.extractors import SpanExtractor
from wdif.models import TraceSpan


class TokenCounter:
    """Tokenizer facade with tiktoken, local HuggingFace, and regex fallback modes."""

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
        provider: str = "tiktoken",
        local_path: str | None = None,
        max_encode_chars: int = 100_000,
    ):
        self.encoding_name = encoding_name
        self.provider = provider.lower()
        self.local_path = local_path
        self.max_encode_chars = max_encode_chars
        self._encoding = None
        self._hf_tokenizer = None
        self.backend = "regex"

        if self.provider == "huggingface":
            self._load_huggingface_tokenizer()
        elif self.provider == "regex":
            return
        else:
            self._load_tiktoken()

    @classmethod
    def from_policy(cls, policy: TokenizerPolicy) -> "TokenCounter":
        return cls(
            encoding_name=policy.name,
            provider=policy.provider,
            local_path=policy.local_path,
        )

    def encode(self, text: str) -> list[int] | list[str]:
        text = self._bounded_text(text)
        if self._encoding is not None:
            return self._encoding.encode(text)
        if self._hf_tokenizer is not None:
            return self._hf_tokenizer.encode(text)
        return re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)

    def count(self, text: str) -> int:
        if len(text) > self.max_encode_chars:
            return self.estimate_count(text)
        return len(self.encode(text))

    def estimate_count(self, text: str) -> int:
        if not text:
            return 0
        head = text[: self.max_encode_chars // 2]
        tail = text[-(self.max_encode_chars // 2) :]
        sample = head + tail
        sample_count = len(self.encode(sample))
        return max(1, int(sample_count * (len(text) / len(sample))))

    def count_prefix(self, text: str) -> int:
        return self.count(text)

    def _bounded_text(self, text: str) -> str:
        if len(text) <= self.max_encode_chars:
            return text
        half = self.max_encode_chars // 2
        return text[:half] + text[-half:]

    def _load_tiktoken(self) -> None:
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding(self.encoding_name)
            self.backend = "tiktoken"
        except Exception:
            self._encoding = None

    def _load_huggingface_tokenizer(self) -> None:
        try:
            from tokenizers import Tokenizer

            source = self.local_path or self.encoding_name
            self._hf_tokenizer = Tokenizer.from_file(source)
            self.backend = "huggingface"
            return
        except Exception:
            pass

        try:
            from transformers import AutoTokenizer

            source = self.local_path or self.encoding_name
            self._hf_tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
            self.backend = "huggingface"
        except Exception:
            self._hf_tokenizer = None


@dataclass
class TokenizerResolution:
    counter: TokenCounter
    model_name: str
    provider: str
    tokenizer_name: str
    backend: str
    matched_route: str | None
    fidelity: str
    warning: str | None = None

    def to_metadata(self) -> dict[str, str | None]:
        return {
            "tokenizer_model_name": self.model_name or None,
            "tokenizer_provider": self.provider,
            "tokenizer_name": self.tokenizer_name,
            "tokenizer_backend": self.backend,
            "tokenizer_route": self.matched_route,
            "tokenizer_fidelity": self.fidelity,
            "tokenizer_warning": self.warning,
        }


class TokenizerRegistry:
    """Routes spans to tokenizer counters based on model metadata."""

    def __init__(
        self,
        default_policy: TokenizerPolicy | None = None,
        routes: list[TokenizerRoute] | None = None,
        extractor: SpanExtractor | None = None,
    ):
        self.default_policy = default_policy or TokenizerPolicy()
        self.routes = routes or []
        self.extractor = extractor or SpanExtractor()
        self._cache: dict[tuple[str, str, str | None], TokenCounter] = {}

    def resolve(self, span: TraceSpan) -> TokenizerResolution:
        model_name = self.extractor.extract_model_name(span)
        route = self._match_route(model_name)
        policy = (
            TokenizerPolicy(
                provider=route.provider,
                name=route.name,
                local_path=route.local_path,
            )
            if route
            else self.default_policy
        )
        counter = self._counter_for(policy)

        warning = None
        fidelity = "configured"
        if counter.backend != policy.provider.lower() and policy.provider.lower() != "regex":
            fidelity = "fallback"
            if route:
                warning = (
                    f"Configured tokenizer for route '{route.match}' could not be loaded; "
                    "regex fallback was used."
                )
            else:
                warning = (
                    f"Configured tokenizer '{policy.name}' could not be loaded; "
                    "regex fallback was used."
                )
        elif model_name and not route:
            fidelity = "fallback"
            warning = (
                f"Unknown tokenizer family for model '{model_name}'. "
                "Token geometry used the global fallback tokenizer."
            )

        return TokenizerResolution(
            counter=counter,
            model_name=model_name,
            provider=policy.provider.lower(),
            tokenizer_name=policy.name,
            backend=counter.backend,
            matched_route=route.match if route else None,
            fidelity=fidelity,
            warning=warning,
        )

    def _match_route(self, model_name: str) -> TokenizerRoute | None:
        if not model_name:
            return None
        normalized = model_name.lower()
        for route in self.routes:
            if route.match.lower() in normalized:
                return route
        return None

    def _counter_for(self, policy: TokenizerPolicy) -> TokenCounter:
        key = (policy.provider.lower(), policy.name, policy.local_path)
        if key not in self._cache:
            self._cache[key] = TokenCounter.from_policy(policy)
        return self._cache[key]
