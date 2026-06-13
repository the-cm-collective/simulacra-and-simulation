from __future__ import annotations

from pathlib import Path


def build_context_review_prompt(
    *,
    output: Path,
    title: str,
    instruction: str,
    context_files: list[Path],
    context_label: str,
    max_bytes_per_file: int,
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
    for context_file in context_files:
        parts.extend(["", f"## {label}: {context_file}", "", "```text"])
        parts.append(_read_context(context_file, max_bytes=max_bytes_per_file))
        parts.append("```")
    output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output


def _read_context(path: Path, *, max_bytes: int) -> str:
    if not path.exists():
        return f"[missing context file: {path}]"
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    if truncated:
        text += f"\n[truncated after {max_bytes} bytes from {len(data)} total bytes]"
    return text
