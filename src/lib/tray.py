#!/usr/bin/env python3

# genesi-update-tray: A systray applet for Genesi-Update
# https://github.com/Antiz96/genesi-update
# SPDX-License-Identifier: GPL-3.0-or-later

"""Genesi-Update System Tray

WHY libappindicator (Gtk) AND NOT Qt's QSystemTrayIcon:
    Qt 6.11's StatusNotifierItem implementation is broken against the caelestia
    (Quickshell) bar used by the Genesi Hyprland session: it registers the item
    with the StatusNotifierWatcher but never serves its properties to the host,
    so the icon simply never appears. Restarting the shell used to make it show
    up sometimes, then stopped working entirely.

    This is the same failure that already forced genesi-containers-tray and
    genesi-ai-tray onto libappindicator. Applications using libappindicator
    (Spotify, Discord, the Genesi trays) render correctly in that same bar, so
    this applet uses libayatana-appindicator too. The icons were always
    installed into hicolor, which is what appindicator resolves against.

    One behavioural consequence: appindicator is menu-only, so a LEFT click
    opens the menu instead of launching Genesi-Update directly. The launch
    action is the first menu entry, and middle-click still launches it via
    set_secondary_activate_target.
"""
import gettext
import logging
import os
import sys
import subprocess
import time
import json
from math import floor

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):       # fall back to the older libappindicator
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import GLib, Gtk

# Create logger
log = logging.getLogger(__name__)

# How often the icon and menu are refreshed. dbusmenu gives no reliable
# "about to show" signal through the host, so the menu cannot be built lazily
# the way the Qt version did — it is rebuilt on a light timer instead.
REFRESH_SECONDS = 5

# Find Icon statefile
ICON_STATEFILE = None

if 'XDG_STATE_HOME' in os.environ:
    ICON_STATEFILE = os.path.join(
        os.environ['XDG_STATE_HOME'], 'genesi-update', 'tray_icon')
elif 'HOME' in os.environ:
    ICON_STATEFILE = os.path.join(
        os.environ['HOME'], '.local', 'state', 'genesi-update', 'tray_icon')
if not os.path.isfile(ICON_STATEFILE):
    log.error("State icon file does not exist: %s", ICON_STATEFILE)
    sys.exit(1)

# Find Updates statefiles
UPDATES_STATEFILE = None
UPDATES_STATEFILE_PACKAGES = None
UPDATES_STATEFILE_AUR = None
UPDATES_STATEFILE_FLATPAK = None

if 'XDG_STATE_HOME' in os.environ:
    UPDATES_STATEFILE = os.path.join(
        os.environ['XDG_STATE_HOME'], 'genesi-update', 'last_updates_check')
    UPDATES_STATEFILE_PACKAGES = os.path.join(
        os.environ['XDG_STATE_HOME'], 'genesi-update', 'last_updates_check_packages')
    UPDATES_STATEFILE_AUR = os.path.join(
        os.environ['XDG_STATE_HOME'], 'genesi-update', 'last_updates_check_aur')
    UPDATES_STATEFILE_FLATPAK = os.path.join(
        os.environ['XDG_STATE_HOME'], 'genesi-update', 'last_updates_check_flatpak')
elif 'HOME' in os.environ:
    UPDATES_STATEFILE = os.path.join(
        os.environ['HOME'], '.local', 'state', 'genesi-update', 'last_updates_check')
    UPDATES_STATEFILE_PACKAGES = os.path.join(
        os.environ['HOME'], '.local', 'state', 'genesi-update', 'last_updates_check_packages')
    UPDATES_STATEFILE_AUR = os.path.join(
        os.environ['HOME'], '.local', 'state', 'genesi-update', 'last_updates_check_aur')
    UPDATES_STATEFILE_FLATPAK = os.path.join(
        os.environ['HOME'], '.local', 'state', 'genesi-update', 'last_updates_check_flatpak')
if not os.path.isfile(UPDATES_STATEFILE):
    log.error("State updates file does not exist: %s", UPDATES_STATEFILE)

# Check where the translation files are installed (depending on the PREFIX used during the installation) to set the localedir
i18n_paths = []

if 'XDG_DATA_HOME' in os.environ:
    i18n_paths.extend(os.environ['XDG_DATA_HOME'].split(":"))
if 'HOME' in os.environ:
    i18n_paths.append(os.path.join(
        os.environ['HOME'], '.local', 'share'))
if 'XDG_DATA_DIRS' in os.environ:
    i18n_paths.extend(os.environ['XDG_DATA_DIRS'].split(":"))
