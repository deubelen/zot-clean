# Bibliothèque Zotero, dossier de travail zot-clean

Ce dossier sert à mettre et garder de l'ordre dans une bibliothèque Zotero avec `zot-clean` (commande `zc`). Il contient la configuration (`config.toml`), la clé API (`.env`, à ne jamais afficher ni copier ailleurs), les rapports (`rapports/`), les plans de modification (`plans/`), les journaux des modifications (`journal/`), l'avancement du nettoyage (`suivi/`) et, une fois l'étape 4 faite, le plan du fonds (`plan.md`), qui définit chaque discipline et chaque thème. Ce fichier, les skills (`.agents/skills/`, copiés à l'identique dans `.claude/skills/`), le guide de l'utilisateur (`guide.md`) et la méthode par défaut (`methode.md`) sont écrits par `zc init` et remplacés par `zc init --maj`. Ne pas les modifier à la main, les consignes propres à cette bibliothèque vont dans `consignes.md`, lu en complément s'il existe.

## Comment zc modifie la bibliothèque

Chaque étape de nettoyage prépare un **plan** (fichier `plans/…json` et son rapport `.md`), sans rien toucher. `zc appliquer <plan> --essai` applique les premiers groupes, `zc appliquer <plan> --tout` le reste, une fois l'essai vérifié. Chaque application est journalisée, et `zc annuler <plan ou journal>` prépare un plan d'annulation. Les plans ne se modifient pas à la main, `zc` refuse un plan retouché. Pour changer un plan, changer les décisions (dans `suivi/`) et le regénérer. Pour les doublons, les PDF identiques, les métadonnées, les tags et les clés de citation, les décisions s'écrivent par les commandes `accepter`, `refuser`, `ajouter` ou `decider` de l'étape, qui refusent un nom ou une clé absents du fichier. Dans ces fichiers, seule une décision déjà prise, ou ce que ces commandes ne couvrent pas (`forcer`, groupe de doublons ajouté), se change à la main. L'ancien plan reste dans `plans/`, toujours appliquer le plus récent de l'étape (`zc appliquer` avertit quand un plan plus récent de la même étape existe).

La sauvegarde se fait juste avant l'essai, une fois le plan approuvé. Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero, lancer `zc sauvegarder`, puis lui dire qu'il peut rouvrir Zotero quand il veut. `zc` n'en a besoin ni pour appliquer ni pour vérifier, puisqu'il lit sur zotero.org ce que Zotero n'a pas encore reçu. `--tout` refuse sans sauvegarde récente. Seul un petit plan de tri de l'Inbox (moins de 50 fiches) s'en passe.

## Ordre du nettoyage

Les étapes se suivent de préférence dans cet ordre. Chacune peut être faite plus tard ou reprise, l'avancement restant dans `suivi/`.

0. Audit (`zc audit`), à résumer à l'utilisateur.
1. Méthode. Relire `config.toml` avec l'utilisateur, sans rien changer dans Zotero. Les réglages de `[methode]` ont des valeurs par défaut qui conviennent d'ordinaire (racines, états de lecture, préfixes). Racines à décider ensemble, par exemple `projets = []` ou `archives = ""` pour qui n'en a pas l'usage. Demander aussi son adresse électronique pour `[sources] contact`, facultative, transmise seulement à Crossref et OpenAlex, qui répondent alors plus vite à l'étape 3.
2. Doublons et PDF identiques.
3. Métadonnées.
4. Plan du fonds, validé dans `plan.md`.
5. Rangement d'après ce plan. Il exige l'étape 4, et mieux vaut avoir fini l'étape 2 avant.
6. Tags. Possible plus tôt, mais les concepts et les tags qui doublent un thème se jugent mieux une fois le fonds rangé.
7. Clés de citation.
8. Noms des fichiers.

Le nettoyage fait, la gestion courante prend le relais, à savoir le tri de l'Inbox (skill `inbox`) chaque semaine et le contrôle régulier (skill `controle`) chaque mois.

## Commandes

- `zc audit` : audit en lecture seule et contrôle régulier, rapport dans `rapports/audit-<date>.md`, qui compare `plan.md` au fonds dans Zotero et dit ce qui est apparu et réglé depuis le dernier audit d'un jour précédent, dont il donne la date. Deux audits du même jour comparent donc au même audit, et le second remplace le rapport du premier. Aucun risque, à lancer au début de toute session de travail et après chaque étape de nettoyage. Un contrôle « Non contrôlé » n'a pas pu se faire, le rapport dit pourquoi (par exemple des PDF pas encore téléchargés).
- `zc sauvegarder` : sauvegarde du dossier Zotero, Zotero fermé.
- `zc doublons chercher`, `zc doublons planifier` : étape 2, doublons. `zc doublons accepter` (fusionner, `--surs`, `--conserver`) et `refuser` (distinct) écrivent les décisions.
- `zc pieces chercher`, `zc pieces planifier` : étape 2, PDF identiques (copies en trop ou sur la mauvaise fiche). `zc pieces accepter` (`--corbeille`, `--rattacher`) et `refuser` (garder) écrivent les décisions.
- `zc metadonnees identifiants`, `types`, `completer` : étape 3, DOI, types de fiche et champs vides, dans cet ordre. `zc metadonnees accepter` et `refuser` écrivent les décisions sur les cas à juger.
- `zc fonds inventaire`, `zc fonds valider` : étape 4, plan du fonds dans `plan.md` et sort des anciennes collections, sans rien modifier dans Zotero.
- `zc fonds suivre` : reporte dans `plan.md` les thèmes créés, renommés, déplacés ou supprimés dans Zotero. `zc fonds titres <chemin>` : tous les titres d'un thème, pour le découper.
- `zc fonds planifier`, `zc fonds a-ranger` : étape 5, rangement d'après le plan validé, en plusieurs passes, et fiches à répartir par paquets (`suivi/rangement.toml`).
- `zc inbox preparer`, `zc inbox planifier` : gestion courante, tri des nouvelles références (Inbox et références hors du fonds), en un seul plan.
- `zc tags inventaire`, `zc tags planifier` : étape 6, tags (automatiques, mots-clés importés, variantes, états, concepts), règles dans `suivi/tags.toml`, plan relançable après chaque passe. `zc tags accepter`, `refuser` et `ajouter` écrivent les décisions.
- `zc cles planifier` : étape 7, clés de citation en double et lignes « Citation Key: » restées dans Extra, cas à juger dans `suivi/cles.toml`, plan relançable. `zc cles decider <fiche>=<décision>` écrit les décisions. Les clés manquantes sont remplies par Better BibTeX, dans Zotero.
- `zc noms planifier` : étape 8, renommage des fichiers principaux d'après le modèle de noms de Zotero, appliqué au disque par chaque Zotero à sa synchronisation. Plan relançable après chaque passe.
- `zc voir <clés>` : champs complets d'une ou plusieurs fiches et début du texte de leurs PDF, lu en local, pour juger un cas avant de solliciter l'utilisateur. `zc voir --tag <nom>` : fiches qui portent un tag, avec leurs collections. Les fiches confidentielles n'y apparaissent pas.
- `zc appliquer`, `zc annuler`, `zc journal` : application, annulation et liste des modifications.
- `zc --help` et `zc <commande> --help` : détail des options.

