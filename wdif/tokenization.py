from __future__ import annotations

import re

from wdif.config.engine import TokenizerPolicy


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
        except Exception:
            self._encoding = None

    def _load_huggingface_tokenizer(self) -> None:
        try:
            from tokenizers import Tokenizer

            source = self.local_path or self.encoding_name
            self._hf_tokenizer = Tokenizer.from_file(source)
            return
        except Exception:
            pass

        try:
            from transformers import AutoTokenizer

            source = self.local_path or self.encoding_name
            self._hf_tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
        except Exception:
            self._hf_tokenizer = None
