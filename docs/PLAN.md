# Mav — backlog features (users)

Ce qui est déjà là : chat style ChatGPT, Helpers, mémoire Postgres (+ extraction
auto de faits), Routines, « Keep an eye on » (page / prix / actu), « For you »,
push web, PWA, thème sombre, ⌘K, dictée + lecture vocale, pièces jointes,
graphiques et téléchargements inline, débats multi-agents, catalogue MCP,
bouton de mise à jour, backup CLI.

Ci-dessous, ce qui reste à construire. Effort : **S** ≈ quelques jours,
**M** ≈ 1-2 semaines, **L** ≈ chantier.

## 1. Compte & accès (le plus demandé pour « mes users »)

| #   | Feature                                            | Ce que ça apporte                                               | Effort |
| --- | -------------------------------------------------- | --------------------------------------------------------------- | ------ |
| 1.1 | Login (mot de passe unique + cookie signé)         | Ouvre Mav hors LAN/VPN sans l'exposer nu                        | S      |
| 1.2 | Comptes multi-utilisateurs + isolation des données | Plusieurs personnes sur une instance, mémoire/routines séparées | L      |
| 1.3 | Foyer / espace partagé                             | Mémoire et routines communes au foyer, à côté des perso         | M      |
| 1.4 | Tokens API personnels                              | Brancher des scripts/apps perso sur son Mav                     | S      |
| 1.5 | Webhooks entrants                                  | « Préviens-moi quand X » depuis un service externe              | S      |

## 2. Proactivité — le cœur de Mav

**Où on en est.** Mav est aujourd'hui _réactif planifié_, pas proactif :

- les routines sont des **rapports à heure fixe** — « dis-moi l'actu à 7 h » ;
- la veille attend qu'on lui **dise quoi** surveiller, et un seul type ;
- **tout est manuel** : rien n'arrive sans qu'on l'ait demandé ;
- **aucune notion d'importance/urgence** : 12 push de même poids ;
- **pas de mémoire du contexte** : Mav ne relie pas routine, veille, chat ;
- **une seule instance** : impossible de faire tourner plusieurs routines en
  parallèle ou de laisser une action se poursuivre en tâche de fond.

**Cible.** Que Mav _remarque_ des choses, décide _si_ elles méritent de te
déranger, et agisse — au lieu de simplement te rapporter ce qu'on lui a
programmé. Trois couches à construire, dans cet ordre.

### Couche A — Déclencheurs riches (ce qui peut réveiller Mav)

| #   | Feature                               | Ce que ça apporte                                                          | Effort |
| --- | ------------------------------------- | -------------------------------------------------------------------------- | ------ |
| 2.1 | Planificateur flexible                | Mensuel, toutes les N semaines, plusieurs heures/jour, jours ouvrés        | S      |
| 2.2 | Détection langage naturel multilingue | « tous les matins… », « chaque lundi », en FR/ES/DE — pas seulement EN     | S      |
| 2.3 | **Événement / webhook**               | Déclenché par un changement externe (GitHub, agenda, formulaire, API)      | S      |
| 2.4 | **Seuil conditionnel**                | « … seulement si X » : pluie, prix, nombre, texte contient                 | M      |
| 2.5 | **Surveillance de l'agenda**          | Anticiper (réunion dans 20 min, anniversaire, échéance) au lieu d'attendre | M      |
| 2.6 | Bibliothèque de modèles de routines   | Créer en 2 clics (brief, revue, rappel, veille)                            | S      |

### Couche B — Décision « est-ce que ça vaut un push ? » (l'intelligence)

| #    | Feature                               | Ce que ça apporte                                                        | Effort |
| ---- | ------------------------------------- | ------------------------------------------------------------------------ | ------ |
| 2.7  | **Classification importance/urgence** | Mav juge lui-même si une alerte est critique, utile ou à ignorer         | M      |
| 2.8  | **Anti-bruit intelligent**            | Regroupe, compare aux alertes passées, retient au lieu de spammer        | M      |
| 2.9  | **Digest quotidien/hebdo**            | Un seul récap au lieu de 12 push                                         | M      |
| 2.10 | **Niveau de proactivité réglable**    | Silencieux · seulement l'important · bavard — préférence par utilisateur | S      |

### Couche C — Mav agit (pas seulement prévenir)

| #    | Feature                           | Ce que ça apporte                                                      | Effort |
| ---- | --------------------------------- | ---------------------------------------------------------------------- | ------ |
| 2.11 | **Actions de fond**               | Lancer une tâche longue et te livrer le résultat plus tard             | M      |
| 2.12 | **Brouillons proposés**           | Rédiger un reply/email/note prêt à valider, déclenché par un événement | M      |
| 2.13 | **Nudges contextuels**            | Suggestions selon l'heure, le lieu, l'agenda (« tu partais à 18 h… »)  | M      |
| 2.14 | **Suivi & relance**               | « Tu m'avais demandé de surveiller ça, toujours rien — je continue ? » | S      |
| 2.15 | Envoi par email (en plus du push) | Recevoir les rapports dans la boîte mail                               | S      |

### Roadmap proposée (phases)

1. **Phase 1 — fondations** : 2.1, 2.2, 2.5, 2.6, 2.10. Mav déclenche sur le
   temps _et_ l'agenda, avec un cran de proactivité réglable.
