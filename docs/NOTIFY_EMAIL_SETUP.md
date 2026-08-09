# Promptless email to realityremixed125@gmail.com — one-time setup (~5 min)

## Why this shape

`mcp__Gmail__create_draft` **cannot** be used from a scheduled run: it pops
*"Create Draft requests permission / Allow once / Deny"* on the owner's phone and the run
**stalls there** (proven runs 1-4; re-proven run 7 on 2026-08-09 with a screenshot). None of
the obvious escapes work:

| escape | verdict |
|---|---|
| Attach the Gmail connector to the Routine | already attached — dialog still pops |
| Allowlist `mcp__Gmail__create_draft` in `.claude/settings.json` | already allowlisted — dialog still pops |
| `create_trigger`'s explicit `connectors: ["Gmail"]` grant | **disabled for this organization** |
| SMTP (587/465) or IMAP (993) direct | **blocked** from the run container |
| Routine-level completion email | works, but goes to the Claude account address, not this Gmail |

What *does* work from the container is ordinary **HTTPS on 443** — which is exactly how
`notify_slack.sh` delivers. So email uses the same trick: a POST to a tiny web app that runs
as **your own Google account** and creates the message directly in that Gmail.

## Step 1 — create the Apps Script

Go to <https://script.google.com> → **New project**. Delete the placeholder and paste:

```javascript
function doPost(e) {
  var p = JSON.parse(e.postData.contents);
  var to      = p.to      || 'realityremixed125@gmail.com';
  var subject = p.subject || 'NFL Parlay';
  var body    = p.body    || '';

  if (p.mode === 'draft') {
    GmailApp.createDraft(to, subject, body);
  } else {
    GmailApp.sendEmail(to, subject, body);
  }
  return ContentService.createTextOutput('ok');
}
```

Name the project something like `nfl-parlay-mailer`.

## Step 2 — deploy it as a web app

**Deploy → New deployment** → gear icon → **Web app**, then set:

- **Execute as:** *Me* — this is what makes it run under your Google account
- **Who has access:** *Anyone* — required so the run container can POST without a Google login

Click **Deploy**, then **Authorize access** and approve the Gmail scope. This approval is
**one time, on your computer** — not per run. Copy the resulting URL; it looks like:

```
https://script.google.com/macros/s/AKfycb…/exec
```

> **Treat that URL as a secret.** Anyone holding it can send mail as you — it is a capability
> URL, exactly like a Slack incoming webhook. Never commit it. To revoke, delete the
> deployment in Apps Script.

## Step 3 — add it to the run environment

Add it as an environment variable on the **nfl-parlay-builder** environment (same place
`ODDS_API_KEY` and `SLACK_WEBHOOK_URL` live — *not* the repo):

```
GMAIL_WEBHOOK_URL = https://script.google.com/macros/s/AKfycb…/exec
```

A new value only reaches sessions started **after** it is saved.

## Step 4 — verify

`session_start.sh` §2b prints the channel state at the top of every run:

```
✓ GMAIL_WEBHOOK_URL present — tools/notify_email.sh will POST.
```

To test by hand from a session that has the variable:

```bash
tools/notify_email.sh --dry-run "test" "body"     # prints the JSON, sends nothing
tools/notify_email.sh "NFL mailer test" "hello"   # actually delivers
```

## Notes

- **Sent vs draft.** Default is a *sent* email. Pass `--draft` to create a Gmail draft
  instead; the owner stated either is acceptable, and sent is the lower-friction default
  since it arrives as a notification rather than waiting in a Drafts folder.
- **Recipient override.** `NFL_REPORT_TO` changes the destination without touching the
  script; it defaults to `realityremixed125@gmail.com`.
- **Failure is loud, absence is quiet.** Missing variable ⇒ `SKIP` + exit 0 (a session
  without the secret degrades gracefully). A real HTTP failure ⇒ exit 1 and the run must
  report it — never silently swallow it.
- **Domain allowlist.** `script.google.com` was reachable from the container on
  2026-08-09. If a future run reports a connection failure, confirm the environment's
  network policy still permits it.
