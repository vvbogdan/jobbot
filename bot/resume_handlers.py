# -*- coding: utf-8 -*-
"""resume_handlers — wires resume.py's Claude-API/PDF generation into the "📄 Tailor resume" and
"✉️ Cover letter" buttons: caching the result in state.json (so a repeat tap doesn't trigger a new
API call) and sending the Telegram document/message. resume.py itself stays pure (no Telegram,
no state.json) — this is the orchestration layer on top of it, kept separate so resume.py can be
unit-tested without mocking Telegram.

Tenth extraction step of jobbot.py's split into focused modules.
"""
import html
import re
import time
from pathlib import Path

from .i18n import t
from .logutil import log
from .telegram_api import answer_callback_query, send_telegram_plain, send_telegram_document
from .state import load_state, state_update
from .resume import ANTHROPIC_API_KEY, adapt_resume, generate_cover_letter, render_resume_pdf
from .runtime import APPLICANT_NAME


def handle_cv_request(chat_id, callback_id, jid, force=False):
    answer_callback_query(callback_id, t("toast_regenerating_resume") if force else t("toast_preparing_resume"))
    st = load_state()
    job = st.get("jobs", {}).get(jid)
    if not job:
        send_telegram_plain(chat_id, t("job_stale_in_cache"))
        return
    cached = job.get("cv_cache")
    note = ""
    if cached and not force:
        markup = cached["markup"]
        note = t("note_from_cache_no_api_call")
    else:
        if not ANTHROPIC_API_KEY:
            send_telegram_plain(chat_id, t("anthropic_key_missing_resume"))
            return
        send_telegram_plain(chat_id, t("tailoring_resume_for", title=job["title"][:80]))
        try:
            markup = adapt_resume(job["resume_key"], job["title"], job["desc"])
        except Exception as e:  # noqa: BLE001
            log("✗ handle_cv_request (adapt):", e)
            send_telegram_plain(chat_id, t("resume_adapt_error", error=e))
            return

        def _cache(st, jid=jid, markup=markup):
            j = st.get("jobs", {}).get(jid)
            if j:
                j["cv_cache"] = {"markup": markup, "ts": time.time()}
        state_update(_cache)
    try:
        tmp_pdf = Path(f"/tmp/cv_{jid.replace(':', '_')}_{int(time.time())}.pdf")
        render_resume_pdf(markup, tmp_pdf)
        safe_title = re.sub(r"[^\w\-]+", "_", job["title"])[:40]
        ok = send_telegram_document(
            chat_id, tmp_pdf, f"{APPLICANT_NAME}_CV_{safe_title}.pdf",
            caption=t("resume_caption", title=job["title"][:150], note=note),
            buttons=[[{"text": t("btn_regenerate"), "callback_data": f"cvr|{jid}"}]],
        )
        tmp_pdf.unlink(missing_ok=True)
        if not ok:
            send_telegram_plain(chat_id, t("resume_send_failed"))
    except Exception as e:  # noqa: BLE001
        log("✗ handle_cv_request (render):", e)
        send_telegram_plain(chat_id, t("resume_render_error", error=e))


def handle_cl_request(chat_id, callback_id, jid, force=False):
    answer_callback_query(callback_id, t("toast_regenerating_letter") if force else t("toast_preparing_letter"))
    st = load_state()
    job = st.get("jobs", {}).get(jid)
    if not job:
        send_telegram_plain(chat_id, t("job_stale_in_cache"))
        return
    cached = job.get("cl_cache")
    note = ""
    if cached and not force:
        letter = cached["text"]
        note = t("note_from_cache")
    else:
        if not ANTHROPIC_API_KEY:
            send_telegram_plain(chat_id, t("anthropic_key_missing_letter"))
            return
        send_telegram_plain(chat_id, t("writing_letter_for", title=job["title"][:80]))
        try:
            letter = generate_cover_letter(job["resume_key"], job["title"], job["desc"])
        except Exception as e:  # noqa: BLE001
            log("✗ handle_cl_request:", e)
            send_telegram_plain(chat_id, t("letter_generate_error", error=e))
            return

        def _cache(st, jid=jid, letter=letter):
            j = st.get("jobs", {}).get(jid)
            if j:
                j["cl_cache"] = {"text": letter, "ts": time.time()}
        state_update(_cache)
    text = t("cover_letter_text", note=note, title=html.escape(job["title"][:120]), letter=html.escape(letter))
    if not send_telegram_plain(chat_id, text, buttons=[[{"text": t("btn_regenerate"), "callback_data": f"clr|{jid}"}]]):
        send_telegram_plain(chat_id, t("letter_send_failed"))
