from __future__ import annotations

from pathlib import Path

from simulacra.mcp_tokens import estimate_text_tokens, measure_artifact_tokens


def test_measure_artifact_tokens_reports_bytes_hash_and_token_count(tmp_path: Path) -> None:
    artifact = tmp_path / "workerbee-status.json"
    artifact.write_text('{"status":"ready","logs":["one","two"]}\n', encoding="utf-8")

    measurement = measure_artifact_tokens(artifact)

    assert measurement.artifact_file == str(artifact)
    assert measurement.byte_count == artifact.stat().st_size
    assert measurement.token_count > 0
    assert len(measurement.sha256) == 64
    assert measurement.tokenizer_requested == "cl100k_base"


def test_estimate_text_tokens_has_heuristic_fallback_for_unknown_tokenizer() -> None:
    token_count, tokenizer, method = estimate_text_tokens(
        "abcdef",
        raw=b"abcdef",
        tokenizer="not-a-real-tokenizer",
    )

    assert token_count == 2
    assert tokenizer == "bytes_div_4"
    assert method == "heuristic_bytes_div_4"
