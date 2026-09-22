# voip-setup

A Claude Code skill that turns a verified [Telnyx](https://telnyx.com) account into a
working phone line: a local number, a softphone login with spending limits, and
[Linphone](https://www.linphone.org) configured on the machine that will make the calls.

Built for outbound calling, where the caller ID has to be local to the people being called
and the bill has to stay small.

## Why not a dialer product

| 10 hours of calling a month | This | A dialer seat |
|---|---|---|
| Number | $1.00 | included |
| Talk time | $0.007/min, about $0.42/hour | included |
| Seat | none | $19 to $33 |
| **Total** | **about $5** | **$19 to $33** |

A seat buys an app and hides two things worth controlling: what the line may dial, and what
it can spend. This sets both explicitly, because SIP credentials live in a softphone on
someone's laptop and stolen ones get used to dial premium-rate numbers overnight.

## Setup

Seven steps. Six are yours, once per account; the seventh is the skill.

1. [Create a Telnyx account](https://telnyx.com/sign-up/)
2. [Add your business details](https://portal.telnyx.com/#/account/general) — they must
   match the payment card, or verification stalls
3. [Upgrade and verify your identity](https://portal.telnyx.com/#/account/account-levels/upgrade/)
   — a trial account cannot buy numbers
4. [Create an API key](https://portal.telnyx.com/#/api-keys/)
5. Put it in `.env` as `TELNYX_API_KEY`
6. [Install Linphone](https://www.linphone.org/en/download/) on the calling machine
7. Run `/voip-setup` in Claude Code

That is the whole thing. No SIP settings screens.

## Installing the skill

```bash
git clone https://github.com/Ramonvdo/voip-setup
mkdir -p .claude/skills/voip-setup
cp -r voip-setup/SKILL.md voip-setup/scripts .claude/skills/voip-setup/
```

Then ask Claude Code for `/voip-setup`. The scripts also run on their own:

```bash
# see what it would buy, buy nothing
py -3 scripts/provision_telnyx.py --company Acme --area-code 512 --user acmecaller
py -3 scripts/provision_telnyx.py --company Acme --area-code 512 --user acmecaller --apply

# ask the carrier directly, change nothing
py -3 scripts/setup_linphone.py --user acmecaller --password "<password>" --check
py -3 scripts/setup_linphone.py --user acmecaller --password "<password>" --display "Alex"
```

Only `httpx` is needed for the provisioning script; the softphone script uses the standard
library alone.

## What it provisions, and why in that order

| Step | Why it is there |
|---|---|
| Outbound voice profile: allowed destinations, daily spend cap, max per-minute rate | A connection without a profile cannot call out at all, and these three are the whole safety story for credentials that live on a laptop |
| Credential connection, SRTP required | The login the softphone registers with |
| A local number in the area code you are calling | An unknown out-of-state number is answered far less often |
| The number pointed back at the connection | A callback rings the softphone, which US caller-ID rules expect |
| `ani_override` on the connection | A softphone offers its SIP username as the caller ID, which is not a phone number. Without this, calls are rejected or show nonsense |

Both scripts are idempotent: they find what exists by name, never order a second number, and
dry-run unless told otherwise.

## The traps

Every one of these was hit on a first run, and none of them say what they are.

| What you see | What it is |
|---|---|
| Intermittent `401` while registering, with the right password | The digest challenge carries an `opaque` value naming the node that issued the nonce, and RFC 3261 says the client echoes it back. Omit it and roughly one attempt in three succeeds, which reads exactly like a flaky password |
| The call rings out and dies, no error on screen | `488 Media Encryption Required`: the connection wants SRTP, the softphone offered plain RTP |
| Setting SRTP appears to do nothing | Linphone ships `media_encryption=none`. The value has to be replaced, not merely added when missing |
| "Outbound proxy uri is invalid" | Linphone wants `sip:sip.telnyx.com:5061;transport=tls`, not a bare host and port |
| Numbers come back as `+1512------` | The account is not verified. Not permissions, not the API |
| The password "does not work" | Generate it without look-alikes: no `I`, `l`, `1`, `O`, `0`. It gets typed by hand at least once |
| Registered, but calls to one country fail | The profile's allowed destinations, or its max per-minute rate. A mobile abroad can exceed a $0.05 cap while every domestic call sits far under it |

`transport_protocol` is not a server-side setting on a credential connection; it reads back
`null`. TLS is the softphone's own choice.

## Before you call anyone

- **Give each caller their own SIP user.** Two devices on one credential fight over inbound
  calls, and revoking one person then means rotating everybody's password. Run the
  provisioning again with a different `--user`.
- **Turn on auto-recharge.** At a zero balance, calls stop dead mid-morning.
- **A new number has no carrier reputation.** Low volume and answering callbacks keeps it
  out of the spam labels.
- **Recording is off.** Consent rules differ by US state and by country. If you switch it
  on, announce it on the call.
- **Cold calling is regulated.** Do-not-call rules, permitted hours and registration
  requirements vary by country and state. This tool provisions a phone line; it does not
  make your calling lawful.

## Scope

Telnyx and Linphone, on Windows, macOS and Linux. Other carriers use different APIs, though
the trap list mostly transfers: the caller ID override, the media encryption match and the
digest `opaque` are SIP problems, not Telnyx ones.

MIT licensed.