i18n_paths.extend(['/usr/local/share', '/usr/share'])
_ = None

for path in i18n_paths:
    translation_file = os.path.join(
        path, "locale", "fr", "LC_MESSAGES", "Genesi-Update.mo")
    if os.path.isfile(translation_file):
        path = os.path.join(path, 'locale')
        t = gettext.translation('Genesi-Update', localedir=path, fallback=True)
        _ = t.gettext
        break
if not _:
    t = gettext.translation('Genesi-Update', fallback=True)
    _ = t.gettext
    log.error("No translation found")

# Launch genesi-update with desktop file
def arch_update():
    """Launch with desktop file"""
    DESKTOP_FILE = None
    if 'XDG_DATA_HOME' in os.environ:
        DESKTOP_FILE = os.path.join(
            os.environ['XDG_DATA_HOME'], 'applications', 'genesi-update.desktop')
    if not DESKTOP_FILE or not os.path.isfile(DESKTOP_FILE):
        if 'HOME' in os.environ:
            DESKTOP_FILE = os.path.join(
                os.environ['HOME'], '.local', 'share', 'applications', 'genesi-update.desktop')
    if not DESKTOP_FILE or not os.path.isfile(DESKTOP_FILE):
        if 'XDG_DATA_DIRS' in os.environ:
            DESKTOP_FILE = os.path.join(
                os.environ['XDG_DATA_DIRS'], 'applications', 'genesi-update.desktop')
    if not DESKTOP_FILE or not os.path.isfile(DESKTOP_FILE):
        DESKTOP_FILE = "/usr/local/share/applications/genesi-update.desktop"
    if not os.path.isfile(DESKTOP_FILE):
        DESKTOP_FILE = "/usr/share/applications/genesi-update.desktop"
    subprocess.run(["gio", "launch", DESKTOP_FILE], check=False)

# Helper function to extract human-readable duration from systemctl JSON output
def get_next_check_duration_human_readable(input_json):
    """Calculate human-readable duration from systemctl output"""
    result = None
    timer_json = json.loads(input_json)
    if timer_json:
        next_microseconds = timer_json[0].get("next")
        if next_microseconds:
            seconds = floor((next_microseconds - int(time.time() * 1_000_000))/1_000_000)
            days = floor(seconds/86400)
            hours = floor((seconds % 86400) / 3600)
            minutes = floor((seconds % 3600) / 60)
            seconds = floor(seconds % 60)
            parts = []
            if days > 0:
                parts.append(f"{days}d")
            if hours > 0:
                parts.append(f"{hours}h")
            if minutes > 0:
                parts.append(f"{minutes}m")
            if seconds > 0:
                parts.append(f"{seconds}s")
            if parts:
                result = " ".join(parts)
    return result


def read_lines(path):
    """Non-empty lines of a statefile, or None when it isn't there."""
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        return None


