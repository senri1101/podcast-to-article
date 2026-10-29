import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"


def run(script, *args):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def row(out, name):
    for line in out.splitlines():
        if line.startswith(name):
            return line
    raise AssertionError(f"{name} の行がない:\n{out}")


class CheckStyleChinese(unittest.TestCase):
    def test_chinese_output_is_unchanged(self):
        code, out, _ = run("check_style.py", FIX / "zh_sample.md")
        self.assertEqual(code, 0)
        body = [l for l in out.splitlines() if not l.startswith("言語:")]
        self.assertEqual(body, (FIX / "zh_expected.txt").read_text(encoding="utf-8").splitlines())

    def test_chinese_is_detected_automatically(self):
        _, out, _ = run("check_style.py", FIX / "zh_sample.md")
        self.assertIn("言語: 中国語", out)


class CheckStyleJapanese(unittest.TestCase):
    def setUp(self):
        _, self.out, _ = run("check_style.py", FIX / "ja_sloppy.md")

    def test_japanese_is_detected_automatically(self):
        self.assertIn("言語: 日本語", self.out)

    def test_hard_banned_patterns_are_flagged(self):
        for name in ["ダッシュ", "対比構文（XではなくY）", "まとめ口調", "話し手の態度を代わりに描く"]:
            self.assertIn("❌", row(self.out, name), name)

    def test_paragraph_opening_with_unanchored_comment_is_reported(self):
        self.assertIn("注目すべきは", self.out)

    def test_japanese_quotes_are_counted(self):
        self.assertIn("1 か所", row(self.out, "直接引用"))

    def test_baselines_are_marked_as_unmeasured(self):
        self.assertIn("未測定", self.out)

    def test_clean_japanese_has_no_hard_failures(self):
        _, out, _ = run("check_style.py", FIX / "ja_clean.md")
        self.assertNotIn("必ず禁止する項目に該当", out)

    def test_language_can_be_forced(self):
        _, out, _ = run("check_style.py", FIX / "zh_sample.md", "--lang", "ja")
        self.assertIn("言語: 日本語", out)


class PrepTranscriptJapanese(unittest.TestCase):
    def test_kana_speaker_names_are_recognized(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("ノア：こんにちは。\nたなか：よろしくお願いします。\n結論：まだ決めていない。\n", encoding="utf-8")
            _, out, _ = run("prep_transcript.py", p, "--speakers")
        self.assertIn("ノア", out)
        self.assertIn("たなか", out)
        self.assertNotIn("結論", out)

    def test_stats_count_kana_for_japanese(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.txt"
            p.write_text("ノア：ありがとう。\n", encoding="utf-8")
            _, _, err = run("prep_transcript.py", p)
        self.assertIn("文字 7", err)


if __name__ == "__main__":
    unittest.main()
