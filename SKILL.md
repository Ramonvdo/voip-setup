---
name: voip-setup
description: Set up a cold-calling phone line end to end — buy a local number at Telnyx, create the softphone login with spending limits, and configure Linphone on the caller's machine so it registers and dials with the right caller ID. Also adds a second caller to an existing line, rotates a leaked password, or diagnoses a line that will not register or will not connect a call. Needs only a verified Telnyx account with TELNYX_API_KEY in .env and Linphone installed. Triggered by /voip-setup.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, AskUserQuestion
---

# /voip-setup — a working phone line in one run

A dialer seat (Quo, JustCall, Aircall) costs $19 to $33 a month per caller and hides two
things you should control: what the line is allowed to dial, and what it costs. This builds
the same call out of a Telnyx number and a free softphone for **$1 a month plus $0.007 a
minute**, about 42 cents an hour of talking.

Everything here was learned by getting it wrong once. Each trap below cost real time on a
first run; none of them announce themselves.

## What the human does first

Only these, and only once per account:

1. [Create a Telnyx account](https://telnyx.com/sign-up/)
2. [Fill in the business details](https://portal.telnyx.com/#/account/general) — legal
   name, registered address, and the company registration and tax numbers for the
   country. They must match the payment card, or verification stalls for days.
3. [Upgrade and verify identity](https://portal.telnyx.com/#/account/account-levels/upgrade/)
   — the account stays a trial until a payment method is on it, and a trial **cannot buy
   numbers**.
4. [Create an API key](https://portal.telnyx.com/#/api-keys/) (v2)
5. Put it in `.env` as `TELNYX_API_KEY`
6. [Install Linphone](https://www.linphone.org/en/download/) on the machine that will call
7. Run this skill

Nothing else is theirs to do. Do not send them to the settings screens.

## What you do

### 1. Establish the facts before touching anything

- **Where are the leads?** The caller ID must be local to them: an unknown out-of-state
  number is answered far less often. If the project has a lead list, derive the area code
  from it rather than asking:
  `SELECT substring(regexp_replace(phone,'\D','','g') from 2 for 3), count(*) ... GROUP BY 1`
  Otherwise ask for the area code.
- **Who is calling?** One SIP user per person. Two devices on one credential fight over
  inbound calls, so never hand an existing login to a second caller: run the provisioning
  again with a different `--user` to mint them their own.
- **Is the account verified?** `GET /v2/balance` proves the key. Masked numbers in a search
  (`+1512------`, city `---`) mean verification is unfinished; stop and say so, because
  nothing can be bought until it is.

### 2. Provision the line

```bash
py -3 .claude/skills/voip-setup/scripts/provision_telnyx.py \
    --company <Company> --area-code <512> --user <sipusername>          # dry run
py -3 .claude/skills/voip-setup/scripts/provision_telnyx.py \
    --company <Company> --area-code <512> --user <sipusername> --apply
```

On a Mac or Linux, `python3` in place of `py -3`, here and below.

Dry-run first and show the user what it would buy. The script is idempotent: it finds what
exists by name, never orders a second number, and rotates the password when the connection
already exists, because a password is only visible at the moment it is set.

It creates, in this order and for these reasons:

| | Why it is first |
|---|---|
| Outbound voice profile with **allowed destinations, a daily spend cap and a max per-minute rate** | A connection without a profile cannot call out at all. And these three are the whole safety story: SIP credentials sit in a softphone on someone's laptop, and stolen ones get used to dial premium-rate numbers overnight. |
| Credential connection, **SRTP required** | The login the softphone registers with. |
| A local number in the lead area code | Answered far more often than an out-of-state one. |
| Number pointed at the connection | A prospect ringing back makes the softphone ring. US caller-ID rules expect a number you can call back. |
| `ani_override` on the connection | **Never skip.** A softphone offers its SIP username as the caller ID, which is not a phone number: without the override calls are rejected or show nonsense. It must be a number this account owns — passing a third party's number through is caller ID spoofing, a federal offence in the US. |

### 3. Configure the softphone

```bash
py -3 .claude/skills/voip-setup/scripts/setup_linphone.py \
    --user <sipusername> --password "<password>" --check        # asks the carrier, changes nothing
py -3 .claude/skills/voip-setup/scripts/setup_linphone.py \
    --user <sipusername> --password "<password>" --display "<Name>"
```

`--check` speaks SIP to Telnyx itself and answers the only question worth asking when
something breaks: is this the account, the network, or the app? A `200 OK` means the first
two are fine. Run it before every configuration attempt, and first when diagnosing.

Then the writer puts the account straight into Linphone's own config file, because typing
these settings by hand fails quietly in at least three ways (below). It refuses to run
while Linphone is open (Linphone rewrites that file when it exits), backs the file up, and
strips half-finished accounts from earlier attempts. On a Mac, `osascript -e 'quit app
"Linphone"'` closes it: it answers with error -128 and quits anyway, so confirm with
`pgrep -x linphone` rather than trusting the error.

### 4. Prove it works, in this order

1. **Registered:** start Linphone, then read its log for `LinphoneRegistrationOk`:
   `%LOCALAPPDATA%\linphone\logs\linphone1.log` on Windows,
   `~/Library/Application Support/linphone/logs/linphone1.log` on a Mac.
2. **A call connects:** have the user dial their own mobile. The screen must show the
   bought number, not their own. Add their own country to `--destinations` for this, and
   say it can be removed afterwards.
3. **A callback rings:** have them ring the bought number from their mobile.

If a call fails, the log names the cause; grep it for `SIP/2.0 4` and `Reason:`. Never
guess twice in a row — read the log.

## The traps, all of which look like something else

| What you see | What it actually is |
|---|---|
| Intermittent `401` on registration, correct password | The digest challenge carries an `opaque` value naming the node that issued the nonce. RFC 3261 says a client echoes it back untouched. Omit it and roughly one attempt in three succeeds, which reads exactly like a flaky password or a lockout. Real softphones do this correctly; hand-written probes do not. |
| Call rings out, never connects, no error on screen | `488 Media Encryption Required`. The connection demands SRTP and the softphone offered plain RTP. |
| Configuring SRTP appears to do nothing | Linphone ships `media_encryption=none` in `linphonerc`. A writer that only adds the key when missing leaves the wrong value in place: **replace the value**, do not merely insert it. |
| "Outbound proxy uri is invalid" | Linphone wants a URI, not a host: `sip:sip.telnyx.com:5061;transport=tls`, or leave the field empty once domain and transport are set. |
| Masked numbers, `+1512------` | The account is not verified. Not a permissions problem, not an API problem. |
| The password "does not work" | Generate without look-alikes (no `I`, `l`, `1`, `O`, `0`). It gets typed by hand at least once. |
| Registered, but calls to one country fail | `whitelisted_destinations` or `max_destination_rate` on the profile. A mobile abroad can exceed a $0.05/min cap while every US call sits far under it. |
| On a Mac, Linphone opens with no account after the settings were written | It reads `~/Library/Preferences/linphone/linphonerc`. `~/Library/Application Support/linphone/` holds only its logs and databases, and a config written there is silently ignored. |
| On a Mac, `--check` fails with `CERTIFICATE_VERIFY_FAILED` | Python from python.org ships without root certificates until its `Install Certificates.command` has been run. Not the network, not the account: Linphone brings its own certificates, so only the probe is affected. |

`transport_protocol` is not a server-side setting on a credential connection; it reads back
`null`. TLS is the softphone's own choice, so it belongs in the config, not the API call.

## Finish by telling them

- The settings table: username, password, `sip.telnyx.com`, TLS, SRTP, and the number that
  shows on the prospect's screen. Say the password is shown once and should travel over a
  private channel.
- **Turn on auto-recharge.** At a zero balance calls stop dead mid-morning.
- A brand-new number has no carrier reputation. Low volume and answering callbacks keeps it
  out of the spam labels; blasting it ruins it.
- Recording is off deliberately. Consent rules differ by US state and by country, and that
  is an argument nobody needs over a cheap product. If it is ever switched on, it gets an
  announcement first.

## Adding a second caller later

Run the provisioning again with a new `--user` and the same `--company`. It reuses the
profile and the number, mints a separate login, and leaves the first caller alone. Then run
the Linphone setup on their machine. Revoking one person later is then deleting one
credential connection, not rotating everybody's password.
