"""Verify that the saved example notice contains searchable text."""

from pathlib import Path

from pypdf import PdfReader


NOTICE_PATH = Path("data/notices/FY27_ASNCompetitiveNotice_Final.508.pdf")


def main() -> None:
    reader = PdfReader(NOTICE_PATH)
    texts = [page.extract_text() or "" for page in reader.pages]
    combined = "\n".join(texts).casefold()
    print(f"{NOTICE_PATH}: {len(reader.pages)} pages, {len(combined)} text characters")
    for phrase in ("eligibility", "deadline", "state commission"):
        pages = [index + 1 for index, text in enumerate(texts) if phrase in text.casefold()]
        print(f"{phrase}: pages {pages[:10]}")


if __name__ == "__main__":
    main()
