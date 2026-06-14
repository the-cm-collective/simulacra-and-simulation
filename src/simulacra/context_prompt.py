from __future__ import annotations

from pathlib import Path

from .prompt_meta import source_context, write_prompt_metadata


def build_context_review_prompt(
    *,
    output: Path,
    title: str,
    instruction: str,
    context_files: list[Path],
    context_label: str,
    max_bytes_per_file: int,
    copied_context_class: str = "k1s_docs",
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    label = context_label.strip() or "Context"
    parts = [
        title.strip(),
        "",
        instruction.strip(),
        "",
        f"The following {label.lower()} was manually gathered by the operator.",
        "Treat it as human-provided context and verify the path before recommending action.",
    ]
    sources = []
    for context_file in context_files:
        parts.extend(["", f"## {label}: {context_file}", "", "```text"])
        text, metadata = source_context(context_file, max_bytes=max_bytes_per_file)
        parts.append(text.replace("[missing file:", "[missing context file:"))
        parts.append("```")
        sources.append(metadata)
    output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    write_prompt_metadata(
        output,
        prompt_kind="context_review",
        copied_context_class=copied_context_class,
        sources=sources,
        context_label=label,
    )
    return output
