# -*- coding: utf-8 -*-
"""resume — Claude API calls for resume-tailoring/cover-letter generation, plus turning the
adapted resume's plain-text markup into a PDF. Nothing here touches Telegram or state.json: it
takes a resume_key/job title/description in and returns text or writes a PDF file out. The
command handlers that wire this into the "📄 Tailor resume"/"✉️ Cover letter" buttons (caching
the result in state.json, sending the Telegram messages/document) stay in jobbot.py as
handle_cv_request/handle_cl_request — this module is the pure generation step they call into.

Fourth extraction step of jobbot.py's split into focused modules (after telegram_api.py/
logutil.py, matching.py, state.py) — see README/commit history for the rest of the plan.
"""
import html
import json
import os

try:
    # your own, real resume — gitignored, never committed (see resumes.py for the public example)
    from .resumes_local import BASE_RESUMES
except ImportError:
    from .resumes import BASE_RESUMES
from .net import http

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

RESUME_SYSTEM_PROMPT = """Ти допомагаєш адаптувати резюме кандидата під конкретну вакансію.

СУВОРІ ПРАВИЛА:
- Нічого не вигадуй: не додавай компаній, дат, посад, технологій чи цифр, яких нема в базовому
  резюме. Можна лише переформульовувати, підсвічувати релевантне, змінювати порядок і скорочувати.
- Контакти (email/телефон/локацію) залишай без змін.
- Заголовок (## Title) — переформулюй під назву вакансії, але чесно, без брехні про рівень.
- Якщо в базовому резюме є прямий застережний коментар (наприклад, що досвід переважно з
  pet-проєкту, а не production) — обов'язково збережи цю чесність, не приховуй і не применшуй.
- Пиши резюме англійською, якщо вакансія англійською; українською — якщо вакансія українською.
- Обсяг — приблизно як в оригіналі (одна сторінка A4), без води.

ФОРМАТ ВИВОДУ — ЛИШЕ ось такий плейн-текст з розміткою, без жодних інших коментарів до чи після:

# <Ім'я Прізвище>
## <Заголовок під вакансію>
<email> | <телефон, якщо є> | <локація>

### Summary
<2-4 речення>

### Skills
- <навичка>: <короткий деталь>
- <навичка>: <короткий деталь>

### Experience
**<Посада> | <Компанія> | <Дати>**
- <буллет>
- <буллет>

**<Посада> | <Компанія> | <Дати>**
- <буллет>

### Education
- <ступінь> | <навчальний заклад> | <дати>
"""

COVER_LETTER_SYSTEM_PROMPT = """Ти пишеш короткий супровідний лист (cover letter) кандидата під
конкретну вакансію.

СУВОРІ ПРАВИЛА:
- Нічого не вигадуй: спирайся лише на факти з базового резюме кандидата (компанії, технології,
  роки досвіду). Не додавай того, чого нема в резюме.
- 3-4 короткі абзаци: чому кандидат підходить, 1-2 конкретні релевантні навички/досягнення з
  резюме, коротке ввічливе завершення. Без канцеляриту й порожніх кліше.
- Пиши тією мовою, якою написана вакансія (англійська → англійською, українська → українською).
- Обсяг — 120-200 слів.
- Формат виводу — лише текст листа плейн-текстом, без markdown-розмітки і без жодних коментарів
  до чи після.
"""


def call_claude(system_prompt, user_prompt, max_tokens=1600):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY не задано")
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()
    raw = http(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        timeout=60, retries=1,
    )
    data = json.loads(raw)
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError(f"Порожня відповідь Claude API: {raw[:300]}")
    return text


def adapt_resume(resume_key, job_title, job_desc):
    base = BASE_RESUMES.get(resume_key)
    if not base:
        raise RuntimeError(f"Немає базового резюме для профілю {resume_key}")
    user_prompt = (
        f"ВАКАНСІЯ:\nНазва: {job_title}\n\nОпис:\n{job_desc[:5000]}\n\n"
        f"БАЗОВЕ РЕЗЮМЕ КАНДИДАТА:\n{base}\n\n"
        "Адаптуй базове резюме під цю вакансію за форматом і правилами з системного промпту."
    )
    return call_claude(RESUME_SYSTEM_PROMPT, user_prompt)


