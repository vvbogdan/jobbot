# jobbot — fast push notifications for new jobs (DOU + Djinni) + resume auto-tailoring

Python 3.8+. Reads public RSS feeds (no login needed). One external dependency — `reportlab`
(PDF generation).

## Quick start (deploy on Render, ~10 minutes)
1. Edit `bot/config.py` — set your own search profiles (see section 11).
2. Create a Telegram bot via @BotFather, get the **token** (see section 1).
3. Get your **chat id** (see section 1).
4. Get an Anthropic API key at console.anthropic.com (see section 2).
5. Push the repo to your own GitHub account.
6. On [render.com](https://render.com), create a new **Web Service** from that repo.
7. Build command: `pip install -r requirements.txt`.
8. Start command: `python3 jobbot.py --loop 60`.
9. Add the environment variables `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
   `ANTHROPIC_API_KEY` (see the full table in section 12).
10. Deploy. Send `/start` to the bot in Telegram to confirm it's alive.
11. (Optional, recommended) Set up Firebase so state survives a disk wipe (section 7b).
12. (Optional, recommended) Set up UptimeRobot so Render doesn't fall asleep (section 9).

Done — the bot now checks for new jobs every minute and pushes matches to your Telegram chat.

## 1. Telegram bot (2 minutes)
1. In Telegram, message @BotFather → `/newbot` → you'll get a **token**.
2. Send your bot anything (`/start`).
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` → find `"chat":{"id":123456789` — this is your **chat id**.
4. **Protection:** the bot only responds to `TELEGRAM_CHAT_ID` set in the environment variables —
   all commands/buttons from any other chat (someone messaging the bot directly, knowing its
   username) are completely ignored, with no response at all. Don't share the token with anyone —
   it's the only thing that ties the bot specifically to you.

## 2. Anthropic API key (for the "Tailor resume" button)
1. Go to console.anthropic.com → create an API key.
2. This is a separate key from a Claude.ai subscription; billing is per-token (tailoring one
   resume costs a fraction of a cent).

## 3. Installation and running
```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="123:ABC..."
export TELEGRAM_CHAT_ID="123456789"
export ANTHROPIC_API_KEY="sk-ant-..."

python3 jobbot.py --test          # test push
python3 jobbot.py --dry-run       # see matches without sending
python3 jobbot.py --loop 60       # run continuously: pushes + listens for the "Tailor resume" button
```
Alternative/extra push channel: `export NTFY_TOPIC=my-secret-topic` + the ntfy app.

## 4. How the "📄 Tailor resume" and "✉️ Cover letter" buttons work
- Every push comes with buttons. Tap "Tailor resume" → the bot takes the base resume matching
  the job's profile, sends it together with the job text to the Claude API, and returns a
  finished PDF to the same chat in ~10-20 seconds.
- "✉️ Cover letter" next to it — same idea, but generates a short (120-200 word) cover letter
  for the same job and sends it as a plain text message.
- Both buttons stick strictly to facts from the base resume — nothing is invented.
- The result is cached per job: clicking the same button again shows the already-generated
  version instantly, **without** a new Claude API call (saves both time and money). There's a
  separate "🔄 Regenerate" button under the result if you want a fresh version.
- **Base resume:** the repo's `bot/resumes.py` is a public example (a made-up "Frontend" one),
  since the repo is public. Put your real resume in `bot/resumes_local.py` next to it (same
  `BASE_RESUMES` shape) — this file is in `.gitignore`, never committed, and `jobbot.py`
  automatically uses it instead of `bot/resumes.py` when it exists. Update the text in
  `bot/resumes_local.py` whenever your experience changes.
- Default model: `claude-sonnet-5`. Change it via the `ANTHROPIC_MODEL` environment variable.
- Without `ANTHROPIC_API_KEY` the buttons still work but reply that the feature is disabled —
  the rest of the bot (pushes) keeps working as usual.

## 5. Priority, reminders, stats, digest
- Jobs with words like AI agentic / Claude Code / AI-enabled etc. get a **⭐** mark and are
  sent first within a given run.
- The **🍎 iOS** profile is always priority (⭐), regardless of keywords or location.
- For the **🔌 Embedded / Linux** profile: a Lviv or remote location also raises priority (⭐) —
  such jobs go first both in pushes and in `/pending`/checkboxes/cards. Kyiv gets a separate
  badge **🏙** (no priority boost), so it's visually distinct without getting lost in the rest
  of the list.
- Salary (if present in the title/description) is shown right in the push — there's no
  filtering by amount.
- Application deadline (if mentioned in the description — "until Oct 15", "deadline:",
  "apply by October 20" etc.) is shown next to the salary as "⏳ by …".
- The **"✅ Applied"** button under a push marks the job as closed. If you don't tap it —
  after `REMINDER_HOURS` hours (default 20) the bot reminds you itself. `REMINDER_HOURS=0`
  disables this.
- The **"🚫 Not interested"** button next to it removes the job from reminders and from
  "Awaiting response" in `/stats`, but does **not** count it as applied (a separate "Not
  interested" counter is kept in stats).
- Company name (best-effort, parsed from the job title/description) is shown right in the
  push whenever it could be recognized.
- The `/stats` Telegram command — how many jobs were sent and how many you applied to over
  7 days, broken down by profile. The bot sends the same text itself once a week (default
  Sunday, 19:00 in `TZ_NAME`) — see `DIGEST_WEEKDAY`/`DIGEST_HOUR` below.
- Jobs marked as closed in the text ("position closed", "вакансія закрита" etc.) aren't shown
  and never enter the cache/reminders at all.
- If the same job appears on both DOU and Djinni (identical title) — you get one push instead
  of two, labeled "DOU + Djinni".

## 6. Quiet hours (no pushes at night)
- Within the `QUIET_HOURS_START`..`QUIET_HOURS_END` window (default 01:00–07:00 in `TZ_NAME`,
  default `Europe/Kyiv`), new jobs aren't pushed immediately — they pile up.
- As soon as quiet hours end, the bot sends a "🌅 Night digest" as one header message and then
  delivers everything that piled up as regular pushes (with all the buttons).
- To disable quiet hours entirely: set `QUIET_HOURS_START` = `QUIET_HOURS_END` (e.g. both `0`).
- `--dry-run` always ignores quiet hours — handy for testing.

## 7. Backup and state restore
- **Render doesn't guarantee a persistent disk on this plan** — the disk can be wiped on
  every redeploy/restart (and the service itself can go to sleep and restart after a period of
  no traffic). Without a backup this means losing the entire history ("seen"/"jobs"/application
  stats) and re-spamming jobs you've already seen — this is exactly why jobs in `/pending` could
  always show "0h ago": the disk got wiped and the bot pushed them again.
- The bot sends `state.json` as a file to the same Telegram chat every `BACKUP_INTERVAL_HOURS`
  hours (default 24), and on the `/backup` command — manually, any time. Every backup sent is
  immediately **pinned** in the chat (`pinChatMessage`).
- **Auto-restore on startup** — when the bot starts (`--loop`) and the local `state.json` is
  empty (the typical situation after a disk wipe), it checks the pinned message
  in the chat itself (`getChat` → `pinned_message` — this survives a restart, unlike
  `getUpdates`), and if it's a valid backup — automatically restores state from it, with no
  manual action needed. If the local state is already non-empty (the disk wasn't wiped) —
  auto-restore doesn't touch anything.
- **Manual restore** — works the same way: forward the file (`state_backup.json`) back to the
  bot in the chat at any time. The bot recognizes it by name, checks that it's actually a valid
  backup (has `jobs`/`seen` fields), and only then replaces the current `state.json`. Unrelated
  files are ignored, broken JSON is rejected with an explanation, and the current state isn't
  touched in that case.
- If Render does have a paid persistent disk (`JOBBOT_STATE=/data/state.json` on a mounted
  disk) — backup/auto-restore to Telegram still doesn't hurt as a second layer of protection.
- `BACKUP_INTERVAL_HOURS=0` — disables auto-backup (only manual `/backup` remains; auto-restore
  on startup works independently of this variable, as long as there's any pinned backup).

## 7b. Firebase Realtime Database (optional — real persistence, no manual restore)
- The pinned-backup dance above exists because Render's disk isn't persistent on this plan.
  Firebase Realtime Database (Spark plan — no card needed, Google just throttles you at the
  quota rather than billing past it: 1 GB storage, 10 GB/month downloaded, plenty for this)
  removes the need for it: state lives in Firebase instead of the local disk, survives every
  restart/redeploy automatically, with nothing to forward or restore by hand.
- Setup (one-time, in the Firebase console — console.firebase.google.com):
  1. Create a project (any name, Analytics not needed).
  2. Build → Realtime Database → Create Database (any region; "locked mode" for the rules).
  3. Copy the database URL shown at the top of the Realtime Database page
     (`https://<project>-default-rtdb.<region>.firebasedatabase.app`).
  4. Project settings → Service accounts → Generate new private key — downloads a `.json` file.
     **Never commit this file or post it anywhere** — it's a password to your database.
- On Render, set two environment variables:
  - `FIREBASE_DB_URL` — the database URL from step 3.
  - `FIREBASE_SERVICE_ACCOUNT_JSON` — the **entire contents** of the downloaded `.json` key file,
    pasted as one value.
- Both unset (the default) — jobbot behaves exactly as in section 7, plain local file + Telegram
  pinned-backup restore. Both set — state is read from/written to Firebase instead, and the
  pinned-backup mechanism automatically becomes a last-resort fallback only (used if Firebase is
  empty or unreachable at startup) rather than the primary path.
- To keep well inside the quota, the bot only writes to Firebase when something in the state
  actually changed (a new job found, a button tapped) — not on every `--loop` tick even if
  nothing happened. State is also kept in memory for the life of the process, so it's read from
  Firebase once at startup, not on every single check.
- Needs the `google-auth` and `requests` packages (already in `requirements.txt`) — only
  imported when both env vars above are set, so a deployment that doesn't use Firebase doesn't
  need them installed for anything to work.
- `/set use_firebase 0` — temporarily turns Firebase off at runtime (falls back to the local
  file) without touching the env vars; `/set use_firebase 1` turns it back on. Default is `1`
  whenever both env vars above are set.
- Firebase Realtime Database keys can't contain `. # $ [ ] /` — some job IDs can (Jooble/RemoteOK
  use the full job URL as their ID, slashes and all). `bot/firebase_store.py` escapes these
  characters transparently on every read/write, so this never needs any attention — mentioned
  here only because an early version didn't do this and failed every write with a bare
  `400 Bad Request`. Confirmed working in production as of October 2026.

## 7a. Settings via Telegram (no redeploy needed)
- The `/settings` command shows the current values of 8 parameters: `reminder_hours`,
  `quiet_hours_start`, `quiet_hours_end`, `stats_period_days`, `backup_interval_hours`,
  `pending_list_limit`, `pending_cards_limit`, `seen_list_limit` — marked "(changed)" for any
  that differ from the default (env variable or built-in default).
- The `/set <key> <value>` command, e.g. `/set reminder_hours 12` or
  `/set backup_interval_hours 0` — changes the parameter immediately, no restart or redeploy
  needed. An invalid key, a non-numeric value, or a value out of the allowed range (e.g. quiet
  hours outside 0-24) is rejected with an explanation, leaving the current setting untouched.
- Values changed via `/set` are stored in `state.json` (`settings`), so they automatically
  survive a disk wipe along with the rest of the state — through the same
  backup/auto-restore from section 7, no separate mechanism needed.
- The environment variable for a parameter (e.g. `REMINDER_HOURS`) still sets the initial value
  until `/set` has been used for that key at least once; after the first `/set`, the value
  stored in `state.json` takes priority until changed again.

## 7b. /pending — "not interested" checkboxes right in the list, no need to open each job
- `/pending` immediately sends ONE message with a list of ⬜/✅ buttons — one per job, with no
  intermediate step (previously you had to first tap a separate "Show with checkboxes" button).
  Tap the title — it immediately switches to ✅ and the job disappears from "Awaiting response"
  in stats; tap it again — the mark is removed (⬜) if you tapped it by mistake. The
  "✅ Done" button removes the keyboard once you've gone through everything you wanted to.
- If you specifically need "Applied" (not "not interested") — there's a "🔘 Applied/Not
  interested one by one (cards)" button at the bottom that switches to the old mode: a separate
  message per job with both buttons.
- Unlike the "🚫 Not interested" button under the push itself (a one-time action), here the mark
  can be toggled on and off as many times as you like — in stats ("Not interested" in `/stats`)
  the job is only counted once, even if you toggle the mark back and forth several times.
- Next to each checkbox is a row with two buttons: **"🔗 Open"** (opens the job without leaving
  the checkbox list) and **"✅ Applied"** (marks the job as "applied" right there, if you applied
  straight from this list — no need to switch to card mode). After "✅ Applied" both rows for
  that job (checkbox + "Open"/"Applied") disappear from the keyboard — the rest of the list
  stays in place.
- The list is split into two groups: **"⭐ Priority (Lviv/Remote, iOS, AI)"** on top and
  **"— Other —"** below. The **"🚫 Dismiss all 'Other'"** button marks the entire bottom group
  as "not interested" with one tap — handy when there's already something interesting in the
  priority group and you don't want to go through the rest.
- **Lots of jobs at once?** Telegram won't accept too large a keyboard in one message (it used
  to fail with "reply markup is too long" at ~50+ jobs) — so the list is automatically split
  into pages, and a **"➡️ Next (N)"** button appears at the bottom: tap it to see the next batch
  starting right where the previous one left off (no need to manually re-run `/pending` from
  the start of the list). The same works in `/skipped`.
- **Changed your mind, or the job got reopened?** The `/skipped` command shows a list of all
  jobs marked "not interested" (not yet "Applied"), with the same checkbox buttons — except here
  everything starts as ✅. Tap the title — the mark is removed, and the job immediately returns
  to "Awaiting response" in `/pending`, from where you can open and apply again.

## 8. If the DOU/Djinni RSS feed goes silent
- If a feed fails to respond (403, timeout, broken XML) for `FEED_FAIL_THRESHOLD` runs in a row
  (default 5) — a single warning in Telegram, so a technical failure isn't mistaken for "just no
  new jobs". When the feed recovers — a single message about that, no spam every time.
- `FEED_FAIL_THRESHOLD=0` — disables these warnings.

## 9. Keeping it running without interruptions
- Mac/PC: `nohup python3 jobbot.py --loop 60 &` (or launchd/systemd).
- Render / a cheap VPS / Raspberry Pi — the most reliable options.
- The resume/cover-letter buttons only work in `--loop` mode (a separate thread listens for
  Telegram commands).

**On this plan, Render goes to sleep without traffic (~15 min with no requests) — it needs an
external ping.** If the `PORT` environment variable is set (Render sets it automatically),
`jobbot.py` starts a minimal HTTP endpoint (`GET /` → `200 OK`) for exactly this purpose — the
bot itself (Telegram polling, feeds) keeps running independently of it. To keep Render from
sleeping:
1. Sign up at [UptimeRobot](https://uptimerobot.com).
2. Add a new **HTTP(s)** monitor, URL — your Render service's address
   (`https://<your-app>.onrender.com/`), check interval — 5 minutes.
3. Done — UptimeRobot regularly "wakes" the service, so the disk/bot doesn't go to sleep
   between real requests. Any similar ping service works too (cron-job.org, healthchecks.io,
   etc.) — the only requirement is that it hits the `/` root at an interval under ~15 min.

## 10. Configuration
`GLOBAL_EXCLUDE` (roles that are never of interest, for any profile), `MAX_AGE_DAYS`,
`FIRST_RUN_LIMIT` (first run only sends the N most recent) — in `bot/config.py`. The base resume
for the "Tailor resume" button is separate, in `bot/resumes.py`/`bot/resumes_local.py` (section 4).
The "Open" button leads straight to "Apply" (DOU) or the job page (Djinni).

The search profiles themselves (iOS, Node.js, Embedded/Linux, Java, Python by default) are now
edited directly from Telegram — no code changes or redeploy needed, see section 11.

## 11. Search profiles — /profiles, /addprofile
`bot/config.py` with its profiles is just the initial seed set for the first run. On first
startup it's copied into `state.json`, and from then on `state.json` is the single source of
truth — that's where the bot adds/removes profiles, and that's the file that gets backed up
(section 7) — so your set of profiles won't get lost if the disk is reset.

- **`/profiles`** — list of current profiles (name, resume, how many feeds) with a 🗑 delete
  button under each.
- **`/addprofile`** — a step-by-step wizard: profile name → resume key (for the "Tailor resume"
  button; if there's no matching resume in `bot/resumes.py` that's fine, the button will just be
  disabled for this profile) → keywords for DOU/Djinni feeds (each word = one DOU feed and one
  Djinni feed) → words that must appear in the title (or "-") → exclusion words (or "-") →
  exclude Senior/Lead positions (yes/no) → max years of experience (or "-"). No regex to write —
  everything is built from plain keywords. `/cancel` — cancel the wizard at any point.

Example: for a frontend-developer friend (not looking for Embedded, not tied to Lviv, no iOS)
it's enough to run `/addprofile` → "🎨 Frontend" → `Frontend` → `Frontend, React, Vue` → `-` →
`backend, devops` → yes (no Senior) → `3` — and that's already a separate, fully custom search
profile, with no code changes at all.

## 12. Render — environment variables
The start command stays `python3 jobbot.py --loop 60`. Add the dependency install to the
build command: `pip install -r requirements.txt`.

| Variable | Required? | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | required | Telegram bot token. |
| `TELEGRAM_CHAT_ID` | required | Chat the bot pushes to and listens in. |
| `ANTHROPIC_API_KEY` | required | Used for resume/cover-letter tailoring. |
| `ANTHROPIC_MODEL` | optional | Overrides the default model. |
| `NTFY_TOPIC` | optional | Mirrors pushes to ntfy.sh as well. |
| `REMINDER_HOURS` | optional | See section 6. |
| `TZ_NAME` | optional | Timezone for quiet hours/digest (default `Europe/Kyiv`). |
| `QUIET_HOURS_START` / `QUIET_HOURS_END` | optional | See section 6. |
| `DIGEST_WEEKDAY` / `DIGEST_HOUR` | optional | See section 6. |
| `BACKUP_INTERVAL_HOURS` | optional | See section 7. |
| `FEED_FAIL_THRESHOLD` | optional | See section 8. |
| `BOT_LANG` | optional | `uk` (default) or `en` — see section 13. |
| `APPLICANT_NAME` | optional | Your name, no spaces — used only for the PDF resume file name (e.g. `JaneDoe_CV_...pdf`); if not set, the file is just named `Resume_CV_...pdf`. |
| `JOOBLE_API_KEY` / `JOOBLE_LOCATION` | optional | See section 15 — only needed if you turn the Jooble source on. |
| `FIREBASE_DB_URL` / `FIREBASE_SERVICE_ACCOUNT_JSON` | optional | See section 7b — only needed for the Firebase persistence backend. |

## 13. Bot language (i18n)
All text the bot sends to Telegram/ntfy (pushes, buttons, command replies) lives in `bot/i18n.py` —
a `TRANSLATIONS` dict with language sections (currently `uk` and `en`). The language is chosen
via the `BOT_LANG` environment variable (default `uk`) and is fixed once at startup — there's
no live language switching, one deployment = one language.

To deploy an English-language version: set `BOT_LANG=en` on Render. To add another language —
copy the `"uk": { ... }` block in `bot/i18n.py`, translate only the values (leave the keys and
`{placeholders}`/HTML tags like `<b>`, `<a href=...>` as they are — the code fills those in,
not the translation), and add the new language as another section in `TRANSLATIONS`.

## 15. Extra sources — Jooble, RemoteOK, Work.ua
- Besides DOU and Djinni, three more sources can be turned on — all off by default.
- Turn one on with `/set source_jooble 1` / `/set source_remoteok 1` / `/set source_workua 1` in
  Telegram (no redeploy needed).
- Each profile's `keywords` field in `bot/config.py` (or the keywords you gave `/addprofile`) drives
  all three; nothing else to configure per-profile.
- **Jooble** — needs a `JOOBLE_API_KEY` env var (sign up at jooble.org/api/about); location
  defaults to `Україна`, override with `JOOBLE_LOCATION`.
- **RemoteOK** — no key needed.
- **Work.ua** — no key needed (needs `beautifulsoup4`, already in `requirements.txt`).
