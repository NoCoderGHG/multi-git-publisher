#!/usr/bin/env python3
# Multi-Git-Publisher
# Parallel-Push zu GitHub, GitLab, Codeberg
# MIT License — NoCoderGHG

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

import json
import locale
import os
import subprocess
import threading
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "multi-git-publisher"
CONFIG_FILE = CONFIG_DIR / "config.json"
I18N_DIR = Path(__file__).parent / "i18n"

PLATFORMS = ["GitHub", "GitLab", "Codeberg"]
PLATFORM_HOSTS = {
    "GitHub": "github.com",
    "GitLab": "gitlab.com",
    "Codeberg": "codeberg.org",
}

DEFAULT_CONFIG = {
    "lang": "system",
    "tokens": {"GitHub": "", "GitLab": "", "Codeberg": ""},
    "repos": [],
}


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def detect_system_lang():
    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""
    if not loc:
        loc = os.environ.get("LANG", "")
    return "de" if loc.lower().startswith("de") else "en"


def resolve_lang(setting):
    if setting == "system":
        return detect_system_lang()
    return setting


def load_i18n(lang):
    en = {}
    en_path = I18N_DIR / "en.json"
    if en_path.exists():
        with open(en_path) as f:
            en = json.load(f)
    if lang == "en":
        return en
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        return en
    with open(path) as f:
        strings = json.load(f)
    for k, v in en.items():
        strings.setdefault(k, v)
    return strings


def t(strings, key, **kwargs):
    s = strings.get(key, key)
    for k, v in kwargs.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def is_git_repo(path):
    return (Path(path) / ".git").is_dir()


def build_remote_url(platform, token, repo_url):
    host = PLATFORM_HOSTS.get(platform, "")
    if not token or not host:
        return repo_url
    if repo_url.startswith("https://"):
        after_https = repo_url[len("https://"):]
        if platform == "GitHub":
            return f"https://{token}@{after_https}"
        else:
            return f"https://oauth2:{token}@{after_https}"
    return repo_url


