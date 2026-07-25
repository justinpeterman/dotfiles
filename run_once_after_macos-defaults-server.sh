#!/usr/bin/env bash

# Applied once, after run_once_macos-defaults.sh. Re-run manually with:
# chezmoi state delete-bucket --bucket=scriptState

set -euo pipefail

echo "→ Applying server-only macOS defaults..."

# Enable SSH (Remote Login) for headless administration.
# Eg. System Settings → General → Sharing → Remote Login
sudo systemsetup -setremotelogin on || echo "⚠ setremotelogin failed — your terminal may need Full Disk Access; enable Remote Login manually if SSH is not on"

# Enable full Remote Management (ARD) for all users — broader than plain Screen Sharing.
# `kickstart` is deprecated since macOS 11 but still functional.
# Eg. System Settings → General → Sharing → Screen Sharing
sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
  -activate -configure -access -on -restart -agent -privs -all || echo "⚠ ARDAgent kickstart failed (continuing)"

# Never sleep — no one's around to wake it.
# Eg. System Settings → Energy → Options → Sleep: Never
sudo systemsetup -setcomputersleep Never || true   # systemsetup can emit a benign -99 and exit non-zero

# Don't sleep even with the display off.
# Eg. System Settings → Energy → Options → "Prevent automatic sleeping when the display is off"
sudo pmset -a disablesleep 1

# Auto-restart after a power failure — no one's around to press the button.
# Eg. System Settings → Energy → Options → "Restart automatically after a power failure"
sudo pmset -a autorestart 1

# Auto-install security updates.
# Eg. System Settings → General → Software Update → Automatic Updates
# Note: on modern macOS `softwareupdate --schedule on` prints success but can
# still exit non-zero, which under `set -e` would abort the rest of this script.
sudo softwareupdate --schedule on || true
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
# Read from the controlling terminal, not stdin: when this repo is bootstrapped
# via `curl … | bash`, stdin is the consumed script pipe (EOF), which would make
# `read` fail under `set -e`.
if fdesetup status | grep -q "FileVault is On"; then
  echo "⚠ FileVault is On — auto-login cannot work while FileVault is enabled; skipping auto-login setup."
else
  read -r -s -p "Enter password for $USER to enable auto-login: " AUTOLOGIN_PASSWORD < /dev/tty
  echo
  read -r -s -p "Confirm password: " AUTOLOGIN_PASSWORD_CONFIRM < /dev/tty
  echo

  if [[ -z "$AUTOLOGIN_PASSWORD" || "$AUTOLOGIN_PASSWORD" != "$AUTOLOGIN_PASSWORD_CONFIRM" ]]; then
    echo "⚠ Password was empty or the two entries did not match — skipping auto-login setup." >&2
    unset AUTOLOGIN_PASSWORD AUTOLOGIN_PASSWORD_CONFIRM
  else
    unset AUTOLOGIN_PASSWORD_CONFIRM

    # Pass the password via stdin, not argv, so it never appears in `ps`.
    kcpassword=$(printf '%s' "$AUTOLOGIN_PASSWORD" | perl -e '
my $key = pack("H*", "7d895223d2bcddeaa3b91f");
my $pw = do { local $/; <STDIN> } . "\0";
$pw .= "\0" x ((length($key) - length($pw) % length($key)) % length($key));
my $out = "";
for (my $i = 0; $i < length($pw); $i++) {
    $out .= chr(ord(substr($pw, $i, 1)) ^ ord(substr($key, $i % length($key), 1)));
}
print $out;
')

    unset AUTOLOGIN_PASSWORD

    # Create the file with 0600 BEFORE writing, so there is no world-readable window.
    sudo install -m 600 /dev/null /etc/kcpassword
    printf '%s' "$kcpassword" | sudo tee /etc/kcpassword > /dev/null
    unset kcpassword

    sudo chmod 600 /etc/kcpassword
    sudo defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser -string "$USER"
    echo "  ✓ Auto-login configured for $USER"
  fi
fi

echo "✓ Server-only macOS defaults applied"
