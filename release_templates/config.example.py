"""
config — this is the file to edit to make jobbot yours: which job profiles to track, which
feeds/keywords to pull from DOU and Djinni, and a few related preferences (AI-job priority
keyword, how far back to look, how many to send on first run).

This is an EXAMPLE config with a single made-up "Frontend" profile, just so you can see the
shape of a profile and run the bot right away. Once it's running, you don't need to touch this
file at all — use /addprofile in Telegram to add your own profile(s) with your own keywords
(no code or regex needed), and /profiles to see/delete them. Profiles added that way live in
state.json and survive redeploys/backups; this file is only the one-time seed for a brand-new
state.json.

To adapt jobbot for your own background by editing code instead (optional — /addprofile covers
most cases):
  1. Add your own base resume(s) to resumes.py (BASE_RESUMES) — or leave resume_key pointing
     at a name that isn't in resumes.py; the bot still works, it just disables the "tailor
     resume"/"cover letter" buttons for that profile.
  2. Edit PROFILES below: one entry per role you're searching for. Each profile is independent
     — different feeds, different title filters, different experience cap.
  3. GLOBAL_EXCLUDE applies to every profile (roles that are never development jobs, whatever
     you're searching for). SENIOR_WORDS/EMBEDDED_TEXT are just reusable regex fragments used
     inside PROFILES below — add more such fragments as you add profiles.
"""
import urllib.parse

MAX_AGE_DAYS = 7          # ignore jobs older than N days
FIRST_RUN_LIMIT = 10      # on first run, only send the N freshest; mark the rest as seen silently

# Jobs whose title/description mention these are marked ⭐ and pushed first, in any profile.
PRIORITY_TEXT = (
    r"agentic|claude code|ai[- ]enabled|ai[- ]native|ai agent|mcp server|"
    r"ai coding assistant|vibe coding"
)

# Title keywords that are never interesting (not development roles) — applies to every profile.
GLOBAL_EXCLUDE = (
    r"\b(aso|qa|aqa|sdet|tester|test engineer|support|marketing|recruiter|sales|"
    r"designer|analyst|product owner|scrum master|hr|accountant|copywriter|"
    r"buyer|media buyer|community manager)\b"
)
SENIOR_WORDS = r"\b(senior|sr\.?|lead|principal|staff|architect|head of|cto|team lead|tech lead)\b"

DOU = "https://jobs.dou.ua/vacancies/feeds/?category={}"
DJINNI = "https://djinni.co/jobs/rss/?primary_keyword={}"

# Used only if you add your own Embedded-style profile below — harmless to leave as-is otherwise.
EMBEDDED_TEXT = (
    r"embedded|firmware|rtos|yocto|buildroot|\bbsp\b|stm32|esp32|microcontroller|"
    r"мікроконтролер|вбудован|linux kernel|device driver|драйвер"
)
EMBEDDED_PRIORITY_LOCATION_RE = r"льв|lviv|remote|віддален|дистанційн"
EMBEDDED_KYIV_LOCATION_RE = r"ки[їє]в|kyiv|kiev"

# Profiles = your own experience. This is just one example — edit it, or better, add your own
# with /addprofile in Telegram once the bot is running (no code editing needed).
PROFILES = {
    "🎨 Frontend (Junior+)": {
        "resume_key": "Frontend",
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("Frontend")), None),
            ("Djinni", DJINNI.format(urllib.parse.quote("Frontend")), None),
            ("DOU", DOU.format(urllib.parse.quote("JavaScript")), r"react|vue"),
            ("Djinni", DJINNI.format(urllib.parse.quote("JavaScript")), r"react|vue"),
        ],
        "must_title": None,
        "exclude_title": r"(?:\b(backend|devops)\b)|(?:" + SENIOR_WORDS + ")",
        "max_years": 3,
    },
}
