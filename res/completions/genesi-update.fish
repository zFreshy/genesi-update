complete -c genesi-update -f

complete -c genesi-update -s c -l check -d 'Check for available updates'
complete -c genesi-update -s l -l list -d 'Display the list of pending updates'
complete -c genesi-update -s d -l devel -d 'Include AUR development packages updates'
complete -c genesi-update -s n -l news -d 'Display latest Arch news'
complete -c genesi-update -s s -l services -d 'Check for services requiring a post upgrade restart'
complete -c genesi-update -s D -l debug -d 'Display debug traces'
complete -c genesi-update -l gen-config -d 'Generate a default / example configuration file'
complete -c genesi-update -l show-config -d 'Display the current configuration file'
complete -c genesi-update -l edit-config -d 'Edit the current configuration file'
complete -c genesi-update -l tray -d 'Launch the Genesi-Update systray applet'
complete -c genesi-update -s h -l help -d 'Display the help message'
complete -c genesi-update -s V -l version -d 'Display version information'
