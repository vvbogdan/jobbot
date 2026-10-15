# -*- coding: utf-8 -*-
"""wizard — the interactive /addprofile flow: a step-by-step Q&A over plain Telegram messages
that builds up a new search profile and saves it via bot.state once every step is answered.
state.py owns the persistence (build_profile_from_wizard/add_profile); this module only owns the
conversation — which step a chat is on and what to ask next.

Seventh extraction step of jobbot.py's split into focused modules.
"""
from .i18n import t
from .telegram_api import send_telegram_plain
from .state import get_profiles, build_profile_from_wizard, add_profile

# In-memory only — an interrupted wizard (bot restart mid-flow) is simply abandoned, which is
# fine for a single-user bot; nothing of value is lost (the profile isn't saved until the final
# confirm step).
PROFILE_WIZARD = {}

PROFILE_WIZARD_STEPS = ["label", "resume_key", "feed_keywords", "must_keywords",
                        "exclude_keywords", "exclude_senior", "max_years"]


def start_profile_wizard(chat_id):
    PROFILE_WIZARD[chat_id] = {"step": 0, "data": {}}
    send_telegram_plain(chat_id, t("profwiz_start") + "\n\n" + t("profwiz_ask_label"))


def cancel_profile_wizard(chat_id):
    PROFILE_WIZARD.pop(chat_id, None)
    send_telegram_plain(chat_id, t("profwiz_cancelled"))


def handle_profile_wizard_text(chat_id, raw_text):
    """Returns True if `raw_text` was consumed as an answer in an ongoing /addprofile wizard for
    this chat (so the normal command dispatch in poll_telegram_loop should skip it)."""
    wiz = PROFILE_WIZARD.get(chat_id)
    if wiz is None:
        return False
    if raw_text.lower() in ("/cancel", "скасувати", "cancel"):
        cancel_profile_wizard(chat_id)
        return True
    step = PROFILE_WIZARD_STEPS[wiz["step"]]
    text = raw_text.strip()

    if step == "label":
        if not text:
            send_telegram_plain(chat_id, t("profwiz_ask_label"))
            return True
        if text in get_profiles():
            send_telegram_plain(chat_id, t("profwiz_label_taken", label=text))
            return True
        wiz["data"]["label"] = text
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_resume_key"))
        return True

    if step == "resume_key":
        wiz["data"]["resume_key"] = text or wiz["data"]["label"]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_feed_keywords"))
        return True

    if step == "feed_keywords":
        kws = [k for k in (p.strip() for p in text.split(",")) if k]
        if not kws:
            send_telegram_plain(chat_id, t("profwiz_ask_feed_keywords"))
            return True
        wiz["data"]["feed_keywords"] = kws
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_must_keywords"))
        return True

    if step == "must_keywords":
        wiz["data"]["must_keywords"] = [] if text == "-" else [k.strip() for k in text.split(",") if k.strip()]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_exclude_keywords"))
        return True

    if step == "exclude_keywords":
        wiz["data"]["exclude_keywords"] = [] if text == "-" else [k.strip() for k in text.split(",") if k.strip()]
        wiz["step"] += 1
        send_telegram_plain(chat_id, t("profwiz_ask_exclude_senior"),
                             buttons=[[{"text": "✅ " + t("profwiz_yes"), "callback_data": "profwiz_senior|yes"},
                                       {"text": "❌ " + t("profwiz_no"), "callback_data": "profwiz_senior|no"}]])
        return True

    if step == "exclude_senior":
        # handled via inline buttons (profwiz_senior|yes|no callback), not free text — but accept
        # a typed yes/no too, in case someone answers by typing instead of tapping the button.
        yes = text.lower() in ("так", "yes", "y", "т")
        _profile_wizard_set_senior_and_advance(chat_id, yes)
        return True

    if step == "max_years":
        if text == "-":
            wiz["data"]["max_years"] = None
        else:
            try:
                wiz["data"]["max_years"] = int(text)
            except ValueError:
                send_telegram_plain(chat_id, t("profwiz_ask_max_years"))
                return True
        _finish_profile_wizard(chat_id)
        return True

    return True


def _profile_wizard_set_senior_and_advance(chat_id, yes):
    wiz = PROFILE_WIZARD.get(chat_id)
    if wiz is None:
        return
    wiz["data"]["exclude_senior"] = yes
    wiz["step"] += 1
    send_telegram_plain(chat_id, t("profwiz_ask_max_years"))


def _finish_profile_wizard(chat_id):
    wiz = PROFILE_WIZARD.pop(chat_id, None)
    if wiz is None:
        return
    profile = build_profile_from_wizard(wiz["data"])
    add_profile(wiz["data"]["label"], profile)
    send_telegram_plain(chat_id, t("profwiz_saved", label=wiz["data"]["label"],
                                    n_keywords=len(profile["keywords"])))