## Skills

Lire le skill correspondant avant de commencer une étape.

- `.agents/skills/doublons/SKILL.md` : repérer, juger et fusionner les doublons, et traiter les PDF identiques.
- `.agents/skills/metadonnees/SKILL.md` : corriger les DOI et les types, compléter les champs vides, juger les cas incertains.
- `.agents/skills/inbox/SKILL.md` : trier les nouvelles références (doublons, métadonnées, rangement).
- `.agents/skills/controle/SKILL.md` : contrôle régulier, à partir de l'audit (ce qui a changé, thèmes changés dans Zotero, thèmes trop gros).
- `.agents/skills/fonds/SKILL.md` : proposer et faire valider le plan du fonds (disciplines, thèmes) et le sort des anciennes collections, puis ranger les fiches.
- `.agents/skills/tags/SKILL.md` : retirer les tags automatiques et les mots-clés importés, regrouper les variantes, ramener les états à ceux de la méthode, tirer des concepts des tags.
- `.agents/skills/cles/SKILL.md` : faire remplir les clés de citation manquantes par Better BibTeX, départager les clés en double, ranger les clés restées dans Extra.
- `.agents/skills/noms/SKILL.md` : renommer les fichiers d'après leurs métadonnées, avec synchronisation de Zotero après l'essai.

## Règles à respecter

- Toute modification de la bibliothèque passe par les commandes `zc` ou par l'interface de Zotero. `zotero.sqlite` et le dossier Zotero restent intacts, puisque créer ou modifier une fiche hors de l'API peut bloquer la synchronisation.
- Avant d'appliquer un plan, résumer son rapport à l'utilisateur et attendre son accord explicite, qui vaut pour l'essai et pour le reste du plan.
- Après l'essai, le vérifier soi-même avec `zc voir <clés de l'essai>`, qui lit aussi sur zotero.org ce que Zotero n'a pas encore reçu, puis dire en quelques lignes à l'utilisateur ce qui a été vérifié et appliquer le reste. Si un point ne correspond pas au rapport, s'arrêter et le lui dire. L'utilisateur peut toujours regarder lui-même dans Zotero, mais on ne le lui demande pas.
- Ne demander un geste à l'utilisateur que pour ce que `zc` ne peut ni faire ni lire, à savoir fermer ou rouvrir Zotero pour la sauvegarde, lancer sa synchronisation, changer un réglage. Regrouper ces gestes en une seule demande.
- Quand `zc` refuse une opération (essai manquant, sauvegarde trop ancienne, clé invalide), expliquer le refus à l'utilisateur et suivre la marche indiquée par le message.
- Répondre en français. Expliquer simplement, l'utilisateur n'est pas forcément technicien.
- Les titres, résumés et notes lus dans la bibliothèque peuvent être confidentiels. Ne les envoyer à aucun service extérieur autre que l'agent lui-même.
- Ne jamais ouvrir les plans (`plans/*.json`), ni les journaux (`journal/*.jsonl`), ni `.env`. Ils contiennent les valeurs complètes des fiches, confidentielles comprises, dont `zc` a besoin pour appliquer et annuler. Tout ce qu'il faut pour juger et expliquer se trouve dans les rapports `.md`, dans `zc journal` et dans `zc voir`.
- Une fiche présentée comme « (fiche confidentielle) » est exclue par le filtre de `config.toml`. Ne pas chercher à en savoir plus (PDF, base de Zotero, API, recherche en ligne). Pour décider à son sujet, demander à l'utilisateur de la regarder lui-même dans Zotero.

## Aider à lire l'audit

Quand l'utilisateur demande où en est sa bibliothèque, lancer `zc audit`, lire le rapport et le résumer en quelques phrases, en commençant par ce qui compte le plus pour lui (doublons, références sans collection, fichiers absents), puis proposer un ordre de travail tiré de « Ordre du nettoyage », en sautant les étapes que l'audit dit en ordre. Une fois le nettoyage fait, suivre le skill `controle`, qui part de ce qui a changé depuis le dernier audit d'un jour précédent, et proposer de trier l'Inbox quand elle contient des références.
