from __future__ import annotations

from pathlib import Path

from .prompt_meta import source_context, write_prompt_metadata


def build_log_review_prompt(
    *,
    output: Path,
    title: str,
    instruction: str,
    log_files: list[Path],
    max_bytes_per_log: int,
    copied_context_class: str = "local_logs",
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        title.strip(),
        "",
        instruction.strip(),
        "",
        "The following logs were manually copied from local consoles. They may contain redundant,"
        " stale, or irrelevant lines; treat them as uncurated human-provided context.",
    ]
    sources = []
    for log_file in log_files:
        parts.extend(["", f"## Log: {log_file}", "", "```text"])
        text, metadata = source_context(log_file, max_bytes=max_bytes_per_log)
        parts.append(text.replace("[missing file:", "[missing log file:"))
        parts.append("```")
        sources.append(metadata)
    output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    write_prompt_metadata(
        output,
        prompt_kind="log_review",
        copied_context_class=copied_context_class,
        sources=sources,
        context_label="Log",
    )
    return output
