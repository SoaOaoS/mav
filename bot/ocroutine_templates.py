"""Ready-made routines, so creating one takes two clicks instead of a form.

Each template is a plain job skeleton (same shape as jobs.json) plus a short
label and description shown in the dashboard. Nothing here calls the model or
the network; the API just copies a template into jobs.json when asked.
"""

from __future__ import annotations

__all__ = ["TEMPLATES", "EN", "get", "localized", "as_jobs"]

# `when` is kept human-readable here and expanded by the API into the concrete
# time/days/every_minutes fields. `agent` must be one of the everyday helpers.
TEMPLATES: list[dict] = [
    {
        "id": "morning-brief",
        "label": "Brief du matin",
        "description": "Un résumé de la journée : agenda, météo, ce qui compte.",
        "icon": "☀️",
        "agent": "assistant",
        "when": {"time": "07:30", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "prompt": (
            "Fais-moi un brief de la journée : la météo de mon lieu, "
            "les événements de mon agenda, et les 3 choses qui méritent mon "
            "attention aujourd'hui. Va à l'essentiel, en quelques lignes."
        ),
    },
    {
        "id": "evening-recap",
        "label": "Bilan du soir",
        "description": "Ce qui s'est passé aujourd'hui et ce qu'il reste à faire.",
        "icon": "🌙",
        "agent": "assistant",
        "when": {"time": "20:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "prompt": (
            "Fais le point sur ma journée : ce qui a été fait, ce qui reste, "
            "et ce qu'il vaut mieux préparer pour demain. Sois bref."
        ),
    },
    {
        "id": "weekly-review",
        "label": "Revue hebdo",
        "description": "Un récap de la semaine, le vendredi en fin de journée.",
        "icon": "📋",
        "agent": "assistant",
        "when": {"time": "17:30", "days": ["fri"]},
        "prompt": (
            "Fais ma revue hebdomadaire : ce qui a avancé, ce qui a bloqué, "
            "et 3 priorités concrètes pour la semaine prochaine."
        ),
    },
    {
        "id": "monthly-review",
        "label": "Revue mensuelle",
        "description": "Un bilan le dernier jour du mois.",
        "icon": "🗓️",
        "agent": "assistant",
        "when": {"time": "18:00", "last_day_of_month": True},
        "prompt": (
            "Fais mon bilan mensuel : ce qui compte ce mois-ci, les dépenses "
            "notables si tu les connais, et un objectif clair pour le mois prochain."
        ),
    },
    {
        "id": "rain-reminder",
        "label": "Parapluie s'il pleut",
        "description": "Un rappel le matin, mais seulement s'il va pleuvoir.",
        "icon": "☔",
        "agent": "assistant",
        "when": {"time": "07:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "prompt": (
            "Dis-moi s'il va pleuvoir dans la journée et à quelle heure, "
            "pour que je prenne un parapluie. Si tu n'as pas la météo, réponds RAS."
        ),
    },
    {
        "id": "news-digest",
        "label": "Veille d'actualité",
        "description": "Les titres qui comptent sur un sujet, chaque matin.",
        "icon": "📰",
        "agent": "researcher",
        "when": {"time": "08:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "prompt": (
            "Résume l'actualité du jour sur les sujets qui me concernent, "
            "en 5 titres maximum, avec la source et pourquoi ça compte."
        ),
    },
    {
        "id": "inbox-triage",
        "label": "Tri des mails",
        "description": "Un résumé de ce qui mérite une réponse, le matin.",
        "icon": "✉️",
        "agent": "assistant",
        "when": {"time": "08:30", "days": ["mon", "tue", "wed", "thu", "fri"]},
        "prompt": (
            "Regarde ma boîte mail et dis-moi ce qui mérite une réponse "
            "aujourd'hui, avec une proposition de réponse courte pour chaque. "
            "S'il n'y a rien d'urgent, réponds RAS."
        ),
    },
    {
        "id": "weekly-planning",
        "label": "Planning de la semaine",
        "description": "Anticipe la semaine, le dimanche soir.",
        "icon": "🧭",
        "agent": "planner",
        "when": {"time": "19:00", "days": ["sun"]},
        "prompt": (
            "Aide-moi à préparer ma semaine : les rendez-vous, les échéances, "
            "et un plan réaliste pour les 3 choses les plus importantes."
        ),
    },
    {
        "id": "mail-watch",
        "label": "Veille mail",
        "description": "Repère les mails qui méritent une réponse et prépare une réponse dans le fil.",
        "icon": "✉️",
        "agent": "assistant",
        # Runs every 30 minutes. Needs Mail set up in Settings → Connections.
        "when": {"every_minutes": 30},
        "requires": "mail",
        "prompt": (
            "Veille de la boîte mail. Exécute d'abord : "
            "python3 /home/opencode/.config/opencode/mail.py inbox 15\n\n"
            "Regarde uniquement les mails ARRIVÉS DANS LES 30 DERNIÈRES MINUTES "
            "(d'après le champ Date ; ignore tout ce qui est plus ancien).\n\n"
            "IGNORE sans exception : publicités, promotions, newsletters, "
            "notifications automatiques (réseaux sociaux, apps, banques, "
            "livraisons, code, CI), reçus, confirmations, et tout expéditeur "
            "no-reply / donotreply / noreply / notification / mailing.\n\n"
            "S'il ne reste AUCUN mail personnel qui attend une action ou une "
            "réponse de ma part, réponds exactement : RAS\n\n"
            "Sinon, pour chaque mail qui compte (2 au maximum), appelle l'outil "
            "mail_reply_draft avec uid = l'UID du mail (le nombre entre crochets) "
            "et body = ta réponse prête à envoyer, dans ma langue, ton naturel et "
            "concis. L'outil pose le destinataire, l'objet « Re: … » et le lien de "
            "fil (In-Reply-To).\n\n"
            "Puis réponds en 2 lignes maximum : expéditeur + sujet, et pourquoi "
            "ça compte. Ne mets pas le brouillon dans ta réponse (il est dans "
            "Drafts). Si mail_reply_draft n'est pas disponible, utilise save_draft.\n\n"
            "Ne réponds à rien et n'envoie rien toi-même."
        ),
    },
]


# English wording (label, description, prompt). The catalog above is the
# French original; `localized()` picks one by language. A prompt left out
# here (None) keeps the French one — the model still answers in the user's
# language. NOTHING TO REPORT is a quiet answer for the worker, like RAS.
EN: dict[str, tuple[str, str, str | None]] = {
    "morning-brief": (
        "Morning brief", "A summary of the day: calendar, weather, what matters.",
        "Give me a brief of the day: the weather where I live, the events in my "
        "calendar, and the 3 things that deserve my attention today. Keep it to "
        "a few lines.",
    ),
    "evening-recap": (
        "Evening recap", "What happened today and what is left to do.",
        "Review my day: what got done, what is left, and what is worth "
        "preparing for tomorrow. Keep it short.",
    ),
    "weekly-review": (
        "Weekly review", "A recap of the week, on Friday afternoon.",
        "Do my weekly review: what moved forward, what got stuck, and 3 "
        "concrete priorities for next week.",
    ),
    "monthly-review": (
        "Monthly review", "A look back on the last day of the month.",
        "Do my monthly review: what mattered this month, notable spending if "
        "you know it, and one clear goal for next month.",
    ),
    "rain-reminder": (
        "Umbrella if it rains", "A morning reminder, only when it will rain.",
        "Tell me whether it will rain today and at what time, so I take an "
        "umbrella. If you have no weather data, reply exactly: NOTHING TO REPORT",
    ),
    "news-digest": (
        "News digest", "The headlines that matter on a topic, every morning.",
        "Summarise today's news on the topics I care about: 5 headlines at "
        "most, each with its source and why it matters.",
    ),
    "inbox-triage": (
        "Inbox triage", "What deserves a reply, every morning.",
        "Look at my inbox and tell me what deserves a reply today, with a "
        "short suggested reply for each. If nothing is urgent, reply exactly: "
        "NOTHING TO REPORT",
    ),
    "weekly-planning": (
        "Plan the week", "Get ahead of the week, on Sunday evening.",
        "Help me prepare my week: appointments, deadlines, and a realistic "
        "plan for the 3 most important things.",
    ),
    "mail-watch": (
        "Mail watch", "Spots the emails that need a reply and drafts one in the thread.",
        None,
    ),
}


def localized(t: dict, lang: str = "fr") -> dict:
    """A copy of template `t` worded for `lang` (French or English)."""
    if (lang or "").lower().startswith("fr") or t["id"] not in EN:
        return dict(t)
    label, desc, prompt = EN[t["id"]]
    return {**t, "label": label, "description": desc, "prompt": prompt or t["prompt"]}


def get(template_id: str, lang: str = "fr") -> dict | None:
    t = next((t for t in TEMPLATES if t["id"] == template_id), None)
    return localized(t, lang) if t else None


def as_jobs(lang: str = "fr") -> list[dict]:
    """The catalog as sent to the dashboard (no schedule expansion here)."""
    return [
        {
            "id": t["id"],
            "label": t["label"],
            "description": t["description"],
            "icon": t.get("icon", "🔁"),
            "agent": t.get("agent", ""),
            "when": t.get("when", {}),
            "prompt": t["prompt"],
            "conditional": bool(t.get("skip_if")),
            "requires": t.get("requires", ""),
        }
        for t in (localized(x, lang) for x in TEMPLATES)
    ]
