#!/usr/bin/env bash

# Applied once, after run_once_macos-defaults.sh. Re-run manually with:
# chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

echo "→ Applying server-only macOS defaults..."

# Enable SSH (Remote Login) for headless administration.
# Eg. System Settings → General → Sharing → Remote Login
sudo systemsetup -setremotelogin on

# Enable Screen Sharing/VNC for remote GUI access.
# Eg. System Settings → General → Sharing → Screen Sharing
sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
  -activate -configure -access -on -restart -agent -privs -all

# Never sleep — no one's around to wake it.
# Eg. System Settings → Energy → Options → Sleep: Never
sudo systemsetup -setcomputersleep Never

# Don't sleep even with the display off.
# Eg. System Settings → Energy → Options → "Prevent automatic sleeping when the display is off"
sudo pmset -a disablesleep 1

# Auto-restart after a power failure — no one's around to press the button.
# Eg. System Settings → Energy → Options → "Restart automatically after a power failure"
sudo pmset -a autorestart 1

# Auto-install security updates.
# Eg. System Settings → General → Software Update → Automatic Updates
sudo softwareupdate --schedule on
sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool true
sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool true
sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate CriticalUpdateInstall -bool true
sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate ConfigDataInstall -bool true

# Enable auto-login so the Mac mini recovers unattended after a power loss.
#
# Security:
# - Requires FileVault to be disabled.
# - Stores an obfuscated (not encrypted) password in /etc/kcpassword,
#   which can be recovered by someone with sufficient system access.
# - Intended only for trusted machines where unattended recovery is desired.
#
# The password is prompted interactively and is never stored in this repository.
#
# Eg. System Settings → General → Login Items & Extensions → Automatic login
read -r -s -p "Enter password for $USER to enable auto-login: " AUTOLOGIN_PASSWORD
echo

kcpassword=$(perl -e '
my $key = pack("H*", "7d895223d2bcddeaa3b91f");
my $pw = $ARGV[0] . "\0";
$pw .= "\0" x ((length($key) - length($pw) % length($key)) % length($key));
my $out = "";
for (my $i = 0; $i < length($pw); $i++) {
    $out .= chr(ord(substr($pw, $i, 1)) ^ ord(substr($key, $i % length($key), 1)));
}
print $out;
' "$AUTOLOGIN_PASSWORD")

unset AUTOLOGIN_PASSWORD

printf '%s' "$kcpassword" | sudo tee /etc/kcpassword > /dev/null
unset kcpassword

sudo chmod 600 /etc/kcpassword
sudo defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser -string "$USER"

echo "✓ Server-only macOS defaults applied"