def show_update(update):
    """Open a package's upstream URL in the browser"""
    package = update.split(' ')[0]
    if not package:
        return
    with subprocess.Popen(["/usr/bin/pacman", "-Qi", package],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        stdout, _stderr = p.communicate()
    if p.returncode != 0:
        return
    for line in stdout.decode().splitlines():
        if line.startswith("URL"):
            parts = line.split(":", 1)
            if len(parts) < 2:
                return
            url = parts[1].strip()
            # Make sure to only send URLs to xdg-open
            if url.startswith("http://") or url.startswith("https://"):
                subprocess.run(["xdg-open", url], check=False)


def _item(label, enabled=True, on_activate=None):
    """A Gtk menu row, optionally greyed out or wired to an action."""
    mi = Gtk.MenuItem(label=label)
    mi.set_sensitive(enabled)
    if on_activate:
        mi.connect("activate", lambda _w: on_activate())
    return mi


def _submenu(parent, title, updates, clickable):
    """Attach a titled submenu listing `updates` under `parent`."""
    item = Gtk.MenuItem(label=title)
    sub = Gtk.Menu()
    for update in updates:
        sub.append(_item(
            update,
            on_activate=(lambda u=update: show_update(u)) if clickable else None,
        ))
    item.set_submenu(sub)
    parent.append(item)


# User Interface
class GenesiUpdateTray:
    """System tray applet built on libappindicator (see the module docstring)."""

    def __init__(self, iconfile):
        self.iconfile = iconfile
        self.updatesfile = UPDATES_STATEFILE
        self.updatesfilepkg = UPDATES_STATEFILE_PACKAGES
        self.updatesfileaur = UPDATES_STATEFILE_AUR
        self.updatesfileflatpak = UPDATES_STATEFILE_FLATPAK
        self.current_icon = None

        # The icons this package installs live in hicolor, which is the theme
        # appindicator resolves names against.
        self.ind = AppIndicator.Indicator.new(
            "genesi-update", "genesi-update-blue",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title(_("Genesi-Update"))

        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

    def _tick(self):
        self.refresh()
        return True  # keep the timer running

    def refresh(self):
        """Re-read every statefile and rebuild the icon and the menu."""
        self.update_icon()
        self.update_menu()

    def update_icon(self):
        """Point the indicator at whatever the 'tray_icon' statefile names."""
        try:
            with open(self.iconfile, encoding="utf-8") as f:
                contents = f.readline().strip()
        except FileNotFoundError:
            log.error("Statefile Missing")
            return

        if contents.startswith("genesi-update") and contents != self.current_icon:
            self.current_icon = contents
            self.ind.set_icon_full(contents, _("Genesi-Update"))

    def update_menu(self):
        """Rebuild the dropdown from the statefiles."""
        menu = Gtk.Menu()

        updates_list = read_lines(self.updatesfile)
        if updates_list is None:
            log.error("State updates file missing")
            menu.append(_item(_("'updates' state file isn't found"), False))
            self._append_static(menu)
            menu.show_all()
            self.ind.set_menu(menu)
            return

        last_check_time = time.strftime(
            "%d %b %H:%M:%S", time.localtime(os.path.getmtime(self.updatesfile)))
        updates_list_pkg = read_lines(self.updatesfilepkg) or []
        updates_list_aur = read_lines(self.updatesfileaur) or []
        updates_list_flatpak = read_lines(self.updatesfileflatpak) or []

        updates_count = len(updates_list)
        updates_count_pkg = len(updates_list_pkg)
        updates_count_aur = len(updates_list_aur)
        updates_count_flatpak = len(updates_list_flatpak)

        # Headline row, which doubles as the launch action when there IS
        # something to install (appindicator has no left-click action of its
        # own, so the menu has to carry it).
        if updates_count == 0:
            menu.append(_item(_("System is up to date"), False))
        else:
            title = (_("1 update available") if updates_count == 1
                     else _("{updates} updates available").format(updates=updates_count))
            menu.append(_item(title, on_activate=arch_update))

        # Per-source submenus, matching what the Qt build showed.
        if (updates_count_pkg >= 1) + (updates_count_aur >= 1) + (updates_count_flatpak >= 1) >= 2:
            _submenu(menu, _("All ({updates})").format(updates=updates_count),
                     [*updates_list_pkg, *updates_list_aur], True)
        if updates_count_pkg >= 1:
            _submenu(menu, _("Packages ({updates})").format(updates=updates_count_pkg),
                     updates_list_pkg, True)
        if updates_count_aur >= 1:
            _submenu(menu, _("AUR ({updates})").format(updates=updates_count_aur),
                     updates_list_aur, True)
        if updates_count_flatpak >= 1:
            _submenu(menu, _("Flatpak ({updates})").format(updates=updates_count_flatpak),
                     updates_list_flatpak, False)

        if updates_count >= 1:
            menu.append(Gtk.SeparatorMenuItem())
        menu.append(_item(_("Last check:\n{time}").format(time=last_check_time), False))

        next_check_output = None
        try:
            timer_left = subprocess.run(
                ["/usr/bin/systemctl", "--user", "list-timers",
                 "genesi-update.timer", "-o", "json"],
                check=False, capture_output=True, text=True, timeout=1,
            )
            next_check_output = get_next_check_duration_human_readable(
                timer_left.stdout.strip())
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            next_check_output = None
        if next_check_output:
            menu.append(_item(
                _("Next check in {time}").format(time=next_check_output), False))

        self._append_static(menu)
        menu.show_all()
        self.ind.set_menu(menu)

    def _append_static(self, menu):
        """The always-present bottom rows."""
        menu.append(Gtk.SeparatorMenuItem())
        launch = _item(_("Run Genesi-Update"), on_activate=arch_update)
        menu.append(launch)
        menu.append(_item(_("Check for updates"), on_activate=self.check))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(_item(_("Exit"), on_activate=Gtk.main_quit))
        # Keeps the Qt build's middle-click-to-launch behaviour.
        self.ind.set_secondary_activate_target(launch)

    def check(self):
        """Run `genesi-update --check`"""
        subprocess.Popen(["genesi-update", "--check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def main():
    """Start the tray."""
    GenesiUpdateTray(ICON_STATEFILE)
    Gtk.main()


if __name__ == "__main__":
    main()
