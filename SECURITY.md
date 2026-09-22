# Security

## Reporting a vulnerability

Open a [security advisory](https://github.com/Ramonvdo/voip-setup/security/advisories/new)
rather than a public issue. Expect a reply within a week.

## What this tool touches

It talks to one API and writes two files. Worth knowing exactly what that means:

- **Your Telnyx API key** is read from `.env` and never printed, logged or committed.
  `.env` is gitignored; `.env.example` holds names only.
- **The SIP password** is generated locally, sent to Telnyx over HTTPS, and printed to your
  terminal exactly once. It is not stored by these scripts. It does end up in the softphone's
  own config file, which is how every softphone works.
- **`linphonerc`** is rewritten in place, after a backup alongside it. The scripts refuse to
  run while Linphone is open, because Linphone overwrites that file when it exits.
- **Nothing is sent anywhere else.** No telemetry, no analytics, no third-party endpoints.

## The risk worth understanding

SIP credentials on a laptop are a theft target: stolen ones are used to dial premium-rate
international numbers, often overnight, and the bill lands on the account owner. That is why
the provisioning script always sets three limits on the outbound voice profile — allowed
destinations, a daily spend cap, and a maximum per-minute rate — rather than leaving them at
the carrier's defaults.

If credentials leak, rotate them: re-run the provisioning script with the same `--company`
and `--user`. It replaces the password on the existing connection, and the old one stops
working immediately.

Give each caller their own SIP user. Sharing one login means revoking any one person
requires changing everyone's password.
