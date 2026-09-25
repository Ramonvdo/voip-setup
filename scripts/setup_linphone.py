#!/usr/bin/env python3
"""Point Linphone at the Telnyx line, on a caller's own machine, without the settings screen.

    py -3 setup_linphone.py --user <sipuser> --password "<password>" --check
    py -3 setup_linphone.py --user <sipuser> --password "<password>"

On a Mac or Linux, python3 in place of py -3.

WHY A SCRIPT AND NOT A SCREENSHOT OF THE SETTINGS

Typing SIP settings by hand fails quietly. The outbound proxy field wants a URI and
rejects a host and port; the media encryption has to match what the carrier requires or
the call sets up and dies with nothing on screen; and a half-finished account left behind
by an earlier attempt keeps erroring no matter what is fixed afterwards. Writing the
config file removes all three.

--check FIRST, ALWAYS

`--check` registers with the carrier directly, by speaking SIP, before Linphone is touched
at all. It answers the only question worth asking when something does not work: is this the
account, the network, or the app? A 200 means the first two are fine, so anything still
broken is the app, on that machine. It leaves no trace: the probe unregisters afterwards.

WHERE THE CONFIG LIVES
    Windows  %LOCALAPPDATA%\\linphone\\linphonerc
    macOS    ~/Library/Preferences/linphone/linphonerc
    Linux    ~/.config/linphone/linphonerc
Linphone rewrites that file when it exits, so it must be closed while this runs. The
script refuses to touch it otherwise, and backs the file up before writing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

DOMAIN = "sip.telnyx.com"
TLS_PORT = 5061


def config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ["LOCALAPPDATA"]) / "linphone" / "linphonerc"
    if system == "Darwin":
        # Not Application Support: on a Mac, Linphone keeps its logs and databases there
        # but reads its settings from Preferences. A file written to the wrong one is
        # simply ignored, and Linphone opens with no account.
        return Path.home() / "Library/Preferences/linphone/linphonerc"
    return Path.home() / ".config/linphone/linphonerc"


def linphone_is_running() -> bool:
    if platform.system() == "Windows":
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq linphone.exe"],
                             capture_output=True, text=True).stdout
        return "linphone.exe" in out
    # The process name, exactly. Matching whole command lines (-f) also caught anything that
    # merely mentions linphone, like an editor open on linphonerc or a tail on its log, and
    # then refused to write while Linphone was in fact closed.
    out = subprocess.run(["pgrep", "-x", "linphone"], capture_output=True, text=True)
    return out.returncode == 0


# --- the probe ---------------------------------------------------------------

def register_probe(user: str, password: str, domain: str = DOMAIN) -> bool:
    """Speak SIP to the carrier ourselves and print the status line it answers with."""
    def md5(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    tag, call_id = secrets.token_hex(6), secrets.token_hex(10) + "@probe"
    raw = socket.create_connection((domain, TLS_PORT), timeout=10)
    local_ip, local_port = raw.getsockname()
    try:
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=domain)
    except ssl.SSLCertVerificationError:
        # Python from python.org on a Mac has no root certificates until its "Install
        # Certificates.command" has run. It reads like a network fault, and it only stops
        # this probe: Linphone brings certificates of its own.
        raise SystemExit("\n  Python could not verify the carrier's certificate. With Python from\n"
                         "  python.org on a Mac, run \"Install Certificates.command\" in its folder\n"
                         "  under /Applications, or use Homebrew's python3, then try again.\n")
    sock.settimeout(10)

    def message(cseq: int, auth: str = "", expires: int = 60) -> bytes:
        head = [
            f"REGISTER sip:{domain} SIP/2.0",
            f"Via: SIP/2.0/TLS {local_ip}:{local_port};branch=z9hG4bK{secrets.token_hex(8)};rport",
            "Max-Forwards: 70",
            f"From: <sip:{user}@{domain}>;tag={tag}",
            f"To: <sip:{user}@{domain}>",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq} REGISTER",
            f"Contact: <sip:{user}@{local_ip}:{local_port};transport=tls>",
            f"Expires: {expires}",
            "User-Agent: telnyx-line-check/1.0",
        ]
        if auth:
            head.append(auth)
        return "\r\n".join(head + ["Content-Length: 0", "", ""]).encode()

    sock.sendall(message(1))
    first = sock.recv(8192).decode(errors="replace")
    print("  carrier answered:", first.splitlines()[0])
    challenge = re.search(r"WWW-Authenticate:\s*Digest\s*(.*)", first, re.I)
    if not challenge:
        print("  no authentication challenge, so the account was refused outright")
        sock.close()
        return False

    p = dict(re.findall(r'(\w+)="?([^",]+)"?', challenge.group(1)))
    realm, nonce, qop = p.get("realm", ""), p.get("nonce", ""), p.get("qop", "")
    # `opaque` identifies the node that issued the nonce, and RFC 3261 says a client
    # returns it untouched. Omitting it looked like an intermittent password problem:
    # roughly one attempt in three landed on the issuing node and succeeded, the rest
    # came back 401 with a fresh challenge. Echoing it makes every attempt succeed.
    opaque = f', opaque="{p["opaque"]}"' if p.get("opaque") else ""
    uri = f"sip:{domain}"
    ha1, ha2 = md5(f"{user}:{realm}:{password}"), md5(f"REGISTER:{uri}")
    if qop:
        cnonce, nc = secrets.token_hex(8), "00000001"
        resp = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
        auth = (f'Authorization: Digest username="{user}", realm="{realm}", nonce="{nonce}", '
                f'uri="{uri}", response="{resp}", algorithm=MD5, qop=auth, nc={nc}, '
                f'cnonce="{cnonce}"' + opaque)
    else:
        resp = md5(f"{ha1}:{nonce}:{ha2}")
        auth = (f'Authorization: Digest username="{user}", realm="{realm}", nonce="{nonce}", '
                f'uri="{uri}", response="{resp}", algorithm=MD5' + opaque)

    sock.sendall(message(2, auth))
    status = sock.recv(8192).decode(errors="replace").splitlines()[0]
    print("  after authenticating:", status)
    ok = status.startswith("SIP/2.0 200")
    if ok:
        sock.sendall(message(3, auth, expires=0))       # leave no registration behind
    sock.close()
    return ok


# --- the config --------------------------------------------------------------

def write_account(cfg: Path, user: str, password: str, display: str, domain: str) -> None:
    account = f"""
