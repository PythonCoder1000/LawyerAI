import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from pathlib import WindowsPath
import threading
import json
import time as _time

from datetime import datetime

import openai
import utils
from extract_pdf import extract_notice, set_api_key, reset_api_key
from utils import ALL_FIELDS, AVAILABLE_MODELS, APP_VERSION

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
    def __init__(self, parent: "App", history: list[dict]) -> None:
        super().__init__(parent)
        self.title("Usage & Costs")
        self.geometry("800x560")
        self.minsize(700, 450)
        self.configure(bg="#f5f5f5")
        self.transient(parent)
        self._parent = parent
        self._history = history
        self._build_ui()

    def _build_ui(self) -> None:
        # --- History table ---
        hist_header = tk.Frame(self, bg="#f5f5f5")
        hist_header.pack(fill=tk.X, padx=15, pady=(12, 4))

        tk.Label(
            hist_header, text="Extraction History", font=("Segoe UI", 14, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        ).pack(side=tk.LEFT)

        clear_btn = tk.Button(
            hist_header, text="Clear History", font=("Segoe UI", 9),
            bg="#b71c1c", fg="white", activebackground="#8b0000",
            activeforeground="white", relief=tk.FLAT, padx=10, pady=2,
            cursor="hand2", command=self._clear_history,
        )
        clear_btn.pack(side=tk.RIGHT)

        table_frame = tk.Frame(self, bg="#f5f5f5", padx=15)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("time", "file", "model", "tokens", "cost", "elapsed")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        self.tree.heading("time", text="Time")
        self.tree.heading("file", text="File")
        self.tree.heading("model", text="Model")
        self.tree.heading("tokens", text="Tokens")
        self.tree.heading("cost", text="Cost")
        self.tree.heading("elapsed", text="Duration")
        self.tree.column("time", width=70, anchor=tk.CENTER)
        self.tree.column("file", width=220, anchor=tk.W)
        self.tree.column("model", width=110, anchor=tk.CENTER)
        self.tree.column("tokens", width=90, anchor=tk.E)
        self.tree.column("cost", width=90, anchor=tk.E)
        self.tree.column("elapsed", width=80, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._populate_table()

        # --- Rate Limits (live from API) ---
        tk.Label(
            self, text="Rate Limits (from OpenAI API)", font=("Segoe UI", 14, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        ).pack(anchor=tk.W, padx=15, pady=(12, 4))

        limits_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=4)
        limits_frame.pack(fill=tk.X)

        live_limits = utils.model_rate_limits
        if live_limits:
            for model_name, limits in live_limits.items():
                row = tk.Frame(limits_frame, bg="#ffffff", relief=tk.SOLID, borderwidth=1, padx=10, pady=6)
                row.pack(fill=tk.X, pady=2)

                tk.Label(
                    row, text=model_name, font=("Segoe UI", 10, "bold"),
                    bg="#ffffff", fg="#1a237e", width=14, anchor=tk.W,
                ).pack(side=tk.LEFT)

                limit_rpm = limits.get("limit_requests", 0)
                remain_rpm = limits.get("remaining_requests", 0)
                limit_tpm = limits.get("limit_tokens", 0)
                remain_tpm = limits.get("remaining_tokens", 0)

                tk.Label(
                    row, text=f"RPM: {remain_rpm}/{limit_rpm}",
                    font=("Segoe UI", 9), bg="#ffffff", fg="#424242",
                ).pack(side=tk.LEFT, padx=(0, 15))

                tk.Label(
                    row, text=f"TPM: {remain_tpm:,}/{limit_tpm:,}",
                    font=("Segoe UI", 9), bg="#ffffff", fg="#424242",
                ).pack(side=tk.LEFT, padx=(0, 15))

                # TPM usage bar
                if limit_tpm > 0:
                    used_pct = min((limit_tpm - remain_tpm) / limit_tpm, 1.0)
                    bar_frame = tk.Frame(row, bg="#e0e0e0", height=12, width=120)
                    bar_frame.pack(side=tk.RIGHT, padx=(5, 0))
                    bar_frame.pack_propagate(False)
                    fill_color = "#2e7d32" if used_pct < 0.5 else "#e65100" if used_pct < 0.8 else "#b71c1c"
                    fill = tk.Frame(bar_frame, bg=fill_color, height=12, width=max(int(120 * used_pct), 1))
                    fill.place(x=0, y=0)
                    tk.Label(
                        row, text=f"{used_pct * 100:.0f}% used",
                        font=("Segoe UI", 8), bg="#ffffff", fg="#757575",
                    ).pack(side=tk.RIGHT)
        else:
            tk.Label(
                limits_frame, text="No rate limit data yet. Run an extraction first.",
                font=("Segoe UI", 10), bg="#f5f5f5", fg="#757575",
            ).pack(anchor=tk.W)

        # --- Per-model cost summary ---
        tk.Label(
            self, text="Session Cost Summary", font=("Segoe UI", 14, "bold"),
            bg="#f5f5f5", fg="#1a237e",
        ).pack(anchor=tk.W, padx=15, pady=(12, 4))

        summary_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=4)
        summary_frame.pack(fill=tk.X)

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
                row = tk.Frame(summary_frame, bg="#ffffff", relief=tk.SOLID, borderwidth=1, padx=10, pady=4)
                row.pack(fill=tk.X, pady=1)
                tk.Label(row, text=model_name, font=("Segoe UI", 9, "bold"),
                         bg="#ffffff", fg="#1a237e", width=14, anchor=tk.W).pack(side=tk.LEFT)
                tk.Label(row, text=f"{stats['requests']} req", font=("Segoe UI", 9),
                         bg="#ffffff", fg="#424242").pack(side=tk.LEFT, padx=(0, 10))
                tk.Label(row, text=f"{stats['tokens']:,} tok", font=("Segoe UI", 9),
                         bg="#ffffff", fg="#424242").pack(side=tk.LEFT, padx=(0, 10))
                tk.Label(row, text=f"${stats['cost']:.6f}", font=("Segoe UI", 9, "bold"),
                         bg="#ffffff", fg="#2e7d32").pack(side=tk.LEFT)
        else:
            tk.Label(summary_frame, text="No usage data yet.", font=("Segoe UI", 10),
                     bg="#f5f5f5", fg="#757575").pack(anchor=tk.W)

        # --- Total cost ---
        total_cost = sum(e.get("cost", 0) for e in self._history)
        total_frame = tk.Frame(self, bg="#f5f5f5", padx=15, pady=10)
        total_frame.pack(fill=tk.X)
        tk.Label(
            total_frame, text=f"Total Session Cost: ${total_cost:.6f}",
            font=("Segoe UI", 12, "bold"), bg="#f5f5f5", fg="#1a237e",
        ).pack(side=tk.LEFT)
        tk.Label(
            total_frame, text=f"{len(self._history)} extraction(s)",
            font=("Segoe UI", 10), bg="#f5f5f5", fg="#616161",
        ).pack(side=tk.RIGHT)

    def _populate_table(self) -> None:
        for entry in self._history:
            total_tok = entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
            self.tree.insert("", tk.END, values=(
                entry.get("time", ""),
                entry.get("file", ""),
                entry.get("model", ""),
                f"{total_tok:,}",
                f"${entry.get('cost', 0):.6f}",
                entry.get("elapsed", ""),
            ))
        if not self._history:
            self.tree.insert("", tk.END, values=("", "No extractions yet", "", "", "", ""))

    def _clear_history(self) -> None:
        if not self._history:
            return
        if messagebox.askyesno("Clear History", "Clear all extraction history for this session?", parent=self):
            self._history.clear()
            utils.model_rate_limits.clear()
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.tree.insert("", tk.END, values=("", "No extractions yet", "", "", "", ""))
            self._parent._update_title()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LawyerAI - Legal Notice Extractor")
        self.geometry("900x740")
        self.minsize(750, 600)
        self.configure(bg="#f5f5f5")
        self.pdf_path: WindowsPath | None = None
        self.usage_history: list[dict] = []
        self._extraction_count: int = 0
        self._extract_start: float = 0.0
        self._key_source = tk.StringVar(value="key.txt")
        self._key_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.txt")
        self._check_api_key()
        self._build_ui()
        self._bind_shortcuts()

    def _check_api_key(self) -> None:
        # 1. Try key.txt in the same directory as this script
        if os.path.isfile(self._key_file_path):
            with open(self._key_file_path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if key:
                set_api_key(key)
                self._key_source.set("key.txt")
                return
        # 2. Fall back to environment variable
        if os.environ.get("OPENAI_API_KEY"):
            self._key_source.set("env")
            return
        # 3. No key found
        self.withdraw()
        messagebox.showwarning(
            "API Key Missing",
            "No OpenAI API key found.\n\n"
            "Paste your key into key.txt (in the code folder),\n"
            "or set the OPENAI_API_KEY environment variable.\n\n"
            "Then restart the app.",
        )
        self.destroy()
        return

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-o>", lambda _e: self._browse_file())
        self.bind("<Control-e>", lambda _e: self._run_extraction())
        self.bind("<Control-u>", lambda _e: self._show_usage())
        self.bind("<Control-s>", lambda _e: self._export_json())

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
            f"Keyboard Shortcuts:\n"
            f"  Ctrl+O  Browse PDF\n"
            f"  Ctrl+E  Extract\n"
            f"  Ctrl+U  Usage & Costs\n"
            f"  Ctrl+S  Export JSON\n\n"
            f"Created by Christian Jin",
        )

    def _update_title(self) -> None:
        base = "LawyerAI - Legal Notice Extractor"
        if self._extraction_count > 0:
            self.title(f"{base}  [{self._extraction_count} extraction(s)]")
        else:
            self.title(base)

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        usage_menu = tk.Menu(menubar, tearoff=0)
        usage_menu.add_command(label="View Usage & Costs", command=self._show_usage, accelerator="Ctrl+U")
        menubar.add_cascade(label="Usage & Costs", menu=usage_menu)
        exp_menu = tk.Menu(menubar, tearoff=0)
        exp_menu.add_command(
            label="Trigger: Auth Error",
            command=lambda: self._trigger_test_error(
                "Invalid API Key",
                "Your OpenAI API key is invalid or expired.\n\n"
                "Please check your key in key.txt and restart the app.",
            ),
        )
        exp_menu.add_command(
            label="Trigger: Rate Limit",
            command=lambda: self._trigger_test_error(
                "Rate Limit Exceeded",
                "OpenAI rate limit reached and retries were exhausted.\n\n"
                "Please wait a minute and try again.",
            ),
        )
        exp_menu.add_command(
            label="Trigger: Connection Error",
            command=lambda: self._trigger_test_error(
                "Connection Error",
                "Could not connect to OpenAI.\n\n"
                "Please check your internet connection and try again.",
            ),
        )
        exp_menu.add_command(
            label="Trigger: API Error (500)",
            command=lambda: self._trigger_test_error(
                "OpenAI API Error",
                "The OpenAI API returned an error (status 500).\n\n"
                "Please try again later.",
            ),
        )
        exp_menu.add_command(
            label="Trigger: File Not Found",
            command=lambda: self._trigger_test_error(
                "File Not Found",
                "The selected PDF file could not be found.\n\n"
                "It may have been moved or deleted. Please select the file again.",
            ),
        )
        exp_menu.add_command(
            label="Trigger: Unexpected Error",
            command=lambda: self._trigger_test_error(
                "Unexpected Error",
                "Something went wrong during extraction:\n\nZeroDivisionError: division by zero",
            ),
        )
        exp_menu.add_separator()
        exp_menu.add_radiobutton(
            label="Use key.txt",
            variable=self._key_source, value="key.txt",
            command=self._switch_key_source,
        )
        exp_menu.add_radiobutton(
            label="Use Environment Variable",
            variable=self._key_source, value="env",
            command=self._switch_key_source,
        )
        menubar.add_cascade(label="Experimental", menu=exp_menu)
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

        self.elapsed_label = tk.Label(
            bottom, text="", font=("Segoe UI", 9), bg="#f5f5f5",
            fg="#455a64", anchor=tk.E,
        )
        self.elapsed_label.pack(side=tk.RIGHT, padx=(0, 10))

        self.warnings_label = tk.Label(
            bottom, text="", font=("Segoe UI", 9), bg="#f5f5f5",
            fg="#b71c1c", anchor=tk.W, wraplength=500, justify=tk.LEFT,
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
                wraplength=700, justify=tk.LEFT, cursor="hand2",
            )
            value_label.pack(fill=tk.X, pady=(4, 0))

            # Right-click to copy value
            value_label.bind("<Button-3>", lambda _e, f=field: self._copy_field(f))
            # Tooltip on hover
            value_label.bind("<Enter>", lambda _e, lbl=value_label: lbl.configure(fg="#1565c0"))
            value_label.bind("<Leave>", lambda _e, lbl=value_label, f=field: lbl.configure(
                fg="#212121" if self.last_result and self.last_result.get(f) else "#b71c1c"
            ))

            self.field_widgets[field] = { # type:ignore
                "value": value_label,
                "source": source_label,
                "confidence": confidence_label,
                "card": card,
            }

    def _copy_field(self, field: str) -> None:
        if not self.last_result:
            return
        value = self.last_result.get(field)
        if value:
            self.clipboard_clear()
            self.clipboard_append(str(value))
            self.status_label.configure(text=f"Copied {FIELD_LABELS.get(field, field)} to clipboard")
            self.after(2000, lambda: self.status_label.configure(text=""))

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
        self.elapsed_label.configure(text="")
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

    def _switch_key_source(self) -> None:
        source = self._key_source.get()
        if source == "key.txt":
            if not os.path.isfile(self._key_file_path):
                messagebox.showwarning("key.txt Not Found", "key.txt was not found in the code folder.")
                self._key_source.set("env")
                return
            with open(self._key_file_path, "r", encoding="utf-8") as f:
                key = f.read().strip()
            if not key:
                messagebox.showwarning("Empty Key", "key.txt is empty. Please paste your API key into it.")
                self._key_source.set("env")
                return
            set_api_key(key)
            self.status_label.configure(text="Switched to key.txt")
        else:
            if not os.environ.get("OPENAI_API_KEY"):
                messagebox.showwarning("No Env Variable", "OPENAI_API_KEY environment variable is not set.")
                self._key_source.set("key.txt")
                return
            reset_api_key()
            self.status_label.configure(text="Switched to environment variable")
        self.after(3000, lambda: self.status_label.configure(text=""))

    def _trigger_test_error(self, title: str, message: str) -> None:
        """Simulate the full loading-then-error flow for testing."""
        self._reset_results()
        self._set_loading(True)

        def worker() -> None:
            _time.sleep(1)
            self.after(0, self._display_error, title, message)

        threading.Thread(target=worker, daemon=True).start()

    def _run_extraction(self) -> None:
        if not self.pdf_path:
            return
        self._reset_results()
        self._set_loading(True)
        self._extract_start = _time.monotonic()
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
                    "Please check your key in key.txt and restart the app.")
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

        elapsed = _time.monotonic() - self._extract_start
        elapsed_str = f"{elapsed:.1f}s"

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
        self.elapsed_label.configure(text=elapsed_str)

        filename = self.pdf_path.name if self.pdf_path else "unknown"
        self.usage_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "file": filename,
            "model": utils.OPENAI_MODEL,
            "cost": cost,
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "elapsed": elapsed_str,
        })

        self._extraction_count += 1
        self._update_title()
        self.export_btn.configure(state=tk.NORMAL)

        # Show rate limits in status briefly
        live = utils.model_rate_limits.get(utils.OPENAI_MODEL, {})
        if live:
            remain_rpm = live.get("remaining_requests", 0)
            limit_rpm = live.get("limit_requests", 0)
            remain_tpm = live.get("remaining_tokens", 0)
            limit_tpm = live.get("limit_tokens", 0)
            self.status_label.configure(
                text=f"Done in {elapsed_str}  |  RPM: {remain_rpm}/{limit_rpm}  |  TPM: {remain_tpm:,}/{limit_tpm:,}"
            )
            self.after(8000, lambda: self.status_label.configure(text=""))

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
