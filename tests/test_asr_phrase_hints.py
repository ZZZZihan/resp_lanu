from __future__ import annotations

import unittest

from resp_lanu.asr import PhraseHint, apply_phrase_hints


class PhraseHintTests(unittest.TestCase):
    def test_apply_phrase_hints_rewrites_aliases_and_merges_phrase_tokens(self) -> None:
        hints = [
            PhraseHint("树莓派五", frozenset({"树莓派五", "数没派五"}), 4),
            PhraseHint("中文语音识别系统", frozenset({"中文语音识别系统"}), 8),
            PhraseHint("语音识别实验", frozenset({"语音识别实验"}), 6),
        ]
        transcript = "你好 今天 我们 在 数 没 派 五 上 测试 中文 语音 识别 系统 语音 识别 实验 已经 开始"
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

        self.assertEqual(
            corrected,
            "你好 今天 我们 在 树莓派五 上 测试 中文语音识别系统 语音识别实验 已经 开始",
        )
        self.assertEqual(
            [item["to"] for item in corrections],
            ["树莓派五", "中文语音识别系统", "语音识别实验"],
        )
        self.assertEqual(corrections[0]["match_type"], "alias")
        self.assertAlmostEqual(corrections[0]["avg_conf"], 0.705, places=3)

    def test_apply_phrase_hints_noops_without_hints(self) -> None:
        transcript = "你好 今天 我们 在 数 没 派 五 上 测试"
        corrected, corrections = apply_phrase_hints(transcript, [], [])
        self.assertEqual(corrected, transcript)
        self.assertEqual(corrections, [])


if __name__ == "__main__":
    unittest.main()
