"""Pin the chunker: it's the most-reused code in the project."""

from cortex.core.chunk import chunk, clean_markdown


def test_frontmatter_to_metadata():
    raw = "---\ntags: [railway, deploy]\ncreated: 2026-07-10\n---\n# Note\nBody text.\n"
    meta, text = clean_markdown(raw)
    assert meta["tags"] == ["railway", "deploy"]
    assert str(meta["created"]) == "2026-07-10"
    assert text.startswith("# Note")
    assert "tags" not in text


def test_malformed_frontmatter_stripped_but_no_metadata():
    raw = "---\nfoo: [a, b\nbar\n---\nBody.\n"
    meta, text = clean_markdown(raw)
    assert meta == {}
    assert text == "Body.\n"


def test_non_dict_frontmatter_stripped():
    raw = "---\n- just\n- a list\n---\nBody.\n"
    meta, text = clean_markdown(raw)
    assert meta == {}
    assert text == "Body.\n"


def test_no_frontmatter_untouched():
    raw = "# Note\n\nBody with --- a dash rule later.\n"
    meta, text = clean_markdown(raw)
    assert meta == {}
    assert text == raw


def test_wikilinks_and_embeds():
    raw = "See [[Railway Gotchas]] and [[Some Page|the alias]].\n![[diagram.png]]\nDone.\n"
    _, text = clean_markdown(raw)
    assert "Railway Gotchas" in text
    assert "the alias" in text
    assert "Some Page" not in text
    assert "diagram.png" not in text
    assert "[[" not in text and "]]" not in text


def test_short_text_single_chunk():
    text = "One paragraph.\n\nAnother one.\n"
    chunks = chunk(text)
    assert len(chunks) == 1
    assert chunks[0].seq == 0
    assert text[chunks[0].start : chunks[0].end] == chunks[0].text


def test_spans_roundtrip_and_overlap():
    text = "\n\n".join(f"Paragraph {i} " + "x" * 300 for i in range(10))
    chunks = chunk(text, target=1000, overlap=150)
    assert len(chunks) > 1
    for c in chunks:
        assert text[c.start : c.end] == c.text
        assert len(c.text) <= 1000
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start < prev.end  # overlap carried between consecutive chunks


def test_heading_is_hard_boundary():
    text = "# Section A\nshort a\n\n# Section B\nshort b\n"
    chunks = chunk(text)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("# Section A")
    assert chunks[1].text.startswith("# Section B")


def test_hash_inside_code_fence_is_not_heading():
    text = "# Real heading\npara\n\n```\n# just a comment\n```\nmore\n"
    assert len(chunk(text)) == 1


def test_oversized_paragraph_hard_split():
    text = "word " * 500  # one 2500-char "paragraph"
    chunks = chunk(text, target=1000, overlap=150)
    assert len(chunks) >= 3
    for c in chunks:
        assert text[c.start : c.end] == c.text
        assert len(c.text) <= 1000


def test_empty_and_frontmatter_only():
    assert chunk("") == []
    meta, text = clean_markdown("---\ntags: [a]\n---\n")
    assert meta == {"tags": ["a"]}
    assert chunk(text) == []
