"""文本切块（产品书 M3-1「切片 + 结构化数据文本化」；rag 架构规划的 chunking.py）。

纯函数、无 IO、确定性（同输入同输出），可离线测试与复跑。

策略（面向中文招生语料）：
1. 段落切分：优先空行，退而单个换行；
2. 超长段二次切：按句末标点断句后向目标长度拼装，单句仍超长则硬切；
3. 短段合并：低于 ``min_len`` 的段与相邻段合并，尽量逼近 ``target``；
4. 保序、不丢字：全部切片去掉空白后拼接，与原文去掉空白后内容一致。

服务层 ``corpus.create_doc`` 的语义不变（chunks 给什么存什么）；
本模块供语料导入 CLI（``app.services.corpus_packs``）与后续索引流程使用，
不引入任何模型或网络依赖。
"""

from __future__ import annotations

import re

CHUNK_TARGET = 500  # 拼装目标长度（字符）
CHUNK_MAX = 800     # 单切片硬上限（字符）
CHUNK_MIN = 120     # 低于该长度的段倾向于并入相邻段

# 句末标点（中英文句号/问号/叹号/分号）；用 lookbehind 保留标点在句尾
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])")
# 任意换行都视为段落边界（中文公文常单换行分段）
_PARAGRAPH_SPLIT = re.compile(r"\r\n|\r|\n")
# 连续空白段（含 - * · 等孤立符号行）丢弃
_PLACEHOLDER_LINE = re.compile(r"^[\s\-—–*·•.。]*$")


def _split_sentences(text: str) -> list[str]:
    """按句末标点断句；标点保留在句尾，无标点则整段视为一句。"""
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _cut_long(paragraph: str, max_len: int) -> list[str]:
    """超长段落：断句拼装到不超过 max_len；单句仍超长则按 max_len 硬切。"""
    pieces: list[str] = []
    buffer = ""
    for sentence in _split_sentences(paragraph):
        while len(sentence) > max_len:  # 单句超长：先硬切出整块
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.append(sentence[:max_len])
            sentence = sentence[max_len:]
        if not sentence:
            continue
        if not buffer:
            buffer = sentence
        elif len(buffer) + len(sentence) <= max_len:
            buffer += sentence
        else:
            pieces.append(buffer)
            buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def _merge_short(pieces: list[str], target: int, max_len: int, min_len: int) -> list[str]:
    """相邻段合并：buffer 未到 target 或下一段过短时并入，超 max_len 立即切出。"""
    merged: list[str] = []
    buffer = ""
    for piece in pieces:
        if not buffer:
            buffer = piece
            continue
        if len(buffer) + len(piece) <= max_len and (len(buffer) < target or len(piece) <= min_len):
            buffer += "\n" + piece
        else:
            merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)
    return merged


def split_chunks(
    text: str,
    *,
    target: int = CHUNK_TARGET,
    max_len: int = CHUNK_MAX,
    min_len: int = CHUNK_MIN,
) -> list[str]:
    """把正文切成检索友好的切片列表。

    - 空文本 / 全空白 → ``[]``（调用方不应为空文本文档造切片）；
    - 短文本（≤ max_len 且无段落结构诉求）→ 原文单切片；
    - 结果保序，切片间以换行衔接的部分已并入切片内部。
    """
    if not isinstance(text, str) or not text.strip():
        return []
    if max_len < min_len or target > max_len or min_len < 1:
        raise ValueError("切块参数需满足 1 <= min_len <= target <= max_len")

    paragraphs = [
        line.strip()
        for line in _PARAGRAPH_SPLIT.split(text)
        if line.strip() and not _PLACEHOLDER_LINE.match(line)
    ]
    if not paragraphs:
        return []

    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_len:
            pieces.append(paragraph)
        else:
            pieces.extend(_cut_long(paragraph, max_len))
    return _merge_short(pieces, target=target, max_len=max_len, min_len=min_len)


__all__ = ["split_chunks", "CHUNK_TARGET", "CHUNK_MAX", "CHUNK_MIN"]
