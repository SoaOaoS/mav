"""Traduit le flux d'événements d'une session en une ligne d'état lisible.

Telegram limite la fréquence d'édition d'un message : on regroupe donc les
événements et on n'édite qu'au-delà d'un intervalle minimum, et seulement si
le texte a réellement changé.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time

log = logging.getLogger("ocprogress")

EDIT_INTERVAL = 3.0  # secondes entre deux éditions du message d'état

# Étiquettes lisibles pour les outils courants. Les serveurs MCP sont préfixés
# par leur nom (github_*, notion_*), on les traite génériquement.
TOOL_LABELS = {
    "websearch": "recherche web",
    "webfetch": "lecture d'une page",
    "read": "lecture de fichier",
    "write": "écriture de fichier",
    "edit": "modification de fichier",
    "bash": "commande shell",
    "grep": "recherche dans le code",
    "glob": "parcours de fichiers",
    "task": "délégation à un sous-agent",
    "todowrite": "mise à jour du plan",
    "apply_patch": "application d'un patch",
}


def tool_label(name: str) -> str:
    if name in TOOL_LABELS:
        return TOOL_LABELS[name]
    if "_" in name:
        server, _, rest = name.partition("_")
        return f"{server} : {rest.replace('_', ' ')}"
    return name


def human_delay(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


class ProgressTracker:
    """Accumule l'état d'une session en cours et produit le texte à afficher."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.current: str | None = None
        self.steps = 0
        self.tool_counts: dict[str, int] = {}
        self.last_tool: str | None = None
        self.compacting = False
        self.error: str | None = None
        self.done = False
        self.text_chars = 0

    # ------------------------------------------------------------- ingestion

    def feed(self, event: dict) -> None:
        etype = event.get("type", "")
        props = event.get("properties") or {}

        if etype == "session.next.step.started":
            self.steps += 1
            self.current = "réflexion"
        elif etype == "session.next.tool.called":
            tool = props.get("tool", "?")
            self.last_tool = tool
            self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
            self.current = tool_label(tool)
        elif etype == "session.next.tool.failed":
            self.current = f"{tool_label(props.get('tool', '?'))} — échec, reprise"
        elif etype in ("session.next.text.started", "session.next.text.delta"):
            self.current = "rédaction de la réponse"
            self.text_chars += len(props.get("delta", "") or "")
        elif etype == "session.next.reasoning.started":
            self.current = "réflexion"
        elif etype == "session.next.compaction.started":
            self.compacting = True
            self.current = "compactage du contexte"
        elif etype == "session.next.compaction.ended":
            self.compacting = False
        elif etype == "session.next.retried":
            self.current = "nouvelle tentative"
        elif etype == "session.error":
            err = props.get("error") or {}
            name = err.get("name") or err.get("_tag") or "erreur"
            self.error = str(name)
            self.done = True
        elif etype == "session.idle":
            self.done = True

    # --------------------------------------------------------------- rendu

    def render(self) -> str:
        elapsed = human_delay(time.monotonic() - self.started)
        if self.error:
            return f"⚠️ {html.escape(self.error)} — après {elapsed}"

        head = f"⏳ <b>{html.escape(self.current or 'démarrage')}</b>  ·  {elapsed}"

        detail = []
        if self.steps > 1:
            detail.append(f"{self.steps} étapes")
        total_tools = sum(self.tool_counts.values())
        if total_tools:
            top = sorted(self.tool_counts.items(), key=lambda x: -x[1])[:3]
            detail.append(
                ", ".join(
                    f"{tool_label(t)} ×{n}" if n > 1 else tool_label(t) for t, n in top
                )
            )
        if self.compacting:
            detail.append("contexte saturé, compactage en cours")

        if not detail:
            return head
        return head + "\n<i>" + html.escape(" · ".join(detail)) + "</i>"


async def follow(
    queue: asyncio.Queue,
    tracker: ProgressTracker,
    on_update,
    idle_timeout: float | None = None,
) -> ProgressTracker:
    """Consomme la file d'événements jusqu'à session.idle.

    on_update(texte) est appelé au plus une fois toutes les EDIT_INTERVAL
    secondes, et uniquement si le rendu a changé.
    """
    last_edit = 0.0
    last_text = ""

    while not tracker.done:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
        except asyncio.TimeoutError:
            tracker.error = "aucun événement reçu (session bloquée ?)"
            tracker.done = True
            break

        tracker.feed(event)

        now = time.monotonic()
        if tracker.done:
            break
        if now - last_edit >= EDIT_INTERVAL:
            text = tracker.render()
            if text != last_text:
                last_text = text
                last_edit = now
                try:
                    await on_update(text)
                except Exception as exc:  # noqa: BLE001
                    log.debug("édition du message d'état ignorée: %s", exc)

    return tracker
