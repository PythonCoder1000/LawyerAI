import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import WindowsPath
import threading
import json

from datetime import datetime

import openai
import utils
from extract_pdf import extract_notice
from utils import (
    ALL_FIELDS, AVAILABLE_MODELS, APP_VERSION,
    MODEL_PRICING, MODEL_DAILY_TOKEN_LIMITS,
)

FIELD_LABELS: dict[str, str] = {
    "case_name": "Case Name",
    "case_number": "Case Number",
    "court_name": "Court Name",
    "hearing_date": "Hearing Date",
    "hearing_time": "Hearing Time",
    "hearing_location": "Hearing Location",
    "motion_name": "Motion Name",
    "motion_summary": "Motion Summary",
}

SOURCE_COLORS: dict[str, str] = {
    "regex": "#2e7d32",
    "rule": "#1565c0",
    "llm": "#6a1b9a",
    "hybrid": "#e65100",
    "missing": "#b71c1c",
}


class UsageCostsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, history: list[dict]) -> None:
        super().__init__(parent)
        self.title("Usage & Costs")
        self.geometry("750x520")
        self.minsize(650, 400)
        self.configure(bg="#f5f5f5")
        self.transient(parent)
        self._history = history
        self._build_ui()

    def _build_ui(self) -> None:
        # --- History table ---
        header = tk.Label(
            self, text="Extraction History", font=("Segoe UI", 14, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        )
        header.pack(anchor=tk.W, padx=15, pady=(12, 4))

        table_frame = tk.Frame(self, bg="#f5f5f5", padx=15)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("time", "file", "model", "tokens", "cost")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree.heading("time", text="Time")
        self.tree.heading("file", text="File")
        self.tree.heading("model", text="Model")
        self.tree.heading("tokens", text="Tokens")
        self.tree.heading("cost", text="Cost")
        self.tree.column("time", width=80, anchor=tk.CENTER)
        self.tree.column("file", width=250, anchor=tk.W)
        self.tree.column("model", width=120, anchor=tk.CENTER)
        self.tree.column("tokens", width=100, anchor=tk.E)
        self.tree.column("cost", width=100, anchor=tk.E)

        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for entry in self._history:
            total_tok = entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
            self.tree.insert("", tk.END, values=(
                entry.get("time", ""),
                entry.get("file", ""),
                entry.get("model", ""),
                f"{total_tok:,}",
                f"${entry.get('cost', 0):.6f}",
            ))

        if not self._history:
            self.tree.insert("", tk.END, values=("", "No extractions yet", "", "", ""))

        # --- Per-model summary ---
        summary_label = tk.Label(
            self, text="Per-Model Usage", font=("Segoe UI", 14, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        )
        summary_label.pack(anchor=tk.W, padx=15, pady=(12, 4))

        summary_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=4)
        summary_frame.pack(fill=tk.X)

        # Aggregate per model
        model_stats: dict[str, dict] = {}
        for entry in self._history:
            m = entry.get("model", "unknown")
            if m not in model_stats:
                model_stats[m] = {"requests": 0, "tokens": 0, "cost": 0.0}
            model_stats[m]["requests"] += 1
            model_stats[m]["tokens"] += entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
            model_stats[m]["cost"] += entry.get("cost", 0)

        if model_stats:
            for model_name, stats in model_stats.items():
                row = tk.Frame(summary_frame, bg="#ffffff", relief=tk.SOLID, borderwidth=1, padx=10, pady=6)
                row.pack(fill=tk.X, pady=2)

                tk.Label(
                    row, text=model_name, font=("Segoe UI", 10, "bold"),
                    bg="#ffffff", fg="#1a237e", width=16, anchor=tk.W,
                ).pack(side=tk.LEFT)

                tk.Label(
                    row, text=f"{stats['requests']} requests", font=("Segoe UI", 9),
                    bg="#ffffff", fg="#424242",
                ).pack(side=tk.LEFT, padx=(0, 15))

                tk.Label(
                    row, text=f"{stats['tokens']:,} tokens", font=("Segoe UI", 9),
                    bg="#ffffff", fg="#424242",
                ).pack(side=tk.LEFT, padx=(0, 15))

                tk.Label(
                    row, text=f"${stats['cost']:.6f}", font=("Segoe UI", 9, "bold"),
                    bg="#ffffff", fg="#2e7d32",
                ).pack(side=tk.LEFT, padx=(0, 15))

                # Usage bar vs daily token limit
                daily_limit = MODEL_DAILY_TOKEN_LIMITS.get(model_name, 0)
                if daily_limit > 0:
                    pct = min(stats["tokens"] / daily_limit, 1.0)
                    bar_frame = tk.Frame(row, bg="#e0e0e0", height=12, width=120)
                    bar_frame.pack(side=tk.RIGHT, padx=(5, 0))
                    bar_frame.pack_propagate(False)
                    fill_color = "#2e7d32" if pct < 0.5 else "#e65100" if pct < 0.8 else "#b71c1c"
                    fill = tk.Frame(bar_frame, bg=fill_color, height=12, width=max(int(120 * pct), 1))
                    fill.place(x=0, y=0)
                    tk.Label(
                        row, text=f"{pct * 100:.1f}% of daily limit",
                        font=("Segoe UI", 8), bg="#ffffff", fg="#757575",
                    ).pack(side=tk.RIGHT)
        else:
            tk.Label(
                summary_frame, text="No usage data yet.", font=("Segoe UI", 10),
                bg="#f5f5f5", fg="#757575",
            ).pack(anchor=tk.W)

        # --- Total cost ---
        total_cost = sum(e.get("cost", 0) for e in self._history)
        total_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=10)
        total_frame.pack(fill=tk.X)
        tk.Label(
            total_frame, text=f"Total Session Cost: ${total_cost:.6f}",
            font=("Segoe UI", 12, "bold"), bg="#f5f5f5", fg="#1a237e",
        ).pack(side=tk.LEFT)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LawyerAI - Legal Notice Extractor")
        self.geometry("900x740")
        self.minsize(750, 600)
        self.configure(bg="#f5f5f5")
        self.pdf_path: WindowsPath | None = None
        self.usage_history: list[dict] = []
        self._check_api_key()
        self._build_ui()

    def _check_api_key(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            self.withdraw()
            messagebox.showwarning(
                "API Key Missing",
                "Please set your environment variable OPENAI_API_KEY in order to use this app!\n\n"
                "On Windows:\n"
                "1. Open Start and search for \"Environment Variables\"\n"
                "2. Click \"Edit the system environment variables\"\n"
                "3. Click \"Environment Variables\"\n"
                "4. Under User variables, click New\n"
                "5. Variable name: OPENAI_API_KEY\n"
                "6. Variable value: your API key\n\n"
                "Then restart the app.",
            )
            self.destroy()
            return

    def _on_model_change(self, _event: object) -> None:
        utils.OPENAI_MODEL = self.model_var.get()

    def _show_usage(self) -> None:
        UsageCostsWindow(self, self.usage_history)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About LawyerAI",
            f"LawyerAI - Legal Notice Extractor\n"
            f"Version {APP_VERSION}\n\n"
            f"Extracts structured case information from\n"
            f"court notice PDFs using regex parsing and\n"
            f"OpenAI language models.\n\n"
            f"Created by Christian Jin",
        )

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        usage_menu = tk.Menu(menubar, tearoff=0)
        usage_menu.add_command(label="View Usage & Costs", command=self._show_usage)
        menubar.add_cascade(label="Usage & Costs", menu=usage_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)

        top = tk.Frame(self, bg="#f5f5f5", pady=10, padx=15)
        top.pack(fill=tk.X)

        title = tk.Label(
            top, text="Legal Notice Extractor", font=("Segoe UI", 18, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        )
        title.pack(anchor=tk.W)

        subtitle = tk.Label(
            top, text="Upload a court notice PDF to extract case information",
            font=("Segoe UI", 10), bg="#f5f5f5", fg="#616161",
        )
        subtitle.pack(anchor=tk.W)

        model_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=5)
        model_frame.pack(fill=tk.X)

        tk.Label(
            model_frame, text="Model:", font=("Segoe UI", 10),
            bg="#f5f5f5", fg="#424242",
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.model_var = tk.StringVar(value=utils.OPENAI_MODEL)
        model_dropdown = ttk.Combobox(
            model_frame, textvariable=self.model_var,
            values=AVAILABLE_MODELS, state="readonly",
            font=("Segoe UI", 10), width=20,
        )
        model_dropdown.pack(side=tk.LEFT)
        model_dropdown.bind("<<ComboboxSelected>>", self._on_model_change)

        controls = tk.Frame(self, bg="#f5f5f5", padx=15, pady=5)
        controls.pack(fill=tk.X)

        self.file_label = tk.Label(
            controls, text="No file selected", font=("Segoe UI", 10),
            bg="#ffffff", fg="#757575", anchor=tk.W, padx=10, pady=8,
            relief=tk.SOLID, borderwidth=1,
        )
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.browse_btn = tk.Button(
            controls, text="Browse PDF", font=("Segoe UI", 10, "bold"),
            bg="#1565c0", fg="white", activebackground="#0d47a1",
            activeforeground="white", relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2", command=self._browse_file,
        )
        self.browse_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.extract_btn = tk.Button(
            controls, text="Extract", font=("Segoe UI", 10, "bold"),
            bg="#2e7d32", fg="white", activebackground="#1b5e20",
            activeforeground="white", relief=tk.FLAT, padx=20, pady=6,
            cursor="hand2", command=self._run_extraction, state=tk.DISABLED,
        )
        self.extract_btn.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            self, text="", font=("Segoe UI", 9), bg="#f5f5f5", fg="#616161",
        )
        self.status_label.pack(fill=tk.X, padx=15, pady=(5, 0))

        self.progress = ttk.Progressbar(self, mode="indeterminate", length=200)

        results_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=10)
        results_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(results_frame, bg="#f5f5f5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.results_container = tk.Frame(canvas, bg="#f5f5f5")

        self.results_container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=self.results_container, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self.field_widgets: dict[str, dict[str, tk.Label]] = {}
        self._build_field_cards()

        bottom = tk.Frame(self, bg="#f5f5f5", padx=15, pady=8)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)

        self.export_btn = tk.Button(
            bottom, text="Export JSON", font=("Segoe UI", 9),
            bg="#455a64", fg="white", activebackground="#37474f",
            activeforeground="white", relief=tk.FLAT, padx=15, pady=4,
            cursor="hand2", command=self._export_json, state=tk.DISABLED,
        )
        self.export_btn.pack(side=tk.RIGHT)

        self.cost_label = tk.Label(
            bottom, text="", font=("Segoe UI", 9), bg="#f5f5f5",
            fg="#455a64", anchor=tk.E,
        )
        self.cost_label.pack(side=tk.RIGHT, padx=(0, 15))

        self.warnings_label = tk.Label(
            bottom, text="", font=("Segoe UI", 9), bg="#f5f5f5",
            fg="#b71c1c", anchor=tk.W, wraplength=600, justify=tk.LEFT,
        )
        self.warnings_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.last_result: dict | None = None

    def _build_field_cards(self) -> None:
        for field in ALL_FIELDS:
            label_text = FIELD_LABELS.get(field, field)

            card = tk.Frame(
                self.results_container, bg="#ffffff", relief=tk.SOLID,
                borderwidth=1, padx=12, pady=8,
            )
            card.pack(fill=tk.X, pady=3, padx=2)

            header_frame = tk.Frame(card, bg="#ffffff")
            header_frame.pack(fill=tk.X)

            name_label = tk.Label(
                header_frame, text=label_text, font=("Segoe UI", 10, "bold"),
                bg="#ffffff", fg="#1a237e", anchor=tk.W,
            )
            name_label.pack(side=tk.LEFT)

            source_label = tk.Label(
                header_frame, text="", font=("Segoe UI", 8),
                bg="#ffffff", fg="#9e9e9e", anchor=tk.E,
            )
            source_label.pack(side=tk.RIGHT)

            confidence_label = tk.Label(
                header_frame, text="", font=("Segoe UI", 8),
                bg="#ffffff", fg="#9e9e9e", anchor=tk.E,
            )
            confidence_label.pack(side=tk.RIGHT, padx=(0, 10))

            value_label = tk.Label(
                card, text="--", font=("Segoe UI", 10),
                bg="#ffffff", fg="#424242", anchor=tk.W,
                wraplength=700, justify=tk.LEFT,
            )
            value_label.pack(fill=tk.X, pady=(4, 0))

            self.field_widgets[field] = { # type:ignore
                "value": value_label,
                "source": source_label,
                "confidence": confidence_label,
                "card": card,
            }

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a Legal Notice PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_path = WindowsPath(path)
            display_name = self.pdf_path.name
            if len(display_name) > 60:
                display_name = display_name[:57] + "..."
            self.file_label.configure(text=display_name, fg="#212121")
            self.extract_btn.configure(state=tk.NORMAL)
            self._reset_results()

    def _reset_results(self) -> None:
        for field in ALL_FIELDS:
            widgets = self.field_widgets[field]
            widgets["value"].configure(text="--", fg="#424242")
            widgets["source"].configure(text="")
            widgets["confidence"].configure(text="")
            widgets["card"].configure(bg="#ffffff")
            for w in widgets.values():
                if isinstance(w, tk.Label):
                    w.configure(bg="#ffffff")
        self.warnings_label.configure(text="")
        self.cost_label.configure(text="")
        self.last_result = None
        self.export_btn.configure(state=tk.DISABLED)

    def _set_loading(self, loading: bool) -> None:
        if loading:
            self.extract_btn.configure(state=tk.DISABLED, text="Extracting...")
            self.browse_btn.configure(state=tk.DISABLED)
            self.status_label.configure(text="Extracting fields from PDF... This may take a moment.")
            self.progress.pack(fill=tk.X, padx=15, pady=(2, 0))
            self.progress.start(15)
        else:
            self.extract_btn.configure(state=tk.NORMAL, text="Extract")
            self.browse_btn.configure(state=tk.NORMAL)
            self.status_label.configure(text="")
            self.progress.stop()
            self.progress.pack_forget()

    def _run_extraction(self) -> None:
        if not self.pdf_path:
            return
        self._reset_results()
        self._set_loading(True)
        thread = threading.Thread(target=self._extraction_worker, daemon=True)
        thread.start()

    def _extraction_worker(self) -> None:
        try:
            result = extract_notice(self.pdf_path)  # type: ignore
            self.after(0, self._display_results, result) # type:ignore
        except openai.AuthenticationError:
            self.after(0, self._display_error,
                    "Invalid API Key",
                    "Your OpenAI API key is invalid or expired.\n\n"
                    "Please check your OPENAI_API_KEY environment variable and restart the app.")
        except openai.RateLimitError:
            self.after(0, self._display_error,
                    "Rate Limit Exceeded",
                    "OpenAI rate limit reached and retries were exhausted.\n\n"
                    "Please wait a minute and try again.")
        except openai.APIConnectionError:
            self.after(0, self._display_error,
                    "Connection Error",
                    "Could not connect to OpenAI.\n\n"
                    "Please check your internet connection and try again.")
        except openai.APIStatusError as e:
            self.after(0, self._display_error,
                    "OpenAI API Error",
                    f"The OpenAI API returned an error (status {e.status_code}).\n\n"
                    "Please try again later.")
        except FileNotFoundError:
            self.after(0, self._display_error,
                    "File Not Found",
                    "The selected PDF file could not be found.\n\n"
                    "It may have been moved or deleted. Please select the file again.")
        except Exception as e:
            self.after(0, self._display_error,
                    "Unexpected Error",
                    f"Something went wrong during extraction:\n\n{e}")

    def _display_results(self, result: dict) -> None:
        self._set_loading(False)
        self.last_result = result

        for field in ALL_FIELDS:
            widgets = self.field_widgets[field]
            value = result.get(field)
            source = result.get("source", {}).get(field, "missing")
            confidence = result.get("confidence", {}).get(field, 0.0)

            if value:
                widgets["value"].configure(text=str(value), fg="#212121")
            else:
                widgets["value"].configure(text="Not found", fg="#b71c1c")

            source_color = SOURCE_COLORS.get(source, "#9e9e9e")
            widgets["source"].configure(text=source.upper(), fg=source_color)

            conf_pct = f"{confidence * 100:.0f}%"
            if confidence >= 0.75:
                conf_color = "#2e7d32"
            elif confidence >= 0.50:
                conf_color = "#e65100"
            else:
                conf_color = "#b71c1c"
            widgets["confidence"].configure(text=conf_pct, fg=conf_color)

        warnings = result.get("warnings", [])
        if warnings:
            warning_text = " | ".join(warnings[:5])
            if len(warnings) > 5:
                warning_text += f" (+{len(warnings) - 5} more)"
            self.warnings_label.configure(text=warning_text)

        cost = result.get("cost", 0.0)
        self.cost_label.configure(text=f"API Cost: ${cost:.6f}")

        filename = self.pdf_path.name if self.pdf_path else "unknown"
        self.usage_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "file": filename,
            "model": utils.OPENAI_MODEL,
            "cost": cost,
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
        })

        self.export_btn.configure(state=tk.NORMAL)

    def _display_error(self, title: str, message: str) -> None:
        self._set_loading(False)
        messagebox.showerror(title, message)

    def _export_json(self) -> None:
        if not self.last_result:
            return
        path = filedialog.asksaveasfilename(
            title="Save Extraction Results",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="extraction_result.json",
        )
        if path:
            export = {k: v for k, v in self.last_result.items() if k != "raw_text"}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Exported", f"Results saved to:\n{path}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
