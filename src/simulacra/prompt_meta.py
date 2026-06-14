from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROMPT_META_SCHEMA_VERSION = "simulacra.prompt-meta.v1"
COPIED_CONTEXT_CLASSES = {
    "local_logs",
    "k1s_docs",
    "remote_failure_logs",
    "operator_summary",
    "other",
}


def prompt_meta_path(prompt_path: Path) -> Path:
    return prompt_path.with_suffix(".prompt-meta.json")


def source_context(path: Path, *, max_bytes: int) -> tuple[str, dict[str, Any]]:
    exists = path.exists()
    data = path.read_bytes() if exists else b""
    available = len(data)
    truncated = available > max_bytes
    embedded = data[:max_bytes]
    text = embedded.decode("utf-8", errors="replace") if exists else f"[missing file: {path}]"
    if truncated:
        text += f"\n[truncated after {max_bytes} bytes from {available} total bytes]"
    metadata = {
        "path": str(path),
        "exists": exists,
        "available_bytes": available,
        "embedded_bytes": len(embedded) if exists else 0,
        "truncated": truncated,
    }
    return text, metadata


def write_prompt_metadata(
    output: Path,
    *,
    prompt_kind: str,
    copied_context_class: str,
    sources: list[dict[str, Any]],
    context_label: str | None = None,
) -> Path:
    normalized_class = (
        copied_context_class if copied_context_class in COPIED_CONTEXT_CLASSES else "other"
    )
    metadata = {
        "schema_version": PROMPT_META_SCHEMA_VERSION,
        "prompt_kind": prompt_kind,
        "copied_context_class": normalized_class,
        "context_label": context_label,
        "sources": sources,
        "source_count": len(sources),
        "total_available_bytes": sum(int(source.get("available_bytes") or 0) for source in sources),
        "total_embedded_bytes": sum(int(source.get("embedded_bytes") or 0) for source in sources),
        "truncated_source_count": sum(1 for source in sources if source.get("truncated")),
    }
    path = prompt_meta_path(output)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_prompt_metadata(prompt_path: Path) -> dict[str, Any] | None:
    path = prompt_meta_path(prompt_path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
