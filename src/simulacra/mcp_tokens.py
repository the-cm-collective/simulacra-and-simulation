from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactTokenMeasurement:
    artifact_file: str
    byte_count: int
    token_count: int
    tokenizer_requested: str
    tokenizer_actual: str
    estimation_method: str
    sha256: str


def measure_artifact_tokens(
    path: Path,
    *,
    tokenizer: str = "cl100k_base",
) -> ArtifactTokenMeasurement:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    token_count, tokenizer_actual, method = estimate_text_tokens(text, raw, tokenizer=tokenizer)
    return ArtifactTokenMeasurement(
        artifact_file=str(path),
        byte_count=len(raw),
        token_count=token_count,
        tokenizer_requested=tokenizer,
        tokenizer_actual=tokenizer_actual,
        estimation_method=method,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def estimate_text_tokens(
    text: str,
    raw: bytes | None = None,
    *,
    tokenizer: str = "cl100k_base",
) -> tuple[int, str, str]:
    try:
        import tiktoken  # type: ignore[import-not-found]

        encoding = tiktoken.get_encoding(tokenizer)
    except Exception:
        raw_bytes = raw if raw is not None else text.encode("utf-8")
        return max(1, math.ceil(len(raw_bytes) / 4)), "bytes_div_4", "heuristic_bytes_div_4"
    return len(encoding.encode(text)), tokenizer, "tiktoken"