[auth_info_0]
username={user}
userid={user}
passwd={password}
realm={domain}
domain={domain}

[proxy_0]
reg_proxy=<sip:{domain}:{TLS_PORT};transport=tls>
reg_identity="{display}" <sip:{user}@{domain}>
reg_expires=600
reg_sendregister=1
publish=0
avpf=0
quality_reporting_enabled=0
realm={domain}
"""
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else "[sip]\n"
    backup = cfg.with_name(cfg.name + ".before-telnyx")
    if cfg.exists() and not backup.exists():
        shutil.copy2(cfg, backup)
        print(f"  backed up the old config to {backup.name}")

    # Any earlier half-finished account has to go, or Linphone keeps reporting its error.
    text = re.sub(r"\n\[(?:proxy|auth_info|account)_\d+\][^\[]*", "\n", text)
    # The carrier requires SRTP and answers an unencrypted offer with
    # "488 Media Encryption Required", which reaches the caller as a call that simply
    # will not connect. Linphone ships media_encryption=none, so this REPLACES the
    # value rather than only filling it in when absent: checking for the key and
    # leaving its value alone is how the first attempt at this failed.
    if re.search(r"^media_encryption=.*$", text, re.M):
        text = re.sub(r"^media_encryption=.*$", "media_encryption=srtp", text, flags=re.M)
    elif "[sip]\n" in text:
        text = text.replace("[sip]\n", "[sip]\nmedia_encryption=srtp\n", 1)
    else:
        text += "\n[sip]\nmedia_encryption=srtp\n"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text.rstrip("\n") + "\n" + account, encoding="utf-8")
    print(f"  account written to {cfg}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Configure Linphone for a Telnyx SIP line.")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--domain", default=DOMAIN)
    ap.add_argument("--display", default="")
    ap.add_argument("--check", action="store_true",
                    help="register with the carrier first and stop, touching nothing")
    args = ap.parse_args()

    print("\n1. asking the carrier directly, before touching Linphone")
    ok = register_probe(args.user, args.password, args.domain)
    if not ok:
        print("\n  The carrier refused this account from this machine, so Linphone was left\n"
              "  alone. Check the username and password, then the network.\n")
        raise SystemExit(1)
    print("  the account and the network are good")
    if args.check:
        print("\n  --check only, so nothing was changed.\n")
        return

    print("\n2. writing the account into Linphone's config")
    if linphone_is_running():
        raise SystemExit("\n  Linphone is open. Quit it completely (Cmd+Q on a Mac), including\n"
                         "  the tray icon, then run this again: it rewrites its config when it\n"
                         "  closes and would undo this.\n")
    write_account(config_path(), args.user, args.password,
                  args.display or args.user, args.domain)
    print("\n  Done. Start Linphone; it should show as registered within a few seconds.\n"
          "  Test it by calling your own mobile: the number the carrier owns shows on\n"
          "  the screen, not your own.\n")


if __name__ == "__main__":
    main()
