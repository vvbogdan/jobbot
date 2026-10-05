"""
config — this is the file to edit to make jobbot yours: which job profiles to track, which
keywords to search for, and a few related preferences (AI-job priority keyword, how far back
to look, how many to send on first run).

To adapt jobbot for your own background:
  1. Add your own base resume(s) to resumes.py (BASE_RESUMES) — or leave resume_key pointing
     at a name that isn't in resumes.py; the bot still works, it just disables the "tailor
     resume"/"cover letter" buttons for that profile (see Java/Python profiles below).
  2. Edit PROFILES below: one entry per role you're searching for. Each profile is independent
     — different keywords, different title filters, different experience cap.
  3. GLOBAL_EXCLUDE applies to every profile (roles that are never development jobs, whatever
     you're searching for). SENIOR_WORDS/EMBEDDED_TEXT are just reusable regex fragments used
     inside PROFILES below — add more such fragments as you add profiles.

"keywords" (per profile, list of (keyword, must_text) pairs — must_text is extra text that must
appear in title+description for that keyword to count, or None for no extra filter) is searched
against every active source in sources/ — DOU and Djinni always, and Jooble/RemoteOK/Work.ua
whenever their /set source_jooble|source_remoteok|source_workua toggle is on (off by default —
see README section 15 for what each needs and its caveats). One list of keywords drives every
source; there's no separate per-source feed list to keep in sync.

Known limitation: the "⭐ priority" badge for AI-related jobs is generic (PRIORITY_TEXT, any
profile), but the Embedded profile's Lviv/remote priority and the iOS profile's always-priority
behavior are still hardcoded by resume_key in jobbot.py (job_priority_and_location) rather than
being a PROFILES setting — fine for one person's own profiles, but the first thing to generalize
further if you add a profile that needs its own priority rule.
"""

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

EMBEDDED_TEXT = (
    r"embedded|firmware|rtos|yocto|buildroot|\bbsp\b|stm32|esp32|microcontroller|"
    r"мікроконтролер|вбудован|linux kernel|device driver|"
    # "драйвер" alone also matches the common Ukrainian business idiom "драйвер
    # зростання/росту" (growth driver) — require it NOT be followed by that, so a marketing/
    # growth-role job (e.g. "User Acquisition Manager") can't sneak into Embedded via this word.
    r"драйвер\w*\b(?!\s*(зростання|росту|змін|продаж|бізнесу|компані|команди|доходу|прибутку))"
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
        "keywords": [("iOS", None), ("Mobile", None)],
        "must_title": r"\b(ios|swift|swiftui|iphone|ipad|apple|objective-c|macos|mobile)\b",
        "exclude_title": r"\b(junior|jr\.?|intern|trainee|android|kotlin|flutter|react native|unity)\b",
        "max_years": None,
    },
    "🟢 Node.js (Junior+/Middle)": {
        "resume_key": "Node.js",
        "keywords": [("Node.js", None), ("JavaScript", r"node")],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 4,       # discard if more than N years are required
    },
    "🔌 Embedded / Linux (Junior)": {
        "resume_key": "Embedded",
        "keywords": [
            ("Embedded", None), ("C++", EMBEDDED_TEXT), ("Linux", EMBEDDED_TEXT),
            ("CPP", EMBEDDED_TEXT), ("C Lang", EMBEDDED_TEXT),
            ("Hardware", EMBEDDED_TEXT), ("Robotics", EMBEDDED_TEXT),
        ],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 3,
    },
    "☕ Java (Junior+/Middle)": {
        "resume_key": "Java",  # no base resume in resumes.py — CV/cover-letter buttons are disabled
        "keywords": [("Java", None)],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 4,
    },
    "🐍 Python (Junior, до 2 років)": {
        "resume_key": "Python",  # no base resume in resumes.py — CV/cover-letter buttons are disabled
        "keywords": [("Python", None)],
        "must_title": None,
        "exclude_title": SENIOR_WORDS,
        "max_years": 1,  # under 2 years — discard if 2+ are required
    },
}
