from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from resp_lanu.asr import (
    PhraseHint,
    _read_grammar_file,
    _read_phrase_hints,
    apply_phrase_hints,
)


def test_apply_phrase_hints_rewrites_aliases_and_merges_phrase_tokens() -> None:
    hints = [
        PhraseHint("树莓派五", frozenset({"树莓派五", "数没派五"}), 4),
        PhraseHint("中文语音识别系统", frozenset({"中文语音识别系统"}), 8),
        PhraseHint("语音识别实验", frozenset({"语音识别实验"}), 6),
    ]
    transcript = (
        "你好 今天 我们 在 数 没 派 五 上 测试 中文 语音 识别 系统 语音 识别 实验 已经 开始"
    )
    words = [
        {"word": "你好", "conf": 0.98},
        {"word": "今天", "conf": 1.0},
        {"word": "我们", "conf": 1.0},
        {"word": "在", "conf": 0.92},
        {"word": "数", "conf": 0.40},
        {"word": "没", "conf": 0.96},
        {"word": "派", "conf": 0.89},
        {"word": "五", "conf": 0.57},
        {"word": "上", "conf": 0.82},
        {"word": "测试", "conf": 0.89},
        {"word": "中文", "conf": 1.0},
        {"word": "语音", "conf": 0.78},
        {"word": "识别", "conf": 0.78},
        {"word": "系统", "conf": 1.0},
        {"word": "语音", "conf": 0.94},
        {"word": "识别", "conf": 0.94},
        {"word": "实验", "conf": 1.0},
        {"word": "已经", "conf": 1.0},
        {"word": "开始", "conf": 1.0},
    ]

    corrected, corrections = apply_phrase_hints(transcript, words, hints)

    assert corrected == "你好 今天 我们 在 树莓派五 上 测试 中文语音识别系统 语音识别实验 已经 开始"
    assert [item["to"] for item in corrections] == ["树莓派五", "中文语音识别系统", "语音识别实验"]
    assert corrections[0]["match_type"] == "alias"
    assert corrections[0]["avg_conf"] == pytest.approx(0.705, abs=1e-3)


def test_apply_phrase_hints_noops_without_hints() -> None:
    transcript = "你好 今天 我们 在 数 没 派 五 上 测试"
    corrected, corrections = apply_phrase_hints(transcript, [], [])
    assert corrected == transcript
    assert corrections == []


def test_read_grammar_file_requires_json_list() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        grammar_path = tmp_path / "grammar.json"
        grammar_path.write_text(
            json.dumps(["你好", "树莓派五"], ensure_ascii=False), encoding="utf-8"
        )
        assert _read_grammar_file(grammar_path) == '["你好", "树莓派五"]'

        invalid_path = tmp_path / "invalid_grammar.json"
        invalid_path.write_text(
            json.dumps({"phrase": "你好"}, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="JSON list"):
            _read_grammar_file(invalid_path)


def test_read_phrase_hints_normalizes_aliases_and_caps_window() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        hints_path = tmp_path / "hints.json"
        hints_path.write_text(
            json.dumps(
                [
                    "树 莓 派 五",
                    {
                        "phrase": "中文语音识别系统",
                        "aliases": ["中文 语音 识别 系统", "中文，语音，识别，系统"],
                    },
                    {
                        "phrase": "超长设备名称ABCDEFGH",
                        "aliases": ["超 长 设 备 名 称 A B C D E F G H"],
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        hints = _read_phrase_hints(hints_path)

        assert hints[0].phrase == "树莓派五"
        assert "中文语音识别系统" in hints[1].aliases
        assert "超长设备名称ABCDEFGH" in hints[2].aliases
        assert hints[2].max_window == 8


def test_read_phrase_hints_rejects_invalid_aliases() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        hints_path = Path(tmp_dir) / "bad_hints.json"
        hints_path.write_text(
            json.dumps([{"phrase": "树莓派五", "aliases": "数 没 派 五"}], ensure_ascii=False),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="string list"):
            _read_phrase_hints(hints_path)