def generate_cover_letter(resume_key, job_title, job_desc):
    base = BASE_RESUMES.get(resume_key)
    if not base:
        raise RuntimeError(f"Немає базового резюме для профілю {resume_key}")
    user_prompt = (
        f"ВАКАНСІЯ:\nНазва: {job_title}\n\nОпис:\n{job_desc[:5000]}\n\n"
        f"БАЗОВЕ РЕЗЮМЕ КАНДИДАТА:\n{base}\n\n"
        "Напиши супровідний лист під цю вакансію за правилами із системного промпту."
    )
    return call_claude(COVER_LETTER_SYSTEM_PROMPT, user_prompt, max_tokens=500)


def parse_resume_markup(text):
    """Lightweight markdown-like markup -> list of blocks for reportlab."""
    blocks = []
    section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            blocks.append(("space", None))
            continue
        if line.startswith("# "):
            blocks.append(("name", line[2:].strip()))
        elif line.startswith("## "):
            blocks.append(("title", line[3:].strip()))
        elif line.startswith("### "):
            section = line[4:].strip().lower()
            blocks.append(("section", line[4:].strip()))
        elif line.startswith("- "):
            blocks.append(("bullet", line[2:].strip()))
        elif line.startswith("**") and line.endswith("**") and len(line) > 4:
            blocks.append(("jobhead", line.strip("*").strip()))
        elif section is None:
            blocks.append(("contact", line))
        else:
            blocks.append(("para", line))
    return blocks


def render_resume_pdf(markup_text, out_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

    ACCENT = colors.HexColor("#1f4e79")
    GRAY = colors.HexColor("#444444")

    styles = {
        "name": ParagraphStyle("name", fontSize=20, leading=24, fontName="Helvetica-Bold",
                                textColor=ACCENT, spaceAfter=2),
        "title": ParagraphStyle("title", fontSize=12.5, leading=16, fontName="Helvetica-Oblique",
                                 textColor=GRAY, spaceAfter=2),
        "contact": ParagraphStyle("contact", fontSize=9.5, leading=13, textColor=GRAY, spaceAfter=8),
        "section": ParagraphStyle("section", fontSize=12, leading=16, fontName="Helvetica-Bold",
                                   textColor=ACCENT, spaceBefore=10, spaceAfter=4,
                                   borderColor=ACCENT, borderWidth=0, alignment=TA_LEFT),
        "jobhead": ParagraphStyle("jobhead", fontSize=10.5, leading=14, fontName="Helvetica-Bold",
                                   spaceBefore=6, spaceAfter=2),
        "para": ParagraphStyle("para", fontSize=10, leading=14, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", fontSize=10, leading=13.5),
    }

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                             topMargin=16 * mm, bottomMargin=14 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []
    bullet_buf = []

    def flush_bullets():
        nonlocal bullet_buf
        if bullet_buf:
            story.append(ListFlowable(
                [ListItem(Paragraph(html.escape(b), styles["bullet"]), leftIndent=6) for b in bullet_buf],
                bulletType="bullet", start="•", leftIndent=12, spaceAfter=4,
            ))
            bullet_buf = []

    for kind, val in parse_resume_markup(markup_text):
        if kind == "bullet":
            bullet_buf.append(val)
            continue
        flush_bullets()
        if kind == "space":
            story.append(Spacer(1, 4))
        elif kind == "name":
            story.append(Paragraph(html.escape(val), styles["name"]))
        elif kind == "title":
            story.append(Paragraph(html.escape(val), styles["title"]))
        elif kind == "contact":
            story.append(Paragraph(html.escape(val), styles["contact"]))
        elif kind == "section":
            story.append(Paragraph(html.escape(val.upper()), styles["section"]))
        elif kind == "jobhead":
            story.append(Paragraph(html.escape(val), styles["jobhead"]))
        elif kind == "para":
            story.append(Paragraph(html.escape(val), styles["para"]))
    flush_bullets()

    doc.build(story)
