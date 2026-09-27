"""Offline bounded PDF extraction in a short-lived process. No filenames or text in errors."""

import io
import json
import logging
import sys

from skillcoach.documents import MAX_FILE, MAX_TEXT


def extract_pdf(raw):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(raw) > MAX_FILE or not raw.startswith(b"%PDF-"):
        return {"error": "invalid_pdf"}
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return {"error": "encrypted_pdf"}
        if not 1 <= len(reader.pages) <= 15:
            return {"error": "pdf_page_limit"}
        texts, total = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            total += len(text) + 1
            if total > MAX_TEXT:
                return {"error": "document_text_limit"}
            texts.append(text)
        text = "\n".join(texts).strip()
        if not text:
            return {"error": "pdf_has_no_text"}
        return {"text": text}
    except (
        PdfReadError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
        MemoryError,
        NotImplementedError,
    ):
        return {"error": "pdf_parse_failed"}


def main():
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    logging.disable(logging.CRITICAL)
    result = extract_pdf(sys.stdin.buffer.read(MAX_FILE + 1))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
