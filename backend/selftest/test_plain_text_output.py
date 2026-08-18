"""纯文本输出：回复既要朗读也要整段显示，不该有 markdown 式空行分段，也不该夹英文。

现场：AI 回复里出现了空行分段（模型带上了文学化的段落排版习惯）和英文单词加
中文注释的点缀（比如 "stiff（硬挺）"）。四个 prompt（normal/proactive/closing/
crisis）的说话风格约束里都没有一条明确禁止这两件事，模型在 0.75 的 temperature
下偶尔就会往这个方向发挥。
"""
from prompts.templates import (
    build_normal_prompt,
    build_proactive_prompt,
    build_closing_prompt,
    build_crisis_prompt,
)


def _normal() -> str:
    return build_normal_prompt('neutral', {})


def _proactive() -> str:
    return build_proactive_prompt('王爷爷', 'scheduled')


def _closing() -> str:
    return build_closing_prompt()


def _crisis() -> str:
    return build_crisis_prompt()


# ─── 不许换行分段 ────────────────────────────────────────────────────────────

def test_normal_prompt_forbids_line_breaks():
    assert '换行' in _normal()


def test_proactive_prompt_forbids_line_breaks():
    assert '换行' in _proactive()


def test_closing_prompt_forbids_line_breaks():
    assert '换行' in _closing()


def test_crisis_prompt_forbids_line_breaks():
    assert '换行' in _crisis()


# ─── 不许夹杂英文 ────────────────────────────────────────────────────────────

def test_normal_prompt_forbids_english():
    assert '英文' in _normal()


def test_proactive_prompt_forbids_english():
    assert '英文' in _proactive()


def test_closing_prompt_forbids_english():
    assert '英文' in _closing()


def test_crisis_prompt_forbids_english():
    assert '英文' in _crisis()
