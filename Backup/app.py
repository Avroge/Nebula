import sys
from pathlib import Path
import traceback

import io
import requests
from PIL import Image, ImageTk


def test():
    print("hello")


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("app.log")
    return Path(__file__).with_name("app.log")


def _excepthook(exc_type, exc, tb):
    _log_path().write_text(
        "".join(traceback.format_exception(exc_type, exc, tb)), encoding="utf-8"
    )


sys.excepthook = _excepthook

import tkinter as tk

from tkinter import ttk, messagebox
from notion_movies import (
    auto_add,
    auto_add_by_tmdb_id,
    mark_seen,
    list_movies,
    tmdb_search_suggestions,
    tmdb_poster_url,
)


class App(tk.Tk):

    def _on_mousewheel_suggestions(self, event):
        self.suggest_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def __init__(self):
        super().__init__()
        self.title("Notion Films (v2 suggestions)")
        self.geometry("720x520")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Titre du film :").grid(row=0, column=0, sticky="w")
        self.title_var = tk.StringVar()
        self.entry = ttk.Entry(frm, textvariable=self.title_var)
        self.entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.entry.focus()

        # --- Suggestions TMDB (scrollables) ---
        self._suggest_after_id = None
        self._suggestions = []
        self._poster_cache = {}

        self.suggest_container = ttk.Frame(frm)
        self.suggest_container.grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        self.suggest_container.grid_remove()

        self.suggest_canvas = tk.Canvas(
            self.suggest_container,
            height=220,
            highlightthickness=1,
        )
        self.suggest_scrollbar = ttk.Scrollbar(
            self.suggest_container,
            orient="vertical",
            command=self.suggest_canvas.yview,
        )
        self.suggest_inner = ttk.Frame(self.suggest_canvas)

        self.suggest_inner.bind(
            "<Configure>",
            lambda e: self.suggest_canvas.configure(
                scrollregion=self.suggest_canvas.bbox("all")
            ),
        )

        self._suggest_window = self.suggest_canvas.create_window(
            (0, 0), window=self.suggest_inner, anchor="nw"
        )

        self.suggest_canvas.bind(
            "<Configure>",
            lambda e: self.suggest_canvas.itemconfigure(
                self._suggest_window, width=e.width
            ),
        )

        self.suggest_canvas.configure(yscrollcommand=self.suggest_scrollbar.set)

        self.suggest_canvas.pack(side="left", fill="both", expand=True)
        self.suggest_scrollbar.pack(side="right", fill="y")

        self.suggest_canvas.bind("<MouseWheel>", self._on_mousewheel_suggestions)
        self.suggest_inner.bind("<MouseWheel>", self._on_mousewheel_suggestions)

        # événements
        self.entry.bind("<KeyRelease>", self.on_type)
        self.entry.bind("<Return>", self.on_enter)

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        btns.columnconfigure(2, weight=1)
        btns.columnconfigure(3, weight=1)

        ttk.Button(
            btns, text="Ajouter automatiquement (TMDB → Notion)", command=self.on_auto
        ).grid(row=0, column=0, sticky="ew", padx=4)

        ttk.Button(btns, text="Marquer comme Vu", command=self.on_seen).grid(
            row=0, column=1, sticky="ew", padx=4
        )

        ttk.Button(btns, text="Rafraîchir la liste", command=self.refresh).grid(
            row=0, column=2, sticky="ew", padx=4
        )

        ttk.Button(btns, text="Ajouter une liste", command=self.on_add_list).grid(
            row=0, column=3, sticky="ew", padx=4
        )

        ttk.Label(frm, text="Liste :").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.filter_var = tk.StringVar(value="")
        filter_row = ttk.Frame(frm)
        filter_row.grid(row=3, column=1, sticky="e", pady=(12, 0))
        ttk.Label(filter_row, text="Filtre statut :").pack(side="left")
        ttk.Entry(filter_row, width=14, textvariable=self.filter_var).pack(
            side="left", padx=(6, 0)
        )

        self.listbox = tk.Listbox(self, height=14)
        self.listbox.grid(row=4, column=0, sticky="nsew", padx=12, pady=12)

        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(self, textvariable=self.status).grid(
            row=5, column=0, sticky="ew", padx=12, pady=(0, 10)
        )

        self.refresh()

    def on_add_list(self):
        win = tk.Toplevel(self)
        win.title("Ajouter plusieurs films")

        ttk.Label(win, text="Colle une liste de titres (un par ligne)").pack(
            padx=10, pady=10
        )

        text = tk.Text(win, height=10, width=40)
        text.pack(padx=10, pady=10)

        def run_import():
            titles = text.get("1.0", tk.END).strip().split("\n")

            added = 0
            for t in titles:
                t = t.strip()
                if not t:
                    continue
                try:
                    auto_add(t)
                    added += 1
                except Exception:
                    pass

            self.status.set(f"{added} films ajoutés")
            self.refresh()
            win.destroy()

        ttk.Button(win, text="Importer", command=run_import).pack(pady=10)

    def selected_title(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        line = self.listbox.get(sel[0])
        # format: "Titre [Statut]"
        if " [" in line and line.endswith("]"):
            return line.rsplit(" [", 1)[0]
        return line

    def hide_suggestions(self):
        for child in self.suggest_inner.winfo_children():
            child.destroy()
        self.suggest_container.grid_remove()
        self._suggestions = []
        self._poster_cache = {}

    def _load_poster_image(self, poster_path: str | None):
        url = tmdb_poster_url(poster_path, size="w92")
        if not url:
            return None

        if url in self._poster_cache:
            return self._poster_cache[url]

        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content))
            img.thumbnail((60, 90))
            photo = ImageTk.PhotoImage(img)
            self._poster_cache[url] = photo
            return photo
        except Exception:
            return None

    def show_suggestions(self, items: list[dict]):
        self.hide_suggestions()
        self._suggestions = items

        if not items:
            return

        for idx, it in enumerate(items):
            row = ttk.Frame(self.suggest_inner)
            row.pack(fill="x", pady=2, padx=2)

            poster = self._load_poster_image(it.get("poster_path"))

            if poster:
                img_label = ttk.Label(row, image=poster)
                img_label.image = poster
                img_label.pack(side="left", padx=(0, 8))
            else:
                img_label = ttk.Label(row, text="[img]", width=8)
                img_label.pack(side="left", padx=(0, 8))

            y = f" ({it['year']})" if it.get("year") else ""
            text = f"{it['title']}{y}"

            btn = ttk.Button(
                row,
                text=text,
                command=lambda i=idx: self.pick_suggestion_index(i),
            )
            btn.pack(side="left", fill="x", expand=True)

        self.suggest_canvas.yview_moveto(0)
        self.suggest_container.grid()

    def pick_suggestion_index(self, idx: int):
        it = self._suggestions[idx]
        self.title_var.set(it["title"])
        self.hide_suggestions()

        try:
            self.status.set("Ajout en cours…")
            res = auto_add_by_tmdb_id(it["id"])
            plat = res["platform"] or "inconnue"
            self.status.set(f"Ajouté: {res['title']} | Plateforme: {plat}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

        self.entry.focus_set()

    def on_type(self, event=None):
        # debounce : on attend 300 ms après la frappe
        if self._suggest_after_id is not None:
            try:
                self.after_cancel(self._suggest_after_id)
            except Exception:
                pass
        self._suggest_after_id = self.after(300, self.refresh_suggestions)

    def refresh_suggestions(self):
        q = self.title_var.get().strip()
        if len(q) < 2:
            self.hide_suggestions()
            return
        try:
            items = tmdb_search_suggestions(q, limit=6)
            self.show_suggestions(items)
        except Exception as e:
            self.status.set(f"Suggestions TMDB: erreur ({e})")
            self.hide_suggestions()

    def on_enter(self, event=None):
        # Si une suggestion est visible, Enter choisit la sélection; sinon lance auto normal
        if self._suggestions and self.suggest_box.winfo_ismapped():
            return self.on_pick_suggestion()
        self.on_auto()
        return "break"

    def on_pick_suggestion(self, event=None):
        return "break"

        # Ajoute en utilisant l'ID TMDB (pas d’ambiguïté)
        try:
            self.status.set("Ajout en cours…")
            res = auto_add_by_tmdb_id(it["id"])
            plat = res["platform"] or "inconnue"
            self.status.set(f"Ajouté: {res['title']} | Plateforme: {plat}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

        self.entry.focus_set()
        return "break"

    def on_auto(self):
        self.hide_suggestions()
        title = self.title_var.get().strip()
        if not title:
            messagebox.showinfo("Info", "Entre un titre.")
            return
        try:
            self.status.set("Ajout en cours…")
            res = auto_add(title)
            plat = res["platform"] or "inconnue"
            self.status.set(f"Ajouté: {res['title']} | Plateforme: {plat}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def on_seen(self):
        title = self.title_var.get().strip() or self.selected_title()
        if not title:
            messagebox.showinfo(
                "Info", "Entre un titre ou sélectionne un film dans la liste."
            )
            return
        try:
            self.status.set("Mise à jour…")
            mark_seen(title)
            self.status.set(f"Marqué comme Vu: {title}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def refresh(self):
        try:
            self.listbox.delete(0, tk.END)
            filt = self.filter_var.get().strip() or None
            for t, s in list_movies(status=filt, limit=100):
                self.listbox.insert(tk.END, f"{t} [{s}]")
            self.status.set("Liste mise à jour.")
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))


if __name__ == "__main__":
    App().mainloop()
