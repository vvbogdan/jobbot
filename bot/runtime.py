# -*- coding: utf-8 -*-
"""runtime — small process-wide constants derived from the environment at import time.

These are read by more than one of the other bot/ modules (e.g. TZ_NAME by both collector.py's
is_quiet_now() and background.py's maybe_send_weekly_digest()), so they live in one place instead
of being duplicated or forcing an import cycle between those modules. Contrast with state.py's
SETTINGS_SCHEMA: those are user-adjustable at runtime via /set and persisted in state.json; these
are fixed for the life of the process, from the environment only.
"""
import os
import re
import time

TZ_NAME = os.environ.get("TZ_NAME", "Europe/Kyiv")

# DOU/Djinni's RSS <pubDate> isn't fixed at first-posted — a recruiter "bumping"/refreshing their
# listing (to signal the role is open again / back near the top of DOU's own site) changes it,
# with the vacancy id staying the same. If the pubDate we see now is at least this much newer
# than the pubDate we saw the last time we sent this id, treat it as reopened and push it again,
# instead of silently treating "already in seen" as "nothing to do here forever".
REOPEN_GAP_SEC = 2 * 86400  # 2 days — enough to ignore minor feed jitter, short enough to catch
                             # a genuine bump quickly
REMINDER_CHECK_SEC = 600  # how often to check who's due for a reminder

DIGEST_WEEKDAY = int(os.environ.get("DIGEST_WEEKDAY", "6"))  # 0=Monday ... 6=Sunday
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "19"))       # what hour (local time, TZ_NAME)
DIGEST_CHECK_SEC = 300

BACKUP_CHECK_SEC = 1800
BACKUP_STARTUP_DELAY_SEC = 90  # give the first run_once time to fill state.json before backing up

FEED_FAIL_THRESHOLD = int(os.environ.get("FEED_FAIL_THRESHOLD", "5"))  # consecutive runs (0 = disable)

# Telegram flood control: without a pause between pushes, a batch of new jobs (e.g. after
# Render Free wipes the disk and a "first run" repeats) hits the rate limit and send_telegram()
# silently (previously — with no log at all) returns False for ALL of them in a row.
PUSH_THROTTLE_SEC = float(os.environ.get("PUSH_THROTTLE_SEC", "1.2"))

APPLICANT_NAME = re.sub(r"[^\w\-]+", "", os.environ.get("APPLICANT_NAME", "Resume"))

# Render sets RENDER_GIT_COMMIT automatically on every deploy — surfacing it (short form) in
# /stats is how to tell "yes, the latest fix actually deployed" apart from "still on the old
# build" without digging through the Render dashboard. PROCESS_STARTED is just this process's
# own start time (module import time) — "how long has it been running without a restart".
BOT_VERSION = os.environ.get("RENDER_GIT_COMMIT", "")[:7] or "dev"
PROCESS_STARTED = time.time()
