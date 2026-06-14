from __future__ import annotations

from pathlib import Path

from simulacra.codex_events import aggregate_usage, normalize_codex_jsonl


def test_normalize_codex_usage(tmp_path: Path) -> None:
    jsonl = tmp_path / "codex.jsonl"
    jsonl.write_text(
        '{"type":"thread.started","thread_id":"t1"}\n'
        '{"type":"turn.completed","usage":{"input_tokens":10,'
        '"cached_input_tokens":4,"output_tokens":3,"reasoning_output_tokens":2}}\n',
        encoding="utf-8",
    )

    events = normalize_codex_jsonl(jsonl, run_id="r1", track="workerbee-codex")

    assert len(events) == 2
    assert events[0].payload["thread_id"] == "t1"
    assert events[0].payload["source_file"] == str(jsonl)
    assert len(str(events[0].payload["source_sha256"])) == 64
    assert aggregate_usage(events) == {
        "input_tokens": 10,
        "cached_input_tokens": 4,
        "output_tokens": 3,
        "reasoning_output_tokens": 2,
    }
