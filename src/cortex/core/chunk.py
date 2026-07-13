"""Pure text functions: Obsidian-flavored markdown cleaning and chunking.
No I/O here — behavior is pinned by tests/test_chunk.py."""

import re
from dataclasses import dataclass
from typing import Any

import yaml

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_EMBED = re.compile(r"!\[\[[^\[\]]*\]\]")
_WIKILINK = re.compile(r"\[\[([^\[\]]+?)\]\]")
_HEADING = re.compile(r"^#{1,6}\s")
_FENCE = re.compile(r"^(```|~~~)")


@dataclass
class Chunk:
    seq: int
    text: str
    start: int
    end: int


def clean_markdown(raw: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter into metadata (never indexed as prose) and
    normalize Obsidian syntax: ![[embeds]] dropped, [[wikilinks]] unwrapped
    to their inner text ([[page|alias]] keeps the alias)."""
    metadata: dict[str, Any] = {}
    text = raw
    match = _FRONTMATTER.match(raw)
    if match:
        # Malformed frontmatter is still stripped — it just yields no metadata.
        text = raw[match.end():]
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, dict):
            metadata = parsed
    text = _EMBED.sub("", text)
    text = _WIKILINK.sub(lambda m: m.group(1).split("|")[-1].strip(), text)
    return metadata, text


def chunk(text: str, target: int = 1000, overlap: int = 150) -> list[Chunk]:
    """Split on headings, then pack paragraphs into ~target-char chunks with
    ~overlap chars carried between consecutive chunks. Headings are hard
    boundaries: no chunk or overlap crosses one. Spans index into `text`,
    so chunk.text == text[chunk.start:chunk.end] always holds."""
    spans: list[tuple[int, int]] = []
    for sec_start, sec_end in _sections(text):
        spans.extend(_pack(text, _paragraphs(text, sec_start, sec_end), target, overlap))
    return [
        Chunk(seq, text[start:end], start, end)
        for seq, (start, end) in enumerate(spans)
        if text[start:end].strip()
    ]


def _sections(text: str) -> list[tuple[int, int]]:
    """Spans between markdown headings; '#' inside fenced code is not a heading."""
    bounds = [0]
    offset = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and _HEADING.match(line) and offset:
            bounds.append(offset)
        offset += len(line)
    bounds.append(len(text))
    return [(s, e) for s, e in zip(bounds, bounds[1:]) if text[s:e].strip()]


def _paragraphs(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Blank-line-separated blocks inside text[start:end]; blank lines inside
    fenced code do not split a block."""
    blocks: list[tuple[int, int]] = []
    offset = start
    block_start: int | None = None
    in_fence = False
    for line in text[start:end].splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if block_start is not None:
                blocks.append((block_start, offset))
                block_start = None
        elif block_start is None:
            block_start = offset
        offset += len(line)
    if block_start is not None:
        blocks.append((block_start, offset))
    return blocks


def _pack(
    text: str, paras: list[tuple[int, int]], target: int, overlap: int
) -> list[tuple[int, int]]:
    """Greedy-pack paragraph spans into windows of at most target chars."""
    spans: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    for p_start, p_end in paras:
        if p_end - p_start > target:
            if cur:
                spans.append(cur)
                cur = None
            spans.extend(_hard_split(text, p_start, p_end, target, overlap))
        elif cur is None:
            start = _overlap_start(text, spans[-1][1], overlap) if spans else p_start
            cur = (min(start, p_start), p_end)
        elif p_end - cur[0] <= target:
            cur = (cur[0], p_end)
        else:
            spans.append(cur)
            cur = (_overlap_start(text, cur[1], overlap), p_end)
    if cur:
        spans.append(cur)
    return spans


def _hard_split(
    text: str, start: int, end: int, target: int, overlap: int
) -> list[tuple[int, int]]:
    """Split one oversized block (huge paragraph or code fence) at ~target chars."""
    spans: list[tuple[int, int]] = []
    pos = start
    while end - pos > target:
        cut = _cut_point(text, pos, pos + target)
        spans.append((pos, cut))
        nxt = _overlap_start(text, cut, overlap)
        pos = nxt if nxt > pos else cut
    spans.append((pos, end))
    return spans


def _cut_point(text: str, start: int, limit: int) -> int:
    """Prefer cutting at a newline, then a space, within the last 200 chars."""
    window_start = max(start, limit - 200)
    for sep in ("\n", " "):
        cut = text.rfind(sep, window_start, limit)
        if cut > start:
            return cut + 1
    return limit


def _overlap_start(text: str, end: int, overlap: int) -> int:
    """Start of the ~overlap-char tail before `end`, advanced to a word boundary.
    If no boundary exists within half the overlap (one giant token), keep the
    raw start — a mid-word overlap beats losing the overlap entirely."""
    start = max(0, end - overlap)
    probe = start
    while 0 < probe < end and not text[probe - 1].isspace():
        probe += 1
        if probe - start > overlap // 2:
            return start
    return probe
