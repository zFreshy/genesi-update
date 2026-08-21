#!/bin/bash

# tray.sh: Start the Genesi-Update systray applet
# https://github.com/Antiz96/genesi-update
# SPDX-License-Identifier: GPL-3.0-or-later

if [ "${2}" == "--enable" ]; then
	# shellcheck disable=SC2154
	if [ -f "${XDG_DATA_HOME}/applications/${name}-tray.desktop" ]; then
		tray_desktop_file="${XDG_DATA_HOME}/applications/${name}-tray.desktop"
	elif [ -f "${HOME}/.local/share/applications/${name}-tray.desktop" ]; then
		tray_desktop_file="${HOME}/.local/share/applications/${name}-tray.desktop"
	elif [ -f "${XDG_DATA_DIRS}/applications/${name}-tray.desktop" ]; then
		tray_desktop_file="${XDG_DATA_DIRS}/applications/${name}-tray.desktop"
	elif [ -f "/usr/local/share/applications/${name}-tray.desktop" ]; then
		tray_desktop_file="/usr/local/share/applications/${name}-tray.desktop"
	elif [ -f "/usr/share/applications/${name}-tray.desktop" ]; then
		tray_desktop_file="/usr/share/applications/${name}-tray.desktop"
	else
		error_msg "$(eval_gettext "\${_name} tray desktop file not found")"
		exit 10
	fi

	tray_desktop_file_autostart="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/${name}-tray.desktop"

	if [ -f "${tray_desktop_file_autostart}" ]; then
		error_msg "$(eval_gettext "The '\${tray_desktop_file_autostart}' file already exists")"
		exit 10
	else
		mkdir -p "${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/" || exit 10
		cp "${tray_desktop_file}" "${tray_desktop_file_autostart}" || exit 10
		info_msg "$(eval_gettext "The '\${tray_desktop_file_autostart}' file has been created, the \${_name} systray applet will be automatically started at your next log on\nTo start it right now, you can launch the \"\${_name} Systray Applet\" application from your app menu")"
	fi
else
	# shellcheck disable=SC2154
	if [ ! -f "${statedir}/tray_icon" ]; then
		icon_up-to-date
	fi

	# shellcheck disable=SC2154
	if [ ! -f "${statedir}/last_updates_check" ]; then
		touch "${statedir}/last_updates_check"
	fi

	# shellcheck disable=SC2154
	exec {fd_tray}>"${tmpdir}/tray.lock"

	if ! flock -n "${fd_tray}"; then
		# NOT an error: the applet is deliberately launched from two places, so
		# it comes up on every desktop Genesi ships. The systemd user service
		# covers systemd-aware Wayland compositors; /etc/xdg/autostart covers
		# the classic desktops that never reach graphical-session.target. On any
		# session that honours BOTH, one of them wins this lock and the other
		# arrives here.
		#
		# Exiting non-zero made that normal outcome look like a failure: the
		# service retried, hit its start limit, and left "Failed to start Launch
		# the Genesi-Update systray applet" in every journal, next to a tray
		# icon that was working fine. The applet is running -- that is success.
		info_msg "$(eval_gettext "The \${_name} systray applet is already running")"
		exit 0
	fi

	# shellcheck disable=SC2154
	"${libdir}/tray.py" || exit 3
fi
