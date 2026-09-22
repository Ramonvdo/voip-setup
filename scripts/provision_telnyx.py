#!/usr/bin/env python3
"""Provision a calling line at Telnyx: spending limits, a softphone login, one number.

    py -3 provision_telnyx.py --company Acme --area-code 512 --user acmecaller
    py -3 provision_telnyx.py --company Acme --area-code 512 --user acmecaller --apply

NEEDS `TELNYX_API_KEY` in the .env at --env (default: the repo root walked up from here),
and a VERIFIED Telnyx account. An unverified account returns masked numbers (+1512------,
city ---) and can create everything except buy a number.

ORDER MATTERS, and each step exists for a reason:

  1. Outbound voice profile, carrying the spending limits. First, because a connection
     without one cannot call out, and because the limits are the point: SIP credentials
     live in a softphone on a caller's laptop, and stolen ones get used to dial
     premium-rate numbers overnight. A dialer seat hides this risk; raw SIP hands it to
     you.
  2. Credential connection: the username and password the softphone registers with,
     with SRTP required.
  3. A local number in the area code most of the leads are in. An unknown out-of-state
     number is answered far less often.
  4. The number pointed at the connection, so a callback rings the softphone.
  5. ani_override on the connection, so every outbound call shows that number. Without
     it the softphone offers its SIP username as the caller ID, which is not a phone
     number, and calls are rejected or show something meaningless.

Idempotent: re-running finds what exists by name and fills gaps. It never orders a second
number. If the connection already exists its password is rotated, because a password is
only ever visible at the moment it is set.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import secrets
import sys

# No I, l, 1, O or 0: this password gets typed by hand at least once.
ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
API = "https://api.telnyx.com/v2"


def find_env(explicit: str | None) -> pathlib.Path:
    if explicit:
        return pathlib.Path(explicit)
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    raise SystemExit("no .env found; pass --env")


def read_env(path: pathlib.Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def put_env(path: pathlib.Path, name: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, re.M):
        text = re.sub(rf"^{name}=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    import httpx

    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True, help="names the profile and connection")
    ap.add_argument("--area-code", required=True, help="e.g. 512 for Austin")
    ap.add_argument("--user", required=True, help="SIP username, 4-32 letters and digits")
    ap.add_argument("--display", default="", help="caller's name, for the softphone")
    ap.add_argument("--destinations", default="US,CA",
                    help="countries the line may dial; add the caller's own for testing")
    ap.add_argument("--daily-limit", default="5.00")
    ap.add_argument("--max-rate", type=float, default=0.05, help="per minute, a fraud guard")
    ap.add_argument("--env", default=None)
    ap.add_argument("--caller-id-var", default="VOIP_CALLER_ID")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9]{4,32}", args.user):
        raise SystemExit("--user must be 4-32 characters, letters and digits only")

    env_path = find_env(args.env)
    key = read_env(env_path).get("TELNYX_API_KEY", "")
    if not key:
        raise SystemExit(f"TELNYX_API_KEY is not in {env_path}")

    profile_name = f"{args.company} outbound"
    connection_name = f"{args.company} softphone"
    tx = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key}"}, timeout=60)

    def explain(resp):
        try:
            errs = resp.json().get("errors") or []
        except Exception:
            return resp.text[:300]
        return "; ".join(f"{e.get('code','')} {e.get('title','')}: {e.get('detail','')}".strip()
                         for e in errs) or resp.text[:200]

    def get(path, **params):
        r = tx.get(path, params=params)
        if r.status_code >= 300:
            raise SystemExit(f"GET {path} failed {r.status_code}: {explain(r)}")
        return r.json().get("data")

    def post(path, payload):
        r = tx.post(path, json=payload)
        if r.status_code >= 300:
            raise SystemExit(f"POST {path} failed {r.status_code}: {explain(r)}")
        return r.json().get("data")

    def patch(path, payload):
        r = tx.patch(path, json=payload)
        if r.status_code >= 300:
            raise SystemExit(f"PATCH {path} failed {r.status_code}: {explain(r)}")
        return r.json().get("data")

    balance = get("/balance")
    print(f"account balance: {balance.get('balance')} {balance.get('currency')} "
          f"| credit limit {balance.get('credit_limit')}")
    if not args.apply:
        print("\n  DRY RUN. Nothing is created or bought. Re-run with --apply.\n")

    # 1. spending limits
    profiles = get("/outbound_voice_profiles", **{"page[size]": 50})
    profile = next((p for p in profiles if p.get("name") == profile_name), None)
    destinations = [d.strip().upper() for d in args.destinations.split(",") if d.strip()]
    if profile:
        print(f"voice profile: '{profile_name}' exists ({profile['id']})")
    else:
        print(f"voice profile: would create '{profile_name}' "
              f"({'/'.join(destinations)} only, ${args.daily_limit}/day, max ${args.max_rate}/min)")
        if args.apply:
            profile = post("/outbound_voice_profiles", {
                "name": profile_name, "traffic_type": "conversational",
                "service_plan": "global", "enabled": True,
                "usage_payment_method": "rate-deck",
                "whitelisted_destinations": destinations,
                "daily_spend_limit": args.daily_limit,
                "daily_spend_limit_enabled": True,
                "max_destination_rate": args.max_rate,
                "concurrent_call_limit": 2,
            })
            print(f"  created {profile['id']}")

    # 2. the softphone login
    password = ""
    connections = get("/credential_connections", **{"page[size]": 50})
    connection = next((c for c in connections
                       if c.get("connection_name") == connection_name), None)
    if connection:
        print(f"connection: '{connection_name}' exists ({connection['id']}), "
              f"user {connection.get('user_name')}")
        if args.apply:
            password = "".join(secrets.choice(ALPHABET) for _ in range(20))
            patch(f"/credential_connections/{connection['id']}", {
                "password": password,
                "outbound": {"outbound_voice_profile_id": profile["id"]},
            })
            print("  password rotated, voice profile attached")
    else:
        print(f"connection: would create '{connection_name}' for user {args.user}")
        if args.apply:
            password = "".join(secrets.choice(ALPHABET) for _ in range(20))
            connection = post("/credential_connections", {
                "connection_name": connection_name, "user_name": args.user,
                "password": password, "active": True,
                "anchorsite_override": "Latency",
                # Required at both ends. A softphone offering plain RTP gets
                # "488 Media Encryption Required" and the call never connects.
                "encrypted_media": "SRTP",
                "outbound": {"outbound_voice_profile_id": profile["id"]},
                "inbound": {"sip_region": "US"},
            })
            print(f"  created {connection['id']}")

    # 3. the number
    owned = get("/phone_numbers", **{"page[size]": 100})
    number = next((n for n in owned
                   if (n.get("phone_number") or "").startswith(f"+1{args.area_code}")), None)
    if number:
        print(f"number: {number['phone_number']} already owned")
    else:
        available = get("/available_phone_numbers", **{
            "filter[country_code]": "US",
            "filter[national_destination_code]": args.area_code,
            "filter[features][]": "voice", "filter[limit]": 5,
        })
        options = [n["phone_number"] for n in (available or [])]
        if not options:
            raise SystemExit(f"no numbers free in area code {args.area_code}")
        if "-" in options[0]:
            raise SystemExit(
                "Telnyx returned masked numbers, which means the account is not verified "
                "yet. Finish identity verification and add a payment method, then re-run.")
        print(f"number: would order {options[0]} (also free: {', '.join(options[1:3])})")
        if args.apply:
            order = post("/number_orders", {"phone_numbers": [{"phone_number": options[0]}],
                                            "connection_id": connection["id"]})
            print(f"  ordered {options[0]} (status {order.get('status')})")
            owned = get("/phone_numbers", **{"page[size]": 100})
            number = next((n for n in owned if n.get("phone_number") == options[0]), None)

    # 4 and 5. route callbacks in, and force the caller ID out
    if args.apply and number and connection:
        patch(f"/phone_numbers/{number['id']}", {"connection_id": connection["id"]})
        patch(f"/credential_connections/{connection['id']}", {
            "outbound": {"outbound_voice_profile_id": profile["id"],
                         "ani_override": number["phone_number"],
                         "ani_override_type": "always", "localization": "US"},
        })
        put_env(env_path, args.caller_id_var, number["phone_number"])
        print(f"callbacks ring the softphone; every outbound call shows "
              f"{number['phone_number']}")
        print(f"{args.caller_id_var} written to {env_path}")

    if args.apply and password:
        print("\n  SOFTPHONE LOGIN")
        print("    username :", args.user)
        print("    password :", password)
        print("    domain   : sip.telnyx.com")
        print("\n  Shown once. Hand it to setup_linphone.py, or send it over a private "
              "channel.\n")
    elif not args.apply:
        print("\n  Re-run with --apply to provision.\n")


if __name__ == "__main__":
    main()
