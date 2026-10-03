"""
config — this is the file to edit to make jobbot yours: which job profiles to track, which
feeds/keywords to pull from DOU and Djinni, and a few related preferences (AI-job priority
keyword, how far back to look, how many to send on first run).

To adapt jobbot for your own background:
  1. Add your own base resume(s) to resumes.py (BASE_RESUMES) — or leave resume_key pointing
     at a name that isn't in resumes.py; the bot still works, it just disables the "tailor
     resume"/"cover letter" buttons for that profile (see Java/Python profiles below).
  2. Edit PROFILES below: one entry per role you're searching for. Each profile is independent
     — different feeds, different title filters, different experience cap.
  3. GLOBAL_EXCLUDE applies to every profile (roles that are never development jobs, whatever
     you're searching for). SENIOR_WORDS/EMBEDDED_TEXT are just reusable regex fragments used
     inside PROFILES below — add more such fragments as you add profiles.

Known limitation: the "⭐ priority" badge for AI-related jobs is generic (PRIORITY_TEXT, any
profile), but the Embedded profile's Lviv/remote priority and the iOS profile's always-priority
behavior are still hardcoded by resume_key in jobbot.py (job_priority_and_location) rather than
being a PROFILES setting — fine for one person's own profiles, but the first thing to generalize
further if you add a profile that needs its own priority rule.
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

EMBEDDED_TEXT = (
    r"embedded|firmware|rtos|yocto|buildroot|\bbsp\b|stm32|esp32|microcontroller|"
    r"мікроконтролер|вбудован|linux kernel|device driver|драйвер"
)

# Embedded profile: Lviv/remote — priority (⭐, goes first in pushes and lists), Kyiv —
# its own badge, no priority. Only for Embedded, since location doesn't matter for other profiles.
EMBEDDED_PRIORITY_LOCATION_RE = r"льв|lviv|remote|віддален|дистанційн"  # bare "льв" stem catches all Ukrainian cases of "Lviv"
EMBEDDED_KYIV_LOCATION_RE = r"ки[їє]в|kyiv|kiev"  # catches all Ukrainian cases of "Kyiv" (except the rare "kiyv" spelling)

# Profiles = your own experience. Edit these freely.
# resume_key -> which base resume from resumes.py to tailor for this job.
PROFILES = {
    "🍎 iOS (Senior)": {
        "resume_key": "iOS",
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("iOS")), None),
            ("Djinni", DJINNI.format("iOS"), None),
        ],
        "must_title": r"\b(ios|swift|swiftui|iphone|ipad|apple|objective-c|macos|mobile)\b",
        "exclude_title": r"\b(junior|jr\.?|intern|trainee|android|kotlin|flutter|react native|unity)\b",
        "max_years": None,
    },
    "🟢 Node.js (Junior+/Middle)": {
        "resume_key": "Node.js",
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("Node.js")), None),
            ("Djinni", DJINNI.format(urllib.parse.quote("Node.js")), None),
        ],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 4,       # discard if more than N years are required
    },
    "🔌 Embedded / Linux (Junior)": {
        "resume_key": "Embedded",
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("Embedded")), None),
            ("DOU", DOU.format(urllib.parse.quote("C++")), EMBEDDED_TEXT),
            ("Djinni", DJINNI.format("Embedded"), None),
            ("Djinni", DJINNI.format(urllib.parse.quote("C++")), EMBEDDED_TEXT),
            ("Djinni", DJINNI.format("Linux"), EMBEDDED_TEXT),
        ],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 3,
    },
    "☕ Java (Junior+/Middle)": {
        "resume_key": "Java",  # no base resume in resumes.py — CV/cover-letter buttons are disabled
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("Java")), None),
            ("Djinni", DJINNI.format("Java"), None),
        ],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 4,
    },
    "🐍 Python (Junior, до 2 років)": {
        "resume_key": "Python",  # no base resume in resumes.py — CV/cover-letter buttons are disabled
        "feeds": [
            ("DOU", DOU.format(urllib.parse.quote("Python")), None),
            ("Djinni", DJINNI.format("Python"), None),
        ],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 1,  # under 2 years — discard if 2+ are required
    },
}
