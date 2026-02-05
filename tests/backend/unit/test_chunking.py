from app.services.ingestion import chunk_markdown


def test_chunk_markdown_splits_on_paragraphs():
    text = "# Title\n\nPara one.\n\nPara two.\n\nPara three."
    chunks = chunk_markdown(text, max_chars=20, overlap=0)
    assert len(chunks) >= 2
    assert chunks[0].content
    assert chunks[0].chunk_index == 0


def test_chunk_markdown_overlap():
    text = "# Title\n\nParagraph one.\n\nParagraph two."
    chunks = chunk_markdown(text, max_chars=30, overlap=5)
    assert len(chunks) >= 2
    assert chunks[1].content.startswith(chunks[0].content[-5:])