def push_to_remote(repo_path, remote_url, branch, platform, token, callback):
    authed_url = build_remote_url(platform, token, remote_url)
    try:
        result = subprocess.run(
            ["git", "push", authed_url, f"HEAD:{branch}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        GLib.idle_add(callback, platform, success, output)
    except subprocess.TimeoutExpired:
        GLib.idle_add(callback, platform, False, "Timeout")
    except Exception as e:
        GLib.idle_add(callback, platform, False, str(e))


def make_menu_button(items, on_select, min_width=150):
    """items: list of str. on_select(text) called on selection. Returns (button, update_fn)."""
    btn = Gtk.MenuButton()
    btn.set_size_request(min_width, -1)
    lbl = Gtk.Label(label=items[0] if items else "")
    btn.add(lbl)
    menu = Gtk.Menu()

    def build_menu(items, current=None):
        for child in menu.get_children():
            menu.remove(child)
        group = []
        for text in items:
            item = Gtk.RadioMenuItem.new_with_label(group, text)
            group = item.get_group()
            if text == current:
                item.set_active(True)

            def _on_activate(i, t=text):
                if i.get_active():
                    lbl.set_text(t)
                    on_select(t)
            item.connect("activate", _on_activate)
            menu.append(item)
        menu.show_all()
        if items:
            active = current if current in items else items[0]
            lbl.set_text(active)

    build_menu(items, items[0] if items else None)
    btn.set_popup(menu)

    def update(new_items, current=None):
        build_menu(new_items, current)

    return btn, lbl, update


class MultiGitPublisher(Gtk.Window):
    def __init__(self):
        super().__init__(title="Multi-Git-Publisher")
        self.set_default_size(720, 580)
        self.set_border_width(0)

        self.cfg = load_config()
        self.strings = load_i18n(resolve_lang(self.cfg.get("lang", "system")))

        self._build_ui()
        self._refresh_repo_list()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = t(self.strings, "app_title")
        self.set_titlebar(header)

        self._lang_options = [("de", "lang_de"), ("en", "lang_en"), ("system", "lang_system")]
        self.lang_menu_btn = Gtk.MenuButton()
        self.lang_menu_btn.set_size_request(130, -1)
        self._lang_label = Gtk.Label()
        self.lang_menu_btn.add(self._lang_label)
        lang_menu = Gtk.Menu()
        group = []
        current_lang = self.cfg.get("lang", "system")
        for code, key in self._lang_options:
            item = Gtk.RadioMenuItem.new_with_label(group, t(self.strings, key))
            group = item.get_group()
            if code == current_lang:
                item.set_active(True)
            item.connect("activate", self._on_lang_menu_item, code)
            lang_menu.append(item)
            if code == current_lang:
                self._lang_label.set_text(t(self.strings, key))
        lang_menu.show_all()
        self.lang_menu_btn.set_popup(lang_menu)
        header.pack_end(self.lang_menu_btn)

        self.notebook = Gtk.Notebook()
        self.notebook.set_border_width(0)
        vbox.pack_start(self.notebook, True, True, 0)

        self._build_publish_tab()
        self._build_repos_tab()
        self._build_tokens_tab()

    def _build_publish_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(16)

        # Project selector
        row_project = Gtk.Box(spacing=8)
        lbl_project = Gtk.Label(label=t(self.strings, "project") + ":")
        lbl_project.set_xalign(0)
        lbl_project.set_size_request(160, -1)
        self.project_menu_btn, self._project_label, self._project_update = make_menu_button(
            [], lambda name: self._on_project_selected(name), min_width=180
        )
        row_project.pack_start(lbl_project, False, False, 0)
        row_project.pack_start(self.project_menu_btn, True, True, 0)
        box.pack_start(row_project, False, False, 0)

        # Repo path
        row_path = Gtk.Box(spacing=8)
        lbl_path = Gtk.Label(label=t(self.strings, "repo_path") + ":")
        lbl_path.set_xalign(0)
        lbl_path.set_size_request(160, -1)
        self.entry_repo_path = Gtk.Entry()
        self.entry_repo_path.set_placeholder_text(t(self.strings, "repo_path_placeholder"))
        self.entry_repo_path.set_hexpand(True)
        self.entry_repo_path.connect("changed", self._on_repo_path_changed)
        btn_browse = Gtk.Button(label=t(self.strings, "browse"))
        btn_browse.connect("clicked", self._on_browse)
        row_path.pack_start(lbl_path, False, False, 0)
        row_path.pack_start(self.entry_repo_path, True, True, 0)
        row_path.pack_start(btn_browse, False, False, 0)
        box.pack_start(row_path, False, False, 0)

        # Init banner (initially hidden)
        self.init_banner = Gtk.Box(spacing=8)

        lbl_init = Gtk.Label(label=t(self.strings, "init_hint"))
        lbl_init.set_xalign(0)
        lbl_init.set_hexpand(True)
        lbl_init.set_line_wrap(True)

        self.entry_commit_msg = Gtk.Entry()
        self.entry_commit_msg.set_text("Initial commit")
        self.entry_commit_msg.set_width_chars(24)
        self.entry_commit_msg.set_placeholder_text(t(self.strings, "commit_msg_placeholder"))

        btn_init = Gtk.Button(label=t(self.strings, "btn_init"))
        btn_init.get_style_context().add_class("suggested-action")
        btn_init.connect("clicked", self._on_git_init)

        self.init_banner.pack_start(lbl_init, True, True, 0)
        self.init_banner.pack_start(self.entry_commit_msg, False, False, 0)
        self.init_banner.pack_start(btn_init, False, False, 0)
        box.pack_start(self.init_banner, False, False, 0)
        self.init_banner.set_visible(False)

        # Commit banner (visible when valid repo is selected)
        self.commit_banner = Gtk.Box(spacing=8)

        lbl_commit = Gtk.Label(label=t(self.strings, "commit_hint"))
        lbl_commit.set_xalign(0)
        lbl_commit.set_hexpand(True)
        lbl_commit.set_line_wrap(True)

        self.entry_new_commit_msg = Gtk.Entry()
        self.entry_new_commit_msg.set_width_chars(24)
        self.entry_new_commit_msg.set_placeholder_text(t(self.strings, "commit_msg_placeholder"))

        btn_commit = Gtk.Button(label=t(self.strings, "btn_commit"))
        btn_commit.connect("clicked", self._on_git_commit)

        self.commit_banner.pack_start(lbl_commit, True, True, 0)
        self.commit_banner.pack_start(self.entry_new_commit_msg, False, False, 0)
        self.commit_banner.pack_start(btn_commit, False, False, 0)
        box.pack_start(self.commit_banner, False, False, 0)
        self.commit_banner.set_visible(False)

        # Branch
        row_branch = Gtk.Box(spacing=8)
        lbl_branch = Gtk.Label(label=t(self.strings, "branch") + ":")
        lbl_branch.set_xalign(0)
        lbl_branch.set_size_request(160, -1)
        self.entry_branch = Gtk.Entry()
        self.entry_branch.set_text("main")
        self.entry_branch.set_placeholder_text(t(self.strings, "branch_placeholder"))
        self.entry_branch.set_hexpand(True)
        row_branch.pack_start(lbl_branch, False, False, 0)
        row_branch.pack_start(self.entry_branch, True, True, 0)
        box.pack_start(row_branch, False, False, 0)

        # Target platform checkboxes
        lbl_targets = Gtk.Label(label=t(self.strings, "targets") + ":")
        lbl_targets.set_xalign(0)
        box.pack_start(lbl_targets, False, False, 0)

        self.check_platforms = {}
        row_checks = Gtk.Box(spacing=16)
        for p in PLATFORMS:
            cb = Gtk.CheckButton(label=p)
            cb.set_active(True)
            self.check_platforms[p] = cb
            row_checks.pack_start(cb, False, False, 0)
        box.pack_start(row_checks, False, False, 0)

        # Push button
        self.btn_push = Gtk.Button(label=t(self.strings, "publish"))
        self.btn_push.get_style_context().add_class("suggested-action")
        self.btn_push.connect("clicked", self._on_push)
        box.pack_start(self.btn_push, False, False, 0)

        # Log
        lbl_log = Gtk.Label(label=t(self.strings, "log_title") + ":")
        lbl_log.set_xalign(0)
        box.pack_start(lbl_log, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buffer = self.log_view.get_buffer()
        self._setup_log_tags()
        self._append_log(t(self.strings, "log_empty"), "muted")

        scroll.add(self.log_view)
        box.pack_start(scroll, True, True, 0)

        label = Gtk.Label(label=t(self.strings, "tab_publish"))
        self.notebook.append_page(box, label)

    def _setup_log_tags(self):
        self.log_buffer.create_tag("ok", foreground="#1D9E75")
        self.log_buffer.create_tag("fail", foreground="#E24B4A")
        self.log_buffer.create_tag("info", foreground="#378ADD")
        self.log_buffer.create_tag("muted", foreground="#888780")
        self.log_buffer.create_tag("bold", weight=Pango.Weight.BOLD)

    def _append_log(self, text, tag=None):
        end = self.log_buffer.get_end_iter()
        if tag:
            self.log_buffer.insert_with_tags_by_name(end, text + "\n", tag)
        else:
            self.log_buffer.insert(end, text + "\n")
        self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0, False, 0, 0)

    def _clear_log(self):
        self.log_buffer.set_text("")

    def _on_repo_path_changed(self, entry):
        path = entry.get_text().strip()
        if path and os.path.isdir(path) and not is_git_repo(path):
            self.init_banner.set_visible(True)
            self.commit_banner.set_visible(False)
        elif path and is_git_repo(path):
            self.init_banner.set_visible(False)
            self.commit_banner.set_visible(True)
        else:
            self.init_banner.set_visible(False)
            self.commit_banner.set_visible(False)

    def _on_git_init(self, _):
        repo_path = self.entry_repo_path.get_text().strip()
        msg = self.entry_commit_msg.get_text().strip() or "Initial commit"
        try:
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, check=True, capture_output=True)
            self.init_banner.set_visible(False)
            self._clear_log()
            self._append_log(t(self.strings, "init_ok"), "ok")
        except subprocess.CalledProcessError as e:
            self._clear_log()
            self._append_log(t(self.strings, "init_fail", error=e.stderr.decode() if e.stderr else str(e)), "fail")

    def _on_git_commit(self, _):
        repo_path = self.entry_repo_path.get_text().strip()
        msg = self.entry_new_commit_msg.get_text().strip()
        if not msg:
            self._clear_log()
            self._append_log(t(self.strings, "commit_msg_empty"), "fail")
            return
        try:
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            result = subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, capture_output=True)
            if result.returncode == 0:
                self.entry_new_commit_msg.set_text("")
                self._clear_log()
                self._append_log(t(self.strings, "commit_ok"), "ok")
            else:
                output = result.stderr.decode() if result.stderr else result.stdout.decode()
                self._clear_log()
                self._append_log(t(self.strings, "commit_fail", error=output), "fail")
        except subprocess.CalledProcessError as e:
            self._clear_log()
            self._append_log(t(self.strings, "commit_fail", error=e.stderr.decode() if e.stderr else str(e)), "fail")

    def _build_repos_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)

        toolbar = Gtk.Box(spacing=8)
        btn_add = Gtk.Button(label=t(self.strings, "repo_add"))
        btn_add.connect("clicked", self._on_repo_add)
        btn_remove = Gtk.Button(label=t(self.strings, "repo_remove"))
        btn_remove.connect("clicked", self._on_repo_remove)
        toolbar.pack_start(btn_add, False, False, 0)
        toolbar.pack_start(btn_remove, False, False, 0)
        box.pack_start(toolbar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.repo_store = Gtk.ListStore(str, str, str, str)  # name, platform, url, local_path
        self.repo_view = Gtk.TreeView(model=self.repo_store)
        for i, col_title in enumerate([
            t(self.strings, "repo_name"),
            t(self.strings, "repo_platform"),
            t(self.strings, "repo_url"),
            t(self.strings, "repo_local_path"),
        ]):
            renderer = Gtk.CellRendererText()
            renderer.set_property("editable", True)
            renderer.connect("edited", self._on_repo_cell_edited, i)
            col = Gtk.TreeViewColumn(col_title, renderer, text=i)
            col.set_resizable(True)
            col.set_expand(True)
            self.repo_view.append_column(col)
        scroll.add(self.repo_view)
        box.pack_start(scroll, True, True, 0)

        row_new = Gtk.Box(spacing=8)
        self.entry_new_name = Gtk.Entry()
        self.entry_new_name.set_placeholder_text(t(self.strings, "repo_name"))
        self._platform_current = PLATFORMS[0]
        self.platform_menu_btn, self._platform_label, _ = make_menu_button(
            PLATFORMS, lambda p: setattr(self, "_platform_current", p), min_width=120
        )
        self.entry_new_url = Gtk.Entry()
        self.entry_new_url.set_placeholder_text("https://github.com/user/repo.git")
        self.entry_new_url.set_hexpand(True)
        self.entry_new_local = Gtk.Entry()
        self.entry_new_local.set_placeholder_text(t(self.strings, "repo_local_path"))
        self.entry_new_local.set_width_chars(20)
        btn_browse_new = Gtk.Button(label="…")
        btn_browse_new.connect("clicked", self._on_browse_new_local)
        btn_add2 = Gtk.Button(label="+")
        btn_add2.connect("clicked", self._on_repo_add_row)
        row_new.pack_start(self.entry_new_name, False, False, 0)
        row_new.pack_start(self.platform_menu_btn, False, False, 0)
        row_new.pack_start(self.entry_new_url, True, True, 0)
        row_new.pack_start(self.entry_new_local, False, False, 0)
        row_new.pack_start(btn_browse_new, False, False, 0)
        row_new.pack_start(btn_add2, False, False, 0)
        box.pack_start(row_new, False, False, 0)

        label = Gtk.Label(label=t(self.strings, "tab_repos"))
        self.notebook.append_page(box, label)

    def _build_tokens_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(16)

        self.token_entries = {}
        for p in PLATFORMS:
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label=p + ":")
            lbl.set_xalign(0)
            lbl.set_size_request(100, -1)
            entry = Gtk.Entry()
            entry.set_visibility(False)
            entry.set_hexpand(True)
            entry.set_text(self.cfg["tokens"].get(p, ""))
            eye_btn = Gtk.ToggleButton()
            eye_btn.set_label("👁")
            eye_btn.connect("toggled", lambda b, e=entry: e.set_visibility(b.get_active()))
            self.token_entries[p] = entry
            row.pack_start(lbl, False, False, 0)
            row.pack_start(entry, True, True, 0)
            row.pack_start(eye_btn, False, False, 0)
            box.pack_start(row, False, False, 0)

        btn_save = Gtk.Button(label=t(self.strings, "token_save"))
        btn_save.connect("clicked", self._on_tokens_save)
        box.pack_start(btn_save, False, False, 0)

        lbl_hint = Gtk.Label(label=t(self.strings, "token_hint"))
        lbl_hint.set_xalign(0)
        lbl_hint.set_line_wrap(True)
        lbl_hint.get_style_context().add_class("dim-label")
        box.pack_start(lbl_hint, False, False, 8)

        label = Gtk.Label(label=t(self.strings, "tab_tokens"))
        self.notebook.append_page(box, label)

    def _refresh_repo_list(self):
        self.repo_store.clear()
        for r in self.cfg.get("repos", []):
            self.repo_store.append([r.get("name", ""), r.get("platform", ""), r.get("url", ""), r.get("local_path", "")])
        self._refresh_project_combo()

    def _refresh_project_combo(self):
        seen = []
        for r in self.cfg.get("repos", []):
            name = r.get("name", "")
            if name and name not in seen:
                seen.append(name)
        current = self._project_label.get_text() if seen else ""
        self._project_update(seen, current if current in seen else (seen[0] if seen else None))

    def _on_browse(self, _):
        dialog = Gtk.FileChooserDialog(
            title=t(self.strings, "repo_path"),
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.entry_repo_path.set_text(dialog.get_filename())
            self._on_repo_path_changed(self.entry_repo_path)
        dialog.destroy()

    def _on_push(self, _):
        repo_path = self.entry_repo_path.get_text().strip()
        branch = self.entry_branch.get_text().strip() or "main"

        if not repo_path:
            self._clear_log()
            self._append_log(t(self.strings, "status_no_repo"), "fail")
            return

        if not is_git_repo(repo_path):
            self._clear_log()
            self._append_log(t(self.strings, "status_not_git"), "fail")
            return

        selected_platforms = [p for p, cb in self.check_platforms.items() if cb.get_active()]
        if not selected_platforms:
            self._clear_log()
            self._append_log(t(self.strings, "status_no_targets"), "fail")
            return

        repos = self.cfg.get("repos", [])
        selected_project = self._project_label.get_text()
        tasks = []
        for p in selected_platforms:
            token = self.cfg["tokens"].get(p, "")
            platform_repos = [r for r in repos if r.get("platform") == p and (not selected_project or r.get("name") == selected_project)]
            if not platform_repos:
                self._append_log(f"[{p}] Kein Repository konfiguriert.", "muted")
                continue
            if not token:
                self._append_log(t(self.strings, "error_token_missing", platform=p), "fail")
                continue
            for r in platform_repos:
                tasks.append((p, token, r["url"]))

        if not tasks:
            return

        self._clear_log()
        self.btn_push.set_sensitive(False)
        self._pending = len(tasks)

        for platform, token, url in tasks:
            self._append_log(t(self.strings, "status_pushing", platform=platform), "info")
            thread = threading.Thread(
                target=push_to_remote,
                args=(repo_path, url, branch, platform, token, self._on_push_result),
                daemon=True,
            )
            thread.start()

    def _on_push_result(self, platform, success, output):
        tag = "ok" if success else "fail"
        status = t(self.strings, "status_ok") if success else t(self.strings, "status_fail")
        self._append_log(f"[{platform}] {status}", tag)
        if output.strip():
            self._append_log(output.strip(), "muted")
        self._pending -= 1
        if self._pending <= 0:
            self.btn_push.set_sensitive(True)

    def _on_repo_add(self, _):
        self.notebook.set_current_page(1)

    def _on_repo_remove(self, _):
        sel = self.repo_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=t(self.strings, "confirm_remove"),
        )
        if dialog.run() == Gtk.ResponseType.YES:
            path = model.get_path(it)
            idx = path.get_indices()[0]
            self.cfg["repos"].pop(idx)
            save_config(self.cfg)
            self._refresh_repo_list()
        dialog.destroy()

    def _on_browse_new_local(self, _):
        dialog = Gtk.FileChooserDialog(
            title=t(self.strings, "repo_path"),
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.entry_new_local.set_text(dialog.get_filename())
        dialog.destroy()

    def _on_project_selected(self, name):
        if not name:
            return
        repos = self.cfg.get("repos", [])
        local_path = next((r.get("local_path", "") for r in repos if r.get("name") == name), "")
        if local_path:
            self.entry_repo_path.set_text(local_path)
            self._on_repo_path_changed(self.entry_repo_path)

    def _on_repo_add_row(self, _):
        name = self.entry_new_name.get_text().strip()
        platform = self._platform_current
        url = self.entry_new_url.get_text().strip()
        local_path = self.entry_new_local.get_text().strip()
        if not url:
            return
        if not name:
            name = platform
        self.cfg.setdefault("repos", []).append({"name": name, "platform": platform, "url": url, "local_path": local_path})
        save_config(self.cfg)
        self._refresh_repo_list()
        self.entry_new_name.set_text("")
        self.entry_new_url.set_text("")
        self.entry_new_local.set_text("")

    def _on_repo_cell_edited(self, renderer, path, new_text, col):
        it = self.repo_store.get_iter_from_string(path)
        self.repo_store.set_value(it, col, new_text)
        idx = int(path)
        keys = ["name", "platform", "url", "local_path"]
        self.cfg["repos"][idx][keys[col]] = new_text
        save_config(self.cfg)
        if col == 0:  # name changed → refresh project combo
            self._refresh_project_combo()

    def _on_tokens_save(self, _):
        for p, entry in self.token_entries.items():
            self.cfg["tokens"][p] = entry.get_text()
        save_config(self.cfg)
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=t(self.strings, "settings_saved"),
        )
        dialog.run()
        dialog.destroy()

    def _on_lang_menu_item(self, item, code):
        if not item.get_active():
            return
        if code == self.cfg.get("lang"):
            return
        self.cfg["lang"] = code
        save_config(self.cfg)
        for c, key in self._lang_options:
            if c == code:
                self._lang_label.set_text(t(self.strings, key))
                break
        new_strings = load_i18n(resolve_lang(code))
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=t(new_strings, "restart_hint"),
        )
        dialog.run()
        dialog.destroy()


def main():
    win = MultiGitPublisher()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
