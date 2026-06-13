from __future__ import annotations

from pathlib import Path


def build_log_review_prompt(
    *,
    output: Path,
    title: str,
    instruction: str,
    log_files: list[Path],
    max_bytes_per_log: int,
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
    for log_file in log_files:
        parts.extend(["", f"## Log: {log_file}", "", "```text"])
        parts.append(_read_log(log_file, max_bytes=max_bytes_per_log))
        parts.append("```")
    output.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output


def _read_log(path: Path, *, max_bytes: int) -> str:
    if not path.exists():
        return f"[missing log file: {path}]"
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    if truncated:
        text += f"\n[truncated after {max_bytes} bytes from {len(data)} total bytes]"
    return text
