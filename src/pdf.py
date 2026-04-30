import pymupdf
import pymupdf4llm
from typing import BinaryIO


def extract_text(file: BinaryIO) -> list[dict]:
    document = pymupdf.open(stream=file.read(), filetype="pdf")
    return pymupdf4llm.to_markdown(document)
