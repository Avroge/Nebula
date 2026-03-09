import sys
from pathlib import Path
import traceback
import io
import hashlib
import json
import threading
import requests
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox

from pathlib import Path
import sys


def resource_path(filename: str) -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).with_name(filename))
    return str(Path(__file__).with_name(filename))


from notion_movies import (
    auto_add,
    auto_add_by_tmdb_id,
    mark_seen,
    update_status,
    delete_movie,
    list_movies_detailed,
    tmdb_search_suggestions,
    tmdb_poster_url,
    tmdb_movie_details,
)


def _log_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("app.log")
    return Path(__file__).with_name("app.log")


def _excepthook(exc_type, exc, tb):
    _log_path().write_text(
        "".join(traceback.format_exception(exc_type, exc, tb)),
        encoding="utf-8",
    )


sys.excepthook = _excepthook


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Nébula")
        self.geometry("980x760")

        try:
            self.iconbitmap(resource_path("nebula.ico"))
        except Exception as e:
            print("Impossible de charger l'icône :", e)

        self._suggest_after_id = None
        self._suggestions = []
        self._poster_cache = {}
        self.selected_movie = None
        self.current_movies = []
        self._load_queue_after_id = None
        self._resize_after_id = None
        self._last_gallery_columns = None
        self._suggest_request_id = 0
        self._suggest_loading = False
        self._last_suggest_query = ""

        self.sort_dir_var = tk.StringVar(value="Décroissant")
        self.status_change_var = tk.StringVar(value="À voir")
        self.library_search_var = tk.StringVar(value="")

        self._disk_cache_dir = self._get_disk_cache_dir()
        self._disk_cache_dir.mkdir(parents=True, exist_ok=True)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(4, weight=1)

        # =========================
        # Recherche
        # =========================
        ttk.Label(frm, text="Titre du film :").grid(row=0, column=0, sticky="w")

        self.title_var = tk.StringVar()
        self.entry = ttk.Entry(frm, textvariable=self.title_var)
        self.entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.entry.focus()

        # =========================
        # Suggestions TMDB
        # =========================
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
            (0, 0),
            window=self.suggest_inner,
            anchor="nw",
        )

        self.suggest_canvas.bind(
            "<Configure>",
            lambda e: self.suggest_canvas.itemconfigure(
                self._suggest_window,
                width=e.width,
            ),
        )

        self.suggest_canvas.configure(yscrollcommand=self.suggest_scrollbar.set)

        self.suggest_canvas.pack(side="left", fill="both", expand=True)
        self.suggest_scrollbar.pack(side="right", fill="y")

        self.suggest_canvas.bind("<MouseWheel>", self._on_mousewheel_suggestions)
        self.suggest_inner.bind("<MouseWheel>", self._on_mousewheel_suggestions)

        self.entry.bind("<KeyRelease>", self.on_type)
        self.entry.bind("<Return>", self.on_enter)

        # =========================
        # Boutons
        # =========================
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for i in range(4):
            btns.columnconfigure(i, weight=1)

        ttk.Button(
            btns,
            text="Ajouter automatiquement (TMDB → Notion)",
            command=self.on_auto,
        ).grid(row=0, column=0, sticky="ew", padx=4)

        ttk.Button(
            btns,
            text="Marquer comme Vu",
            command=self.on_seen,
        ).grid(row=0, column=1, sticky="ew", padx=4)

        ttk.Button(
            btns,
            text="Rafraîchir la liste",
            command=self.refresh,
        ).grid(row=0, column=2, sticky="ew", padx=4)

        ttk.Button(
            btns,
            text="Ajouter une liste",
            command=self.on_add_list,
        ).grid(row=0, column=3, sticky="ew", padx=4)

        # =========================
        # Filtres / tri / vue / actions
        # =========================
        top_controls = ttk.Frame(frm)
        top_controls.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        top_controls.columnconfigure(0, weight=1)
        top_controls.columnconfigure(1, weight=1)

        # --- Ligne 1
        top_row_1 = ttk.Frame(top_controls)
        top_row_1.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        top_row_1.columnconfigure(0, weight=1)
        top_row_1.columnconfigure(1, weight=1)

        left_controls = ttk.Frame(top_row_1)
        left_controls.grid(row=0, column=0, sticky="w")

        ttk.Label(left_controls, text="Recherche dans ma liste :").pack(side="left")
        library_search_entry = ttk.Entry(
            left_controls,
            width=18,
            textvariable=self.library_search_var,
        )
        library_search_entry.pack(side="left", padx=(6, 12))
        library_search_entry.bind("<KeyRelease>", lambda e: self.refresh())

        ttk.Label(left_controls, text="Filtre statut :").pack(side="left")
        self.filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(left_controls, width=12, textvariable=self.filter_var)
        filter_entry.pack(side="left", padx=(6, 0))
        filter_entry.bind("<Return>", lambda e: self.refresh())

        middle_controls = ttk.Frame(top_row_1)
        middle_controls.grid(row=0, column=1, sticky="e")

        ttk.Label(middle_controls, text="Trier par :").pack(side="left")
        self.sort_var = tk.StringVar(value="Titre")
        sort_combo = ttk.Combobox(
            middle_controls,
            textvariable=self.sort_var,
            values=["Titre", "Année", "Note"],
            width=10,
            state="readonly",
        )
        sort_combo.pack(side="left", padx=(6, 6))
        sort_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        self.sort_dir_combo = ttk.Combobox(
            middle_controls,
            textvariable=self.sort_dir_var,
            values=["Croissant", "Décroissant"],
            width=12,
            state="readonly",
        )
        self.sort_dir_combo.pack(side="left", padx=(0, 0))
        self.sort_dir_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        # --- Ligne 2
        top_row_2 = ttk.Frame(top_controls)
        top_row_2.grid(row=1, column=0, columnspan=2, sticky="ew")
        top_row_2.columnconfigure(0, weight=1)
        top_row_2.columnconfigure(1, weight=1)

        view_controls = ttk.Frame(top_row_2)
        view_controls.grid(row=0, column=0, sticky="w")

        ttk.Label(view_controls, text="Vue :").pack(side="left")
        self.view_var = tk.StringVar(value="Liste")
        view_combo = ttk.Combobox(
            view_controls,
            textvariable=self.view_var,
            values=["Liste", "Galerie"],
            width=10,
            state="readonly",
        )
        view_combo.pack(side="left", padx=(6, 12))
        view_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(view_controls, text="Taille des films :").pack(side="left")
        self.movie_size_var = tk.StringVar(value="Grand")
        size_combo = ttk.Combobox(
            view_controls,
            textvariable=self.movie_size_var,
            values=["Très grand", "Grand", "Moyen", "Petit", "Très petit"],
            width=12,
            state="readonly",
        )
        size_combo.pack(side="left", padx=(6, 0))
        size_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        right_controls = ttk.Frame(top_row_2)
        right_controls.grid(row=0, column=1, sticky="e")

        ttk.Label(right_controls, text="Nouveau statut :").pack(side="left")
        self.status_combo = ttk.Combobox(
            right_controls,
            textvariable=self.status_change_var,
            values=["À voir", "Vu", "À revoir", "En cours"],
            width=10,
            state="readonly",
        )
        self.status_combo.pack(side="left", padx=(6, 6))

        ttk.Button(
            right_controls,
            text="Changer statut",
            command=self.on_change_status,
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            right_controls,
            text="Supprimer",
            command=self.on_delete_movie,
        ).pack(side="left")

        # =========================
        # Zone principale scrollable
        # =========================
        self.movies_container = ttk.Frame(frm)
        self.movies_container.grid(
            row=4, column=0, columnspan=2, sticky="nsew", pady=12
        )
        self.movies_container.columnconfigure(0, weight=1)
        self.movies_container.rowconfigure(0, weight=1)

        self.movies_canvas = tk.Canvas(self.movies_container, highlightthickness=1)
        self.movies_scrollbar = ttk.Scrollbar(
            self.movies_container,
            orient="vertical",
            command=self.movies_canvas.yview,
        )

        self.movies_inner = ttk.Frame(self.movies_canvas)

        self.movies_inner.bind(
            "<Configure>",
            lambda e: self.movies_canvas.configure(
                scrollregion=self.movies_canvas.bbox("all")
            ),
        )

        self._movies_window = self.movies_canvas.create_window(
            (0, 0),
            window=self.movies_inner,
            anchor="nw",
        )

        self.movies_canvas.bind(
            "<Configure>",
            lambda e: self.movies_canvas.itemconfigure(
                self._movies_window,
                width=e.width,
            ),
        )

        self.movies_canvas.bind("<Configure>", self._on_movies_canvas_resize, add="+")

        self.movies_canvas.configure(yscrollcommand=self.movies_scrollbar.set)

        self.movies_canvas.grid(row=0, column=0, sticky="nsew")
        self.movies_scrollbar.grid(row=0, column=1, sticky="ns")

        self.movies_canvas.bind("<MouseWheel>", self._on_mousewheel_movies)
        self.movies_inner.bind("<MouseWheel>", self._on_mousewheel_movies)

        # =========================
        # Statut
        # =========================
        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(frm, textvariable=self.status).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )

        self.movie_menu = tk.Menu(self, tearoff=0)
        self.movie_menu.add_command(
            label="Marquer comme À voir",
            command=lambda: self._change_status_to("À voir"),
        )
        self.movie_menu.add_command(
            label="Marquer comme Vu",
            command=lambda: self._change_status_to("Vu"),
        )
        self.movie_menu.add_command(
            label="Marquer comme À revoir",
            command=lambda: self._change_status_to("Vu"),
        )
        self.movie_menu.add_command(
            label="Marquer comme En cours",
            command=lambda: self._change_status_to("Vu"),
        )
        self.movie_menu.add_separator()
        self.movie_menu.add_command(
            label="Supprimer",
            command=self.on_delete_movie,
        )

        settings = self._load_settings()
        self._apply_loaded_settings(settings)

        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

        self.refresh()

    # =========================
    # Scroll
    # =========================
    def _on_mousewheel_suggestions(self, event):
        self.suggest_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _on_mousewheel_movies(self, event):
        self.movies_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_mousewheel_recursive(self, widget, handler):
        widget.bind("<MouseWheel>", handler)

        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, handler)

    # =========================
    # Images
    # =========================
    def _get_disk_cache_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).with_name("poster_cache")
        return Path(__file__).with_name("poster_cache")

    def _get_disk_cache_file(self, url: str) -> Path:
        suffix = Path(url.split("?")[0]).suffix or ".img"
        name = hashlib.sha1(url.encode("utf-8")).hexdigest() + suffix
        return self._disk_cache_dir / name

    def _load_image_from_url(self, url: str | None, size=(140, 210)):
        if not url:
            return None

        cache_key = f"{url}|{size[0]}x{size[1]}"
        if cache_key in self._poster_cache:
            return self._poster_cache[cache_key]

        cache_file = self._get_disk_cache_file(url)

        try:
            if cache_file.exists():
                img = Image.open(cache_file).convert("RGB")
            else:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                cache_file.write_bytes(r.content)
                img = Image.open(io.BytesIO(r.content)).convert("RGB")

            img = img.resize(size, Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(img, master=self)
            self._poster_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def _load_suggestion_poster(self, poster_path: str | None):
        url = tmdb_poster_url(poster_path, size="w92")
        if not url:
            return None

        if url in self._poster_cache:
            return self._poster_cache[url]

        return None

    # =========================
    # Suggestions
    # =========================
    def hide_suggestions(self):
        for child in self.suggest_inner.winfo_children():
            child.destroy()

        self.suggest_container.grid_remove()
        self._suggestions = []

    def show_suggestions(self, items: list[dict]):
        self.hide_suggestions()
        self._suggestions = items

        if not items:
            return

        jobs = []

        for idx, it in enumerate(items):
            row = ttk.Frame(self.suggest_inner)
            row.pack(fill="x", pady=2, padx=2)

            img_label = ttk.Label(row, text="[img]", width=8)
            img_label.pack(side="left", padx=(0, 8))

            year = f" ({it['year']})" if it.get("year") else ""
            text = f"{it['title']}{year}"

            btn = ttk.Button(
                row,
                text=text,
                command=lambda i=idx: self.pick_suggestion_index(i),
            )
            btn.pack(side="left", fill="x", expand=True)

            movie_id = it["id"]

            btn.bind(
                "<Enter>",
                lambda e, m=movie_id: self.show_movie_preview(m, e.x_root, e.y_root),
            )

            btn.bind("<Leave>", self.hide_movie_preview)

            self._bind_mousewheel_recursive(row, self._on_mousewheel_suggestions)

            jobs.append((img_label, it.get("poster_path")))

        self.suggest_canvas.yview_moveto(0)
        self.suggest_container.grid()

        self._start_suggestion_poster_loading(jobs)

    def pick_suggestion_index(self, idx: int):
        it = self._suggestions[idx]
        self.title_var.set(it["title"])
        self.hide_suggestions()

        try:
            self.status.set("Ajout en cours…")
            res = auto_add_by_tmdb_id(it["id"])
            plat = res.get("platform") or "inconnue"
            self.status.set(f"Ajouté: {res['title']} | Plateforme: {plat}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

        self.entry.focus_set()

    def on_type(self, event=None):
        if self._suggest_after_id is not None:
            try:
                self.after_cancel(self._suggest_after_id)
            except Exception:
                pass

        self._suggest_after_id = self.after(250, self.start_suggestion_search)

    def refresh_suggestions(self):
        self.start_suggestion_search()

    def on_enter(self, event=None):
        if self._suggestions and self.suggest_container.winfo_ismapped():
            self.pick_suggestion_index(0)
            return "break"

        self.on_auto()
        return "break"

    def start_suggestion_search(self):
        q = self.title_var.get().strip()

        if len(q) < 2:
            self.hide_suggestions()
            return

        if q == self._last_suggest_query and self._suggestions:
            return

        self._last_suggest_query = q
        self._suggest_request_id += 1
        request_id = self._suggest_request_id
        self._suggest_loading = True
        self.status.set("Recherche TMDB…")

        self.show_loading_suggestions()

        thread = threading.Thread(
            target=self._suggestions_worker,
            args=(q, request_id),
            daemon=True,
        )
        thread.start()

    def _suggestions_worker(self, query: str, request_id: int):
        try:
            items = tmdb_search_suggestions(query, limit=8)
            self.after(
                0, lambda: self._apply_suggestions_result(request_id, items, None)
            )
        except Exception as e:
            self.after(0, lambda: self._apply_suggestions_result(request_id, None, e))

    def _apply_suggestions_result(self, request_id: int, items, error):
        if request_id != self._suggest_request_id:
            return

        self._suggest_loading = False

        if error is not None:
            self.status.set(f"Suggestions TMDB: erreur ({error})")
            self.hide_suggestions()
            return

        self.show_suggestions(items or [])
        self.status.set("Suggestions TMDB prêtes.")

    def show_loading_suggestions(self):
        self.hide_suggestions()

        row = ttk.Frame(self.suggest_inner)
        row.pack(fill="x", pady=4, padx=4)

        ttk.Label(row, text="Recherche des films...").pack(side="left", padx=8, pady=8)

        self.suggest_canvas.yview_moveto(0)
        self.suggest_container.grid()

    def _start_suggestion_poster_loading(self, jobs):
        if not jobs:
            return

        if hasattr(self, "_suggest_poster_jobs"):
            try:
                self.after_cancel(self._suggest_poster_jobs)
            except Exception:
                pass

        self._suggest_poster_queue = list(jobs)
        self._process_next_suggestion_poster()

    def _process_next_suggestion_poster(self):
        if not self._suggest_poster_queue:
            return

        img_label, poster_path = self._suggest_poster_queue.pop(0)

        url = tmdb_poster_url(poster_path, size="w92")
        if url:
            photo = self._load_image_from_url(url, size=(60, 90))

            if photo:
                img_label.configure(image=photo, text="")
                img_label.image = photo

        self._suggest_poster_jobs = self.after(
            30,
            self._process_next_suggestion_poster,
        )

    # =========================
    # Import liste
    # =========================
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
            total = len([t for t in titles if t.strip()])

            for idx, t in enumerate(titles, start=1):
                t = t.strip()
                if not t:
                    continue

                try:
                    self.status.set(f"Import {idx}/{total} : {t}")
                    self.update_idletasks()
                    auto_add(t)
                    added += 1
                except Exception:
                    pass

            self.status.set(f"{added} films ajoutés")
            self.refresh()
            win.destroy()

        ttk.Button(win, text="Importer", command=run_import).pack(pady=10)

    def _get_selected_title(self):
        title = self.title_var.get().strip()
        if not title and self.selected_movie:
            title = self.selected_movie.get("title", "").strip()
        return title

    def _select_movie(self, movie: dict):
        self.selected_movie = movie
        self.title_var.set(movie.get("title", ""))
        self.status.set(f"Sélectionné : {movie.get('title', '(sans titre)')}")

    def _show_movie_context_menu(self, event, movie: dict):
        self._select_movie(movie)
        try:
            self.movie_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.movie_menu.grab_release()

    def _change_status_to(self, new_status: str):
        title = self._get_selected_title()
        if not title:
            messagebox.showinfo(
                "Info",
                "Clique sur un film ou entre un titre.",
            )
            return

        try:
            self.status.set("Mise à jour du statut…")
            update_status(title, new_status)
            self.status_change_var.set(new_status)
            self.status.set(f"Statut modifié : {title} → {new_status}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def _status_badge_config(self, status: str):
        s = (status or "").strip().lower()

        if s == "vu":
            return "Vu", "#2e7d32"
        if s in ("à voir", "a voir"):
            return "À voir", "#1565c0"
        if s in ("à revoir", "a revoir"):
            return "À revoir", "#ef6c00"

        return status or "Sans statut", "#616161"

    # =========================
    # Actions
    # =========================
    def on_auto(self):
        self.hide_suggestions()
        title = self.title_var.get().strip()

        if not title:
            messagebox.showinfo("Info", "Entre un titre.")
            return

        try:
            self.status.set("Ajout en cours…")
            res = auto_add(title)
            plat = res.get("platform") or "inconnue"
            self.status.set(f"Ajouté: {res['title']} | Plateforme: {plat}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def on_seen(self):
        title = self.title_var.get().strip()

        if not title and self.selected_movie:
            title = self.selected_movie.get("title")

        if not title:
            messagebox.showinfo(
                "Info",
                "Entre un titre ou clique sur un film dans la liste.",
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

    # =========================
    # Données / tri
    # =========================
    def _sort_movies(self, movies: list[dict]) -> list[dict]:
        mode = self.sort_var.get()
        reverse = self.sort_dir_var.get() == "Décroissant"

        if mode == "Titre":
            return sorted(
                movies,
                key=lambda m: (m.get("title") or "").lower(),
                reverse=reverse,
            )

        if mode == "Année":
            return sorted(
                movies,
                key=lambda m: m.get("year") or 0,
                reverse=reverse,
            )

        if mode == "Note":
            return sorted(
                movies,
                key=lambda m: m.get("rating") or 0,
                reverse=reverse,
            )

        return movies

    def _get_gallery_columns(self, available_width: int | None = None) -> int:
        if available_width is None:
            self.update_idletasks()
            available_width = self.movies_canvas.winfo_width()

        if available_width <= 1:
            available_width = self.winfo_width()

        cfg = self._get_movie_size_config()
        card_width = cfg["gallery_card_width"]

        columns = max(1, available_width // card_width)
        return columns

    def _on_movies_canvas_resize(self, event=None):
        print("resize", event.width if event else "no event")

        if self.view_var.get() != "Galerie":
            return

        if not self.current_movies:
            return

        if event is not None:
            new_columns = self._get_gallery_columns(event.width)
        else:
            new_columns = self._get_gallery_columns()

        if new_columns == self._last_gallery_columns:
            return

        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass

        self._resize_after_id = self.after(120, self._rebuild_gallery_only)

    def _rebuild_gallery_only(self):
        self._resize_after_id = None

        if self.view_var.get() != "Galerie":
            return

        self.clear_movie_cards()
        self._display_gallery_view(self.current_movies)
        self.movies_canvas.yview_moveto(0)

    def _refresh_gallery_layout(self):
        if self.view_var.get() != "Galerie":
            return

        try:
            self._is_refreshing_gallery = True
            self.refresh()
        finally:
            self._is_refreshing_gallery = False
            self._resize_after_id = None

    def _get_settings_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).with_name("settings.json")
        return Path(__file__).with_name("settings.json")

    def _load_settings(self) -> dict:
        path = self._get_settings_path()
        if not path.exists():
            return {}

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self):
        settings = {
            "view": self.view_var.get(),
            "movie_size": self.movie_size_var.get(),
            "sort_by": self.sort_var.get(),
            "sort_dir": self.sort_dir_var.get(),
            "filter_status": self.filter_var.get(),
            "library_search": self.library_search_var.get(),
        }

        path = self._get_settings_path()
        try:
            path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _apply_loaded_settings(self, settings: dict):
        if not settings:
            return

        if "view" in settings:
            self.view_var.set(settings["view"])

        if "movie_size" in settings:
            self.movie_size_var.set(settings["movie_size"])

        if "sort_by" in settings:
            self.sort_var.set(settings["sort_by"])

        if "sort_dir" in settings:
            self.sort_dir_var.set(settings["sort_dir"])

        if "filter_status" in settings:
            self.filter_var.set(settings["filter_status"])

        if "library_search" in settings:
            self.library_search_var.set(settings["library_search"])

    def _on_app_close(self):
        self._save_settings()
        self.destroy()

    # =========================
    # Affichage principal
    # =========================
    def clear_movie_cards(self):
        if self._load_queue_after_id is not None:
            try:
                self.after_cancel(self._load_queue_after_id)
            except Exception:
                pass
            self._load_queue_after_id = None

        for child in self.movies_inner.winfo_children():
            child.destroy()

    def _build_list_card(self, movie: dict):
        cfg = self._get_movie_size_config()
        list_poster_size = cfg["list_poster"]

        outer = ttk.Frame(self.movies_inner, padding=6)
        outer.pack(fill="x", padx=4, pady=4)

        card = tk.Frame(
            outer,
            bd=1,
            relief="solid",
            padx=8,
            pady=8,
            bg="white",
            cursor="hand2",
        )
        card.pack(fill="x", expand=True)

        poster_holder = tk.Label(
            card,
            text="[chargement...]",
            bg="white",
            anchor="center",
            justify="center",
        )
        poster_holder.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 10))

        title = movie.get("title") or "(sans titre)"
        year = movie.get("year")
        rating = movie.get("rating")
        status = movie.get("status") or ""
        platform = movie.get("platform") or "Inconnue"
        genres = movie.get("genres") or []

        title_text = title
        if year:
            title_text += f" ({int(year)})"

        rating_text = "⭐ N/A"
        if rating is not None:
            rating_text = f"⭐ {float(rating):.1f}"

        genres_text = ", ".join(genres) if genres else "Genres inconnus"

        title_label = tk.Label(
            card,
            text=title_text,
            font=("Segoe UI", 12, "bold"),
            bg="white",
            anchor="w",
        )
        title_label.grid(row=0, column=1, sticky="w")

        badge_text, badge_color = self._status_badge_config(status)
        status_badge = tk.Label(
            card,
            text=badge_text,
            bg=badge_color,
            fg="white",
            padx=8,
            pady=3,
            font=("Segoe UI", 9, "bold"),
        )
        status_badge.grid(row=0, column=2, sticky="e", padx=(10, 0))

        info1 = tk.Label(
            card,
            text=f"{rating_text}   |   Plateforme : {platform}",
            bg="white",
            anchor="w",
        )
        info1.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        info2 = tk.Label(
            card,
            text=f"Genres : {genres_text}",
            bg="white",
            anchor="w",
            justify="left",
            wraplength=700,
        )
        info2.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))

        card.grid_columnconfigure(1, weight=1)

        def on_left_click(event=None):
            self._select_movie(movie)

        def on_right_click(event, m=movie):
            self._show_movie_context_menu(event, m)

        widgets = [card, poster_holder, title_label, status_badge, info1, info2]
        for w in widgets:
            w.bind("<Button-1>", on_left_click)
            w.bind("<Button-3>", on_right_click)

        self._bind_mousewheel_recursive(card, self._on_mousewheel_movies)

        return {
            "movie": movie,
            "poster_holder": poster_holder,
            "size": list_poster_size,
        }

    def _build_gallery_card(self, movie: dict, col: int, row: int):
        cfg = self._get_movie_size_config()
        gallery_poster_size = cfg["gallery_poster"]
        gallery_wraplength = cfg["gallery_wraplength"]

        card = tk.Frame(
            self.movies_inner,
            bd=1,
            relief="solid",
            padx=8,
            pady=8,
            bg="white",
            cursor="hand2",
        )
        card.grid(row=row, column=col, padx=8, pady=8, sticky="n")

        poster_holder = tk.Label(
            card,
            text="[chargement...]",
            bg="white",
            anchor="center",
            justify="center",
            wraplength=180,
        )
        poster_holder.pack()

        title = movie.get("title") or "(sans titre)"
        year = movie.get("year")
        rating = movie.get("rating")
        status = movie.get("status") or ""

        title_text = title
        if year:
            title_text += f"\n({int(year)})"

        rating_text = "⭐ N/A"
        if rating is not None:
            rating_text = f"⭐ {float(rating):.1f}"

        title_label = tk.Label(
            card,
            text=title_text,
            font=("Segoe UI", 10, "bold"),
            bg="white",
            justify="center",
            wraplength=gallery_wraplength,
        )
        title_label.pack(pady=(8, 4))

        rating_label = tk.Label(
            card,
            text=rating_text,
            bg="white",
        )
        rating_label.pack()

        badge_text, badge_color = self._status_badge_config(status)
        status_badge = tk.Label(
            card,
            text=badge_text,
            bg=badge_color,
            fg="white",
            padx=8,
            pady=3,
            font=("Segoe UI", 9, "bold"),
        )
        status_badge.pack(pady=(6, 0))

        def on_left_click(event=None):
            self._select_movie(movie)

        def on_right_click(event, m=movie):
            self._show_movie_context_menu(event, m)

        for w in [card, poster_holder, title_label, rating_label, status_badge]:
            w.bind("<Button-1>", on_left_click)
            w.bind("<Button-3>", on_right_click)

        self._bind_mousewheel_recursive(card, self._on_mousewheel_movies)

        return {
            "movie": movie,
            "poster_holder": poster_holder,
            "size": gallery_poster_size,
        }

    def _start_progressive_poster_loading(self, jobs: list[dict]):
        self._poster_jobs = jobs
        self._poster_job_index = 0
        self._load_next_poster()

    def _load_next_poster(self):
        if self._poster_job_index >= len(self._poster_jobs):
            self._load_queue_after_id = None
            return

        job = self._poster_jobs[self._poster_job_index]
        self._poster_job_index += 1

        movie = job["movie"]
        holder = job["poster_holder"]
        size = job["size"]

        poster = self._load_image_from_url(movie.get("poster_url"), size=size)

        if holder.winfo_exists():
            if poster:
                holder.configure(image=poster, text="")
                holder.image = poster
            else:
                holder.configure(text="[pas d'image]")

        self._load_queue_after_id = self.after(10, self._load_next_poster)

    def _display_list_view(self, movies: list[dict]):
        jobs = []
        for movie in movies:
            jobs.append(self._build_list_card(movie))
        self._start_progressive_poster_loading(jobs)

    def _display_gallery_view(self, movies: list[dict]):
        jobs = []

        columns = self._get_gallery_columns()
        self._last_gallery_columns = columns

        for i in range(12):
            self.movies_inner.grid_columnconfigure(i, weight=0)

        for c in range(columns):
            self.movies_inner.grid_columnconfigure(c, weight=1)

        for idx, movie in enumerate(movies):
            row = idx // columns
            col = idx % columns
            jobs.append(self._build_gallery_card(movie, col=col, row=row))

        self._start_progressive_poster_loading(jobs)

    def refresh(self):
        try:
            self.clear_movie_cards()

            filt = self.filter_var.get().strip() or None
            movies = list_movies_detailed(status=filt, limit=100)

            search_text = self.library_search_var.get().strip().lower()
            if search_text:
                movies = [
                    m for m in movies if search_text in (m.get("title") or "").lower()
                ]

            movies = self._sort_movies(movies)

            self.current_movies = movies
            self.selected_movie = None

            if self.view_var.get() == "Galerie":
                self._display_gallery_view(movies)
            else:
                self._display_list_view(movies)

            self.movies_canvas.yview_moveto(0)
            self.status.set(f"Liste mise à jour. {len(movies)} film(s).")

            self._save_settings()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def _get_selected_title(self):
        title = self.title_var.get().strip()
        if not title and self.selected_movie:
            title = self.selected_movie.get("title", "").strip()
        return title

    def on_change_status(self):
        title = self._get_selected_title()
        if not title:
            messagebox.showinfo(
                "Info",
                "Entre un titre ou clique sur un film dans la liste.",
            )
            return

        new_status = self.status_change_var.get().strip()
        if not new_status:
            messagebox.showinfo("Info", "Choisis un statut.")
            return

        try:
            self.status.set("Mise à jour du statut…")
            update_status(title, new_status)
            self.status.set(f"Statut modifié : {title} → {new_status}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def on_delete_movie(self):
        title = self._get_selected_title()
        if not title:
            messagebox.showinfo(
                "Info",
                "Entre un titre ou clique sur un film dans la liste.",
            )
            return

        ok = messagebox.askyesno(
            "Confirmation",
            f"Supprimer '{title}' de la liste ?",
        )
        if not ok:
            return

        try:
            self.status.set("Suppression…")
            delete_movie(title)
            self.title_var.set("")
            self.selected_movie = None
            self.status.set(f"Film supprimé : {title}")
            self.refresh()
        except Exception as e:
            self.status.set("Erreur.")
            messagebox.showerror("Erreur", str(e))

    def _get_movie_size_config(self):
        size_name = self.movie_size_var.get()

        configs = {
            "Très grand": {
                "list_poster": (190, 285),
                "gallery_poster": (260, 390),
                "gallery_card_width": 320,
                "gallery_wraplength": 220,
            },
            "Grand": {
                "list_poster": (160, 240),
                "gallery_poster": (220, 330),
                "gallery_card_width": 280,
                "gallery_wraplength": 190,
            },
            "Moyen": {
                "list_poster": (130, 195),
                "gallery_poster": (180, 270),
                "gallery_card_width": 240,
                "gallery_wraplength": 170,
            },
            "Petit": {
                "list_poster": (100, 150),
                "gallery_poster": (150, 225),
                "gallery_card_width": 210,
                "gallery_wraplength": 150,
            },
            "Très petit": {
                "list_poster": (80, 120),
                "gallery_poster": (120, 180),
                "gallery_card_width": 180,
                "gallery_wraplength": 130,
            },
        }

        return configs.get(size_name, configs["Grand"])

    def show_movie_preview(self, movie_id, x, y):
        try:
            data = tmdb_movie_details(movie_id)

            title = data["title"] or ""
            year = data["year"] or ""
            rating = data["rating"]
            overview = data["overview"] or ""

            rating_text = "⭐ N/A"
            if rating is not None:
                rating_text = f"⭐ {rating:.1f}"

            text = f"{title} ({year})\n{rating_text}\n\n{overview}"

            if hasattr(self, "_preview_win") and self._preview_win:
                self._preview_win.destroy()

            win = tk.Toplevel(self)
            win.overrideredirect(True)
            win.geometry(f"+{x+20}+{y+20}")

            frame = tk.Frame(win, bg="white", bd=1, relief="solid", padx=10, pady=10)
            frame.pack()

            label = tk.Label(
                frame,
                text=text,
                justify="left",
                bg="white",
                wraplength=300,
            )
            label.pack()

            self._preview_win = win

        except Exception:
            pass

    def hide_movie_preview(self, event=None):
        if hasattr(self, "_preview_win") and self._preview_win:
            try:
                self._preview_win.destroy()
            except Exception:
                pass
            self._preview_win = None


if __name__ == "__main__":
    App().mainloop()
