from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class PromptPatch:
    title: str
    diff: str
    before: str
    after: str


def build_context_reorder_patch(
    prompt_template: str,
    chunk_text: str,
    placement: str = "suffix",
) -> PromptPatch | None:
    """Create a unified diff that moves a critical chunk to prompt edge position."""

    if not chunk_text or chunk_text not in prompt_template:
        return None

    before_lines = prompt_template.splitlines()
    prompt_without_chunk = prompt_template.replace(chunk_text, "").strip()

    if placement == "prefix":
        after = f"{chunk_text.strip()}\n\n{prompt_without_chunk}".strip()
    else:
        after = f"{prompt_without_chunk}\n\n{chunk_text.strip()}".strip()

    after_lines = after.splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="prompt_template.before",
            tofile="prompt_template.after",
            lineterm="",
        )
    )
    return PromptPatch(
        title=f"Move critical context chunk to prompt {placement}",
        diff=diff,
        before=prompt_template,
        after=after,
    )