2. **Phase 2 — le cerveau** : 2.7, 2.8, 2.9, 2.14. Mav trie, retient, digère —
   arrête de tout pousser au même niveau.
3. **Phase 3 — l'agent** : 2.3, 2.4, 2.11, 2.12, 2.13. Mav agit en tâche de
   fond et propose, déclenché par des événements et des conditions.

## 3. Veille (« Keep an eye on »)

| #   | Feature                               | Ce que ça apporte                        | Effort |
| --- | ------------------------------------- | ---------------------------------------- | ------ |
| 3.1 | Flux RSS / Atom                       | Suivre un site, un blog, une chaîne      | S      |
| 3.2 | Météo (seuil / alerte)                | Canicule, gel, pluie sur un lieu         | S      |
| 3.3 | Cotation / marché (retour, en option) | Seuil de prix, variation, volume         | S      |
| 3.4 | Endpoint JSON (API)                   | N'importe quel service avec une API      | M      |
| 3.5 | Sélecteur CSS / XPath                 | Cibler un prix/texte précis sur une page | M      |
| 3.6 | Suivi colis / vols                    | Notif quand le statut change             | M      |
| 3.7 | Réseaux sociaux (X / Mastodon)        | Mentions, posts d'un compte              | M      |

## 4. Connexions (catalogue MCP)

| #   | Feature                                      | Ce que ça apporte                                        | Effort |
| --- | -------------------------------------------- | -------------------------------------------------------- | ------ |
| 4.1 | Agenda (Google / CalDAV)                     | Lire/créer des événements, routines sur l'agenda du jour | M      |
| 4.2 | Email (lecture/envoi)                        | Résumer, trier, répondre depuis le chat                  | M      |
| 4.3 | Gestionnaires de tâches (Todoist, TickTick…) | Ajouter/cocher depuis une conversation                   | S      |
| 4.4 | Obsidian / notes locales                     | Lire et créer des notes                                  | M      |
| 4.5 | Messagerie (Signal / WhatsApp bridge)        | Notifs et réponses hors dashboard                        | L      |

## 5. Mémoire

| #   | Feature                             | Ce que ça apporte                              | Effort |
| --- | ----------------------------------- | ---------------------------------------------- | ------ |
| 5.1 | File de validation des faits appris | Approuver/corriger ce que Mav retient          | S      |
| 5.2 | « Oublie ça » en ligne dans le chat | Supprimer un fait sans quitter la conversation | S      |
| 5.3 | Rappel sémantique (pgvector)        | Retrouver par le sens, pas que les mots-clés   | M      |
| 5.4 | Import / export de la mémoire       | Sauvegarde, migration, portabilité             | S      |
| 5.5 | Mémoire par Helper                  | Le Money ne voit que les faits utiles, etc.    | M      |

## 6. Chat & interaction

| #   | Feature                                         | Ce que ça apporte                                 | Effort |
| --- | ----------------------------------------------- | ------------------------------------------------- | ------ |
| 6.1 | Édition + régénération depuis un message        | Corriger un tour et repartir de là                | M      |
| 6.2 | Chat éphémère (sans mémoire)                    | Poser une question sensible sans laisser de trace | S      |
| 6.3 | Instructions personnalisées par chat            | Ton, format, contexte propre à une conversation   | S      |
| 6.4 | Bibliothèque de prompts                         | Réutiliser ses meilleurs prompts                  | S      |
| 6.5 | Partage d'une conversation (lien lecture seule) | Envoyer une réponse à quelqu'un                   | M      |

## 7. Modèle & fiabilité

| #   | Feature                                | Ce que ça apporte                                 | Effort |
| --- | -------------------------------------- | ------------------------------------------------- | ------ |
| 7.1 | Modèle rapide pour les tâches internes | Titres/extraction sur un petit modèle, moins cher | S      |
| 7.2 | Chaîne de repli fournisseur            | Si le principal tombe, on bascule                 | M      |
| 7.3 | Tableau de bord coûts / tokens         | Voir ce que ça consomme par jour/mois             | M      |
| 7.4 | Mode 100 % local garanti               | Vérifier qu'aucune donnée ne sort                 | S      |

## 8. Plateforme & données

| #   | Feature                           | Ce que ça apporte                 | Effort |
| --- | --------------------------------- | --------------------------------- | ------ |
| 8.1 | Backup / restauration depuis l'UI | Plus besoin de SSH                | S      |
| 8.2 | Import ChatGPT / Claude           | Récupérer son historique existant | M      |
| 8.3 | Export complet (RGPD)             | Tout récupérer, tout supprimer    | S      |
| 8.4 | Journal d'audit                   | Voir ce que Mav a fait, quand     | M      |

## Quick wins recommandés d'abord

Priorité proactivité (demandée) :

1. **2.2 Détection NL multilingue** — le vrai manque aujourd'hui : on ne peut pas
   _dire_ « tous les matins » en français.
2. **2.5 Agenda** — le premier déclencheur non-horaire : anticiper au lieu d'attendre.
3. **2.10 + 2.7 Niveau de proactivité + classement d'importance** — ce qui
   distingue « proactif » de « spammant ».
4. **2.3 Événement/webhook** — ouvre Mav au monde extérieur en une brique.
5. **2.14 Suivi & relance** — Mav qui te relance tout seul, effet « waouh ».

Puis le reste : **1.1 Login**, **3.1 RSS**, **5.1 Validation des faits**, **4.1 Agenda**.
