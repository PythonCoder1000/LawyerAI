import fitz
import tkinter as tk
from tkinter import filedialog
from pathlib import WindowsPath
from typing import TypedDict


class PageData(TypedDict):
    page_num: int
    text: str


class PagesResult(TypedDict):
    pages: list[PageData]


def open_pdf() -> WindowsPath:
    root = tk.Tk()
    root.withdraw()

    filename = filedialog.askopenfilename(
        title="Choose a PDF",
        filetypes=(("PDF files", "*.pdf"), ("All files", "*.*"))
    )

    return WindowsPath(filename)


def extract_text_by_page(path: WindowsPath) -> PagesResult:
    document = fitz.open(path)
    try:
        pages: list[PageData] = []
        for i in range(len(document)):
            page = document[i]
            page_text: str = str(page.get_text("text", sort=True))
            entry: PageData = {
                "page_num": i + 1,
                "text": page_text,
            }
            pages.append(entry)
        return {"pages": pages}
    finally:
        document.close()
