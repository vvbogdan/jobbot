"""
i18n — translations for every string jobbot actually sends to Telegram/ntfy (push text, button
labels, command replies, callback toasts). Code comments and internal/dev log() lines are NOT
part of this — those are English in the source and never shown to the bot's user.

Usage: `from i18n import t` then `t("key", **kwargs)` — looks up BOT_LANG (env var, default
"uk") in TRANSLATIONS, falls back to "uk" if the language or the key is missing, and finally
falls back to returning the key itself (so a typo'd key never crashes the bot, just shows up
oddly in a push — easy to spot and fix).

Adding a language: copy the "uk" block, translate every value, leave the {placeholders} and
HTML tags (<b>, <i>, <code>, <a href=...>) exactly as they are — they're filled in / parsed by
the calling code, not by the translation itself. Keep the keys identical across languages.
"""
import os

BOT_LANG = os.environ.get("BOT_LANG", "uk")

TRANSLATIONS = {
    "uk": {
        # ── generic ──
        "new_job_ntfy_title": "Нова вакансія",
        "age_hours": "{n} год",
        "age_days": "{n} дн",
        "and_n_more": "…і ще {n}.",
        "no_pending": "🎉 Немає вакансій, що очікують відгуку — усе розібрано.",
        "reason_too_old": "старіша за MAX_AGE_DAYS={days} дн.",
        "reason_first_run_limit": "перший запуск — понад ліміт FIRST_RUN_LIMIT={limit}",

        # ── push buttons (send_telegram / send_pending_cards) ──
        "btn_open_apply": "📨 Відкрити / Відгукнутись",
        "btn_tailor_resume": "📄 Адаптувати резюме",
        "btn_regenerate": "🔄 Перегенерувати",
        "btn_cover_letter": "✉️ Супровідний лист",
        "btn_applied": "✅ Відгукнувся",
        "btn_not_interested": "🚫 Не цікаво",

        # ── fmt_message (the push itself) ──
        "push_deadline": "⏳ до {deadline}",
        "push_experience": "досвід: {years}+ р.",
        "push_location_lviv_remote": "📍 Львів/Remote",
        "push_location_kyiv": "📍 Київ",
        "push_remote": "remote",
        "push_reservation": "бронювання",

        # ── main menu keyboard ──
        "menu_stats": "📊 Статистика",
        "menu_pending": "📋 Очікують",
        "menu_backup": "🗄 Бекап",
        "menu_help": "❓ Довідка",

        # ── bot command descriptions (Telegram "/" menu) ──
        "cmd_start_desc": "Довідка та кнопки меню",
        "cmd_stats_desc": "Статистика за {days} дн.",
        "cmd_pending_desc": "Вакансії, що очікують відгуку",
        "cmd_seen_desc": "Мовчки позначені побаченими (без пушу)",
        "cmd_skipped_desc": "Позначені «не цікаво» — можна передумати",
        "cmd_backup_desc": "Надіслати бекап стану зараз",
        "cmd_settings_desc": "Переглянути/змінити налаштування",

        # ── /help ──
        "help_text": (
            "👋 <b>jobbot</b>\n"
            "Я стежу за новими вакансіями на DOU і Djinni під твої профілі і шлю їх сюди одразу "
            "(/profiles — подивитись, /addprofile — додати свій).\n\n"
            "Під кожним пушем є кнопки:\n"
            "📄 <b>Адаптувати резюме</b> — за секунд 10-20 прийде PDF-резюме під цю вакансію "
            "(повторний клік — миттєво з кешу, «🔄 Перегенерувати» під результатом — новий варіант).\n"
            "✉️ <b>Супровідний лист</b> — короткий cover letter під ту саму вакансію (теж кешується).\n"
            "✅ <b>Відгукнувся</b> — познач, щоб бот не нагадував про цю вакансію.\n"
            "🚫 <b>Не цікаво</b> — прибрати вакансію з нагадувань і з «очікують відгуку», не рахуючи "
            "це відгуком.\n\n"
            "Вакансії з AI-agentic / Claude Code позначені ⭐ і йдуть у пуші першими.\n"
            "Якщо за {reminder_hours} год. не позначиш «Відгукнувся» — надішлю нагадування.\n\n"
            "Команди: /stats — статистика за {stats_days} дн. "
            "/pending — список вакансій, що очікують відгуку, одразу з чекбоксами: тиснеш назву — "
            "позначаєш «не цікаво», «🔗 Відкрити» — дивишся вакансію, без переходів деінде. "
            "/seen — вакансії, мовчки позначені побаченими без пушу (занадто старі або обрізані "
            "лімітом першого запуску) — перевірити, чи не пропущено щось важливе. "
            "/skipped — вакансії, позначені «не цікаво»: якщо передумав(ла) чи вакансію "
            "перевідкрили — знімаєш позначку однією кнопкою, і вона повертається в /pending. "
            "/backup — надіслати бекап стану зараз. "
            "/settings — переглянути й змінити налаштування (/set ключ значення) без редеплою. "
            "/profiles — список твоїх профілів пошуку з кнопками видалення. "
            "/addprofile — додати новий профіль покроково (ключові слова, без коду і regex).\n"
            "Нижче — постійні кнопки з тими самими командами, щоб не набирати їх руками.\n\n"
            "Щоб відновити стан — просто перешли мені файл бекапу (state_backup.json) назад у чат."
        ),

        # ── /stats ──
        "stats_period_1_day": "1 день",
        "stats_period_2_4_days": "{n} дні",
        "stats_period_n_days": "{n} днів",
        "stats_header": "📊 <b>За останні {period}</b>",
        "stats_sent": "Надіслано вакансій: {n}",
        "stats_by_profile_line": "  · {label}: {n}",
        "stats_applied": "Відгукнувся: {n}{rate}",
        "stats_skipped": "Не цікаво: {n}",
        "stats_pending": "Очікують відгуку (в кеші): {n}",

        # ── /settings, /set ──
        "settings_header": "⚙️ <b>Налаштування</b> — змінити: <code>/set ключ значення</code>",
        "settings_line": "• <code>{name}</code> = {value}{mark}\n  {desc}",
        "settings_changed_mark": " <i>(змінено)</i>",
        "setting_desc_reminder_hours": "нагадати про відгук через N год (0 = вимкнути)",
        "setting_desc_quiet_hours_start": "тихі години — з котрої (0-24)",
        "setting_desc_quiet_hours_end": "тихі години — до котрої (0-24)",
        "setting_desc_stats_period_days": "вікно для /stats і тижневого дайджесту, дні",
        "setting_desc_backup_interval_hours": "інтервал автобекапу, год (0 = вимкнути)",
        "setting_desc_pending_list_limit": "скільки вакансій показувати в /pending",
        "setting_desc_pending_cards_limit": "ліміт карток за раз у «Показати з кнопками»",
        "setting_desc_seen_list_limit": "скільки вакансій показувати в /seen",
        "set_unknown_key": "невідоме налаштування «{name}». Відомі: {known}",
        "set_not_a_number": "«{value}» — очікувалось число.",
        "set_out_of_range_0_24": "має бути в межах 0-24.",
        "set_must_be_nonnegative": "має бути невід'ємним числом.",
        "set_usage": "Формат: <code>/set ключ значення</code>\n\n{settings}",
        "set_ok": "✅ {key} = {value}",
        "set_error": "⚠️ {error}",

        # ── /profiles, /addprofile ──
        "cmd_profiles_desc": "Профілі пошуку (перегляд/видалення)",
        "cmd_addprofile_desc": "Додати новий профіль пошуку",
        "profiles_empty": "Профілів поки немає. /addprofile — щоб додати перший.",
        "profiles_header": "🧭 <b>Профілі пошуку: {n}</b>",
        "profiles_line": "• <b>{label}</b> — резюме «{resume_key}», фідів: {feeds}",
        "profiles_delete_btn": "🗑 {label}",
        "profiles_deleted": "🗑 Видалено профіль «{label}»",
        "profwiz_start": "➕ <b>Новий профіль пошуку</b> (/cancel — скасувати в будь-який момент)",
        "profwiz_ask_label": "1/6. Назва профілю (як показувати в /profiles), напр. «🎨 Frontend (Junior+)»:",
        "profwiz_label_taken": "Профіль «{label}» вже є. Введи іншу назву, або /cancel.",
        "profwiz_ask_resume_key": (
            "2/6. Ключ резюме для кнопки «Адаптувати резюме» (напр. Frontend). Якщо такого "
            "резюме нема в resumes.py — просто не страшно, кнопки резюме/листа для цього профілю "
            "будуть вимкнені. Можна залишити порожнім — візьму назву профілю."
        ),
        "profwiz_ask_feed_keywords": (
            "3/6. Ключові слова для пошуку на DOU і Djinni, через кому (напр. Frontend, React). "
            "Для кожного слова додам фід з DOU і з Djinni."
        ),
        "profwiz_ask_must_keywords": (
            "4/6. Заголовок вакансії обов'язково має містити одне з цих слів (через кому), "
            "або «-» якщо без обмежень:"
        ),
        "profwiz_ask_exclude_keywords": (
            "5/6. Виключити вакансії, де в заголовку є одне з цих слів (через кому), "
            "або «-» якщо нічого:"
        ),
        "profwiz_ask_exclude_senior": "Виключити Senior/Lead/Principal-позиції?",
        "profwiz_yes": "Так",
        "profwiz_no": "Ні",
        "profwiz_ask_max_years": "6/6. Максимум років досвіду у вимогах (число), або «-» без обмежень:",
        "profwiz_cancelled": "Скасовано.",
        "profwiz_saved": "✅ Профіль «{label}» збережено, фідів: {n_feeds}. /profiles — переглянути всі.",

        # ── /pending (list view) ──
        "pending_header": "📋 <b>Очікують відгуку: {n}</b>",
        "pending_line": "• <a href=\"{link}\">{title}</a> — {age} тому",

        # ── /pending cards mode ──
        "pending_cards_intro": "👇 {n} вакансій нижче — тисни кнопки під кожною.",
        "pending_cards_overflow": (
            "…і ще {n} (понад ліміт {limit} за раз) — розбери видимі вище кнопками, тоді "
            "натисни «Показати з кнопками» під /pending ще раз для решти."
        ),
        "pending_card_text": "<b>{title}</b>\n{age} тому",

        # ── checklist (shared by /pending and /skipped) ──
        "checklist_priority_header": "⭐ — Пріоритет (Львів/Remote, iOS, AI) —",
        "checklist_other_header": "— Інше —",
        "checklist_btn_open": "🔗 Відкрити",
        "checklist_btn_applied": "✅ Відгукнувся",
        "checklist_btn_done": "✅ Готово",
        "checklist_btn_next_page": "➡️ Далі ({n})",
        "checklist_btn_bulk_dismiss_other": "🚫 Відхилити все «Інше» ({n})",
        "checklist_btn_switch_to_cards": "🔘 Відгукнувся/Не цікаво по черзі (картками)",
        "pending_checklist_text": (
            "📋 <b>Очікують відгуку: {n}</b>\n"
            "☑️ тисни назву, щоб позначити «не цікаво» (можна й повернути назад), "
            "«🔗 Відкрити» — переглянути вакансію. Пріоритетна група (Львів/Remote, iOS, AI) — "
            "зверху, решта — нижче під «— Інше —»; «🚫 Відхилити все «Інше»» одним тапом "
            "позначає всю нижню групу, якщо там нема нічого цікавого."
        ),
        "checklist_page_note_more": "\n\n(показано {start}–{end} з {total} — тисни «➡️ Далі» для решти)",
        "checklist_page_note_last": "\n\n(показано {start}–{end} з {total})",
        "skipped_checklist_text": (
            "🚫 <b>Позначені «не цікаво»</b> — тисни назву, щоб зняти позначку: вакансія одразу\n"
            "повернеться в «Очікують відгуку» в /pending (напр. якщо її перевідкрили і хочеш "
            "знову податись), потім тисни «Готово»."
        ),
        "no_skipped": "📭 Немає вакансій, позначених «не цікаво».",

        # ── checklist callback toasts ──
        "toast_marked_not_interested": "🚫 Позначено як «не цікаво»",
        "toast_marked_applied": "✅ Позначено як «відгукнувся»",
        "toast_unmarked": "↩️ Позначку знято",
        "toast_job_gone": "⚠️ Вакансія вже зникла з кешу.",
        "toast_done": "✅ Готово",
        "toast_bulk_dismissed": "🚫 Відхилено «Інше»: {n}",
        "toast_preparing_resume": "⏳ Готую резюме…",
        "toast_regenerating_resume": "⏳ Перегенеровую резюме…",
        "toast_preparing_letter": "⏳ Готую лист…",
        "toast_regenerating_letter": "⏳ Перегенеровую лист…",

        # ── /seen ──
        "seen_empty": "🤷 Лог порожній — нічого не позначалось «побаченим» без пушу за останні {days} дн.",
        "seen_header": "👀 <b>Мовчки позначено «побаченим» (без пушу): {n}</b> за останні {days} дн.",
        "seen_line": "• <a href=\"{link}\">{title}</a> — {reason} — {age} тому",

        # ── resume tailoring (handle_cv_request) ──
        "job_stale_in_cache": "⚠️ Вакансія вже застаріла в кеші — відкрий її за посиланням із пуша.",
        "anthropic_key_missing_resume": "⚠️ Не задано ANTHROPIC_API_KEY на сервері — адаптація резюме вимкнена.",
        "tailoring_resume_for": "⏳ Адаптую резюме під «{title}»…",
        "resume_adapt_error": "⚠️ Помилка адаптації резюме: {error}",
        "resume_caption": "Резюме під: {title}{note}",
        "note_from_cache_no_api_call": " (з кешу — без нового запиту в Claude)",
        "resume_send_failed": "⚠️ Не вдалося надіслати PDF у Telegram.",
        "resume_render_error": "⚠️ Помилка рендеру PDF: {error}",

        # ── cover letter (handle_cl_request) ──
        "anthropic_key_missing_letter": "⚠️ Не задано ANTHROPIC_API_KEY на сервері — генерація листа вимкнена.",
        "writing_letter_for": "⏳ Пишу супровідний лист під «{title}»…",
        "letter_generate_error": "⚠️ Помилка генерації листа: {error}",
        "note_from_cache": " (з кешу)",
        "cover_letter_text": "✉️ <b>Супровідний лист</b>{note}\n<i>{title}</i>\n\n{letter}",
        "letter_send_failed": "⚠️ Не вдалося надіслати лист у Telegram.",

        # ── reminders ──
        "reminder_text": "⏰ Минуло {hours}+ год., а на вакансію ще не відмічено відгук:\n<b>{title}</b>\n{link}",

        # ── weekly digest ──
        "weekly_digest_header": "🗓 <b>Тижневий дайджест</b>\n\n",
        "overnight_digest_header": "🌅 Нічний дайджест — {n} вакансій, поки було тихо:",

        # ── feed health ──
        "feed_recovered": "✅ {src} знову віддає RSS як слід:\n{url}",
        "feed_failing": (
            "⚠️ {src} не віддає RSS вже {n} прогонів поспіль — схоже на технічну проблему "
            "з фідом, а не на відсутність вакансій:\n{url}"
        ),

        # ── backup / restore ──
        "no_state_to_backup": "⚠️ Ще немає state.json для бекапу.",
        "backup_caption": "🗄 Бекап стану jobbot — {date}",
        "backup_manual_note": "(запит вручну)",
        "restoring_state_from": "⏳ Відновлюю стан з «{filename}»…",
        "state_restored": "✅ Стан відновлено: {jobs} вакансій у кеші, {seen} позначено побаченими.",
        "restore_failed": "⚠️ Не вдалося відновити стан: {error}",
        "restore_invalid_file": "файл не схожий на бекап стану jobbot (немає полів jobs/seen)",
        "auto_restored": (
            "🔄 Диск скинувся (типово для Render Free) — автоматично відновив стан із "
            "закріпленого бекапу: {jobs} вакансій у кеші, {seen} позначено побаченими."
        ),

        # ── main() / --test ──
        "test_push_text": "✅ <b>jobbot</b> працює. Нові вакансії приходитимуть сюди.",
        "test_ntfy_text": "jobbot працює",
    },
    "en": {
        "new_job_ntfy_title": "New job",
        "age_hours": "{n}h",
        "age_days": "{n}d",
        "and_n_more": "…and {n} more.",
        "no_pending": "🎉 No jobs awaiting a response — all done.",
        "reason_too_old": "older than MAX_AGE_DAYS={days} days",
        "reason_first_run_limit": "first run — over the FIRST_RUN_LIMIT={limit} cap",

        "btn_open_apply": "📨 Open / Apply",
        "btn_tailor_resume": "📄 Tailor resume",
        "btn_regenerate": "🔄 Regenerate",
        "btn_cover_letter": "✉️ Cover letter",
        "btn_applied": "✅ Applied",
        "btn_not_interested": "🚫 Not interested",

        "push_deadline": "⏳ by {deadline}",
        "push_experience": "experience: {years}+ yr",
        "push_location_lviv_remote": "📍 Lviv/Remote",
        "push_location_kyiv": "📍 Kyiv",
        "push_remote": "remote",
        "push_reservation": "draft-exempt",

        "menu_stats": "📊 Stats",
        "menu_pending": "📋 Pending",
        "menu_backup": "🗄 Backup",
        "menu_help": "❓ Help",

        "cmd_start_desc": "Help and menu buttons",
        "cmd_stats_desc": "Stats for the last {days} days",
        "cmd_pending_desc": "Jobs awaiting a response",
        "cmd_seen_desc": "Silently marked as seen (no push)",
        "cmd_skipped_desc": "Marked \"not interested\" — can be undone",
        "cmd_backup_desc": "Send a state backup now",
        "cmd_settings_desc": "View/change settings",

        "help_text": (
            "👋 <b>jobbot</b>\n"
            "I watch for new jobs on DOU and Djinni matching your profiles and push them here "
            "right away (/profiles to see them, /addprofile to add your own).\n\n"
            "Every push has buttons:\n"
            "📄 <b>Tailor resume</b> — in 10-20 seconds you'll get a PDF resume tailored to this "
            "job (a repeat click is instant from cache, \"🔄 Regenerate\" under the result makes "
            "a new version).\n"
            "✉️ <b>Cover letter</b> — a short cover letter for the same job (also cached).\n"
            "✅ <b>Applied</b> — mark it so the bot stops reminding you about this job.\n"
            "🚫 <b>Not interested</b> — remove the job from reminders and from \"pending\", "
            "without counting it as an application.\n\n"
            "Jobs mentioning AI-agentic / Claude Code are marked ⭐ and pushed first.\n"
            "If you don't mark \"Applied\" within {reminder_hours}h, I'll send a reminder.\n\n"
            "Commands: /stats — stats for the last {stats_days} days. "
            "/pending — list of jobs awaiting a response, right away with checkboxes: tap the "
            "title to mark \"not interested\", \"🔗 Open\" to view the job, no need to go "
            "elsewhere. /seen — jobs silently marked as seen with no push (too old, or trimmed "
            "by the first-run limit) — check that nothing important was missed. /skipped — jobs "
            "marked \"not interested\": if you changed your mind or the job got reposted, one "
            "button unmarks it and it returns to /pending. /backup — send a state backup now. "
            "/settings — view and change settings (/set key value) without redeploying. "
            "/profiles — your search profiles, with delete buttons. "
            "/addprofile — add a new profile step by step (plain keywords, no code or regex).\n"
            "Below are persistent buttons for the same commands, so you don't have to type "
            "them.\n\n"
            "To restore the state — just forward the backup file (state_backup.json) back to "
            "me in this chat."
        ),

        "stats_period_1_day": "1 day",
        "stats_period_2_4_days": "{n} days",
        "stats_period_n_days": "{n} days",
        "stats_header": "📊 <b>Last {period}</b>",
        "stats_sent": "Jobs sent: {n}",
        "stats_by_profile_line": "  · {label}: {n}",
        "stats_applied": "Applied: {n}{rate}",
        "stats_skipped": "Not interested: {n}",
        "stats_pending": "Awaiting response (cached): {n}",

        "settings_header": "⚙️ <b>Settings</b> — change with: <code>/set key value</code>",
        "settings_line": "• <code>{name}</code> = {value}{mark}\n  {desc}",
        "settings_changed_mark": " <i>(changed)</i>",
        "setting_desc_reminder_hours": "remind about applying after N hours (0 = off)",
        "setting_desc_quiet_hours_start": "quiet hours — starting at (0-24)",
        "setting_desc_quiet_hours_end": "quiet hours — until (0-24)",
        "setting_desc_stats_period_days": "window for /stats and the weekly digest, days",
        "setting_desc_backup_interval_hours": "auto-backup interval, hours (0 = off)",
        "setting_desc_pending_list_limit": "how many jobs to show in /pending",
        "setting_desc_pending_cards_limit": "card limit per batch in \"Show with buttons\"",
        "setting_desc_seen_list_limit": "how many jobs to show in /seen",
        "set_unknown_key": "unknown setting \"{name}\". Known: {known}",
        "set_not_a_number": "\"{value}\" — expected a number.",
        "set_out_of_range_0_24": "must be between 0 and 24.",
        "set_must_be_nonnegative": "must be a non-negative number.",
        "set_usage": "Usage: <code>/set key value</code>\n\n{settings}",
        "set_ok": "✅ {key} = {value}",
        "set_error": "⚠️ {error}",

        # ── /profiles, /addprofile ──
        "cmd_profiles_desc": "Search profiles (view/delete)",
        "cmd_addprofile_desc": "Add a new search profile",
        "profiles_empty": "No profiles yet. /addprofile to add your first one.",
        "profiles_header": "🧭 <b>Search profiles: {n}</b>",
        "profiles_line": "• <b>{label}</b> — resume \"{resume_key}\", feeds: {feeds}",
        "profiles_delete_btn": "🗑 {label}",
        "profiles_deleted": "🗑 Deleted profile \"{label}\"",
        "profwiz_start": "➕ <b>New search profile</b> (/cancel to stop at any point)",
        "profwiz_ask_label": "1/6. Profile name (shown in /profiles), e.g. \"🎨 Frontend (Junior+)\":",
        "profwiz_label_taken": "Profile \"{label}\" already exists. Pick another name, or /cancel.",
        "profwiz_ask_resume_key": (
            "2/6. Resume key for the \"Tailor resume\" button (e.g. Frontend). If there's no such "
            "resume in resumes.py, that's fine — the resume/cover-letter buttons just stay "
            "disabled for this profile. Leave blank to reuse the profile name."
        ),
        "profwiz_ask_feed_keywords": (
            "3/6. Keywords to search for on DOU and Djinni, comma-separated (e.g. Frontend, "
            "React). Each one adds a DOU feed and a Djinni feed."
        ),
        "profwiz_ask_must_keywords": (
            "4/6. The job title must contain one of these words (comma-separated), "
            "or \"-\" for no restriction:"
        ),
        "profwiz_ask_exclude_keywords": (
            "5/6. Exclude jobs whose title contains one of these words (comma-separated), "
            "or \"-\" for none:"
        ),
        "profwiz_ask_exclude_senior": "Exclude Senior/Lead/Principal roles?",
        "profwiz_yes": "Yes",
        "profwiz_no": "No",
        "profwiz_ask_max_years": "6/6. Max years of experience required (a number), or \"-\" for no limit:",
        "profwiz_cancelled": "Cancelled.",
        "profwiz_saved": "✅ Profile \"{label}\" saved, feeds: {n_feeds}. /profiles to see them all.",

        "pending_header": "📋 <b>Awaiting response: {n}</b>",
        "pending_line": "• <a href=\"{link}\">{title}</a> — {age} ago",

        "pending_cards_intro": "👇 {n} jobs below — tap the buttons under each.",
        "pending_cards_overflow": (
            "…and {n} more (over the {limit}-per-batch limit) — work through the ones shown "
            "above, then tap \"Show with buttons\" under /pending again for the rest."
        ),
        "pending_card_text": "<b>{title}</b>\n{age} ago",

        "checklist_priority_header": "⭐ — Priority (Lviv/Remote, iOS, AI) —",
        "checklist_other_header": "— Other —",
        "checklist_btn_open": "🔗 Open",
        "checklist_btn_applied": "✅ Applied",
        "checklist_btn_done": "✅ Done",
        "checklist_btn_next_page": "➡️ Next ({n})",
        "checklist_btn_bulk_dismiss_other": "🚫 Dismiss all \"Other\" ({n})",
        "checklist_btn_switch_to_cards": "🔘 Applied/Not interested one by one (cards)",
        "pending_checklist_text": (
            "📋 <b>Awaiting response: {n}</b>\n"
            "☑️ tap a title to mark it \"not interested\" (can be undone), "
            "\"🔗 Open\" to view the job. The priority group (Lviv/Remote, iOS, AI) is on top, "
            "the rest is below under \"— Other —\"; \"🚫 Dismiss all 'Other'\" marks the whole "
            "bottom group in one tap if there's nothing interesting there."
        ),
        "checklist_page_note_more": "\n\n(showing {start}–{end} of {total} — tap \"➡️ Next\" for the rest)",
        "checklist_page_note_last": "\n\n(showing {start}–{end} of {total})",
        "skipped_checklist_text": (
            "🚫 <b>Marked \"not interested\"</b> — tap a title to unmark it: the job\n"
            "immediately returns to \"Awaiting response\" in /pending (e.g. if it got reposted "
            "and you want to apply again), then tap \"Done\"."
        ),
        "no_skipped": "📭 No jobs marked \"not interested\".",

        "toast_marked_not_interested": "🚫 Marked \"not interested\"",
        "toast_marked_applied": "✅ Marked \"applied\"",
        "toast_unmarked": "↩️ Mark removed",
        "toast_job_gone": "⚠️ The job has already dropped out of the cache.",
        "toast_done": "✅ Done",
        "toast_bulk_dismissed": "🚫 Dismissed \"Other\": {n}",
        "toast_preparing_resume": "⏳ Preparing resume…",
        "toast_regenerating_resume": "⏳ Regenerating resume…",
        "toast_preparing_letter": "⏳ Preparing letter…",
        "toast_regenerating_letter": "⏳ Regenerating letter…",

        "seen_empty": "🤷 Log is empty — nothing was silently marked \"seen\" with no push in the last {days} days.",
        "seen_header": "👀 <b>Silently marked \"seen\" (no push): {n}</b> in the last {days} days.",
        "seen_line": "• <a href=\"{link}\">{title}</a> — {reason} — {age} ago",

        "job_stale_in_cache": "⚠️ The job has already aged out of the cache — open it via the link from the push.",
        "anthropic_key_missing_resume": "⚠️ ANTHROPIC_API_KEY isn't set on the server — resume tailoring is disabled.",
        "tailoring_resume_for": "⏳ Tailoring resume for \"{title}\"…",
        "resume_adapt_error": "⚠️ Error tailoring the resume: {error}",
        "resume_caption": "Resume for: {title}{note}",
        "note_from_cache_no_api_call": " (from cache — no new Claude request)",
        "resume_send_failed": "⚠️ Failed to send the PDF to Telegram.",
        "resume_render_error": "⚠️ Error rendering the PDF: {error}",

        "anthropic_key_missing_letter": "⚠️ ANTHROPIC_API_KEY isn't set on the server — cover letter generation is disabled.",
        "writing_letter_for": "⏳ Writing a cover letter for \"{title}\"…",
        "letter_generate_error": "⚠️ Error generating the letter: {error}",
        "note_from_cache": " (from cache)",
        "cover_letter_text": "✉️ <b>Cover letter</b>{note}\n<i>{title}</i>\n\n{letter}",
        "letter_send_failed": "⚠️ Failed to send the letter to Telegram.",

        "reminder_text": "⏰ {hours}+ hours have passed and this job still isn't marked as applied:\n<b>{title}</b>\n{link}",

        "weekly_digest_header": "🗓 <b>Weekly digest</b>\n\n",
        "overnight_digest_header": "🌅 Overnight digest — {n} jobs while it was quiet:",

        "feed_recovered": "✅ {src} is serving RSS normally again:\n{url}",
        "feed_failing": (
            "⚠️ {src} has failed to serve RSS for {n} runs in a row — looks like a technical "
            "feed issue, not an absence of jobs:\n{url}"
        ),

        "no_state_to_backup": "⚠️ There's no state.json yet to back up.",
        "backup_caption": "🗄 jobbot state backup — {date}",
        "backup_manual_note": "(manual request)",
        "restoring_state_from": "⏳ Restoring state from \"{filename}\"…",
        "state_restored": "✅ State restored: {jobs} jobs cached, {seen} marked as seen.",
        "restore_failed": "⚠️ Failed to restore the state: {error}",
        "restore_invalid_file": "this doesn't look like a jobbot state backup (missing jobs/seen fields)",
        "auto_restored": (
            "🔄 The disk was wiped (typical for Render Free) — automatically restored the "
            "state from the pinned backup: {jobs} jobs cached, {seen} marked as seen."
        ),

        "test_push_text": "✅ <b>jobbot</b> is running. New jobs will arrive here.",
        "test_ntfy_text": "jobbot is running",
    },
}


def t(key, **kwargs):
    """Looks up `key` for BOT_LANG, falling back to "uk" if the language or the key itself is
    missing there, and finally to the bare key (so a typo'd key shows up oddly in a push instead
    of crashing the bot — easy to notice and fix, as opposed to a silent KeyError mid-request)."""
    table = TRANSLATIONS.get(BOT_LANG, TRANSLATIONS["uk"])
    template = table.get(key) or TRANSLATIONS["uk"].get(key) or key
    return template.format(**kwargs) if kwargs else template
