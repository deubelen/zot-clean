# Décisions

Ce document consigne les options examinées pour construire `zot-clean`, leurs avantages et inconvénients, et les décisions prises. Il fait foi. Les nouvelles décisions continuent la numérotation, une décision révisée garde son numéro et renvoie à celle qui la remplace.

## Origine

`zot-clean` généralise un prototype personnel qui a servi, en septembre 2026, à réorganiser une vraie bibliothèque Zotero (doublons, métadonnées, collections, tags, clés de citation, noms de fichiers), puis à la tenir en ordre (tri de l'Inbox, contrôle mensuel, suggestions de lectures). Le prototype reposait sur un agent (Claude Code) guidé par des consignes et des skills, qui s'appuyait sur une trentaine de scripts Python. Les décisions ci-dessous ont été prises le 28/09/2026 pour en faire un outil utilisable par d'autres.

## Cadre du projet

### D1. Public visé

Options examinées.
- Universitaires peu techniciens, qui n'ont jamais ouvert un terminal. Public le plus large, mais il faudrait un plugin Zotero, donc une réécriture complète en JavaScript.
- Universitaires prêts à suivre un guide pas à pas (installer un outil, coller une clé API, lancer une commande). Réaliste pour le public visé, demande une documentation soignée.
- Utilisateurs à l'aise avec Python et git. Documentation minimale, mais public très restreint.

Décision. Universitaires prêts à suivre un guide pas à pas.

### D2. Degré d'opinion de l'outil

Options examinées.
- Imposer la méthode du prototype telle quelle. Simple à construire, mais rejette ceux qui ont déjà leurs habitudes.
- La proposer par défaut, chaque convention restant modifiable dans la configuration. Un utilisateur débordé reçoit une méthode qui marche, les autres gardent une porte de sortie.
- Ne rien imposer, chacun construisant son cadre en répondant à des questions. Souple, mais chaque utilisateur refait des dizaines de décisions.

Décision. Méthode proposée par défaut, modifiable dans `config.toml` (voir D19 à D25).

### D3. Relation avec le prototype

Options examinées.
- Nouveau dépôt public vierge, le dépôt du prototype restant privé. Historique propre, archives du prototype intactes.
- Nettoyer le dépôt du prototype en réécrivant son historique. Continuité, mais l'historique contient des titres de la bibliothèque et l'état d'avant des fiches, et la réécriture est risquée.

Décision. Nouveau dépôt. Le dépôt du prototype devient un dossier de travail de `zot-clean` (D10) à partir de la v0.3 (D31).

### D4. Langue

Options examinées.
- Tout en français, y compris les noms dans le code. Cohérent avec le public et avec le code du prototype.
- Documentation et messages en français, code en anglais. Plus conventionnel, mais deux langues à tenir.
- Tout en anglais avec une traduction française de la documentation. Public plus large, effort double.

Décision. Tout en français. Une internationalisation pourra venir si des non-francophones s'y intéressent.

### D5. Licence et titulaire des droits

Options examinées.
- MIT. Tout usage permis, y compris fermé.
- GPL-3.0. Les versions modifiées et redistribuées restent libres.
- AGPL. Même obligation étendue aux services en ligne.

Décision. MIT, droits au nom de l'auteur à titre personnel.

### D6. Hébergement

Options examinées.
- GitHub. La plupart des utilisateurs y sont, la distribution des plugins d'agents y passe, intégration continue gratuite pour un dépôt public.
- Codeberg ou GitLab. Plus indépendants, mais découverte et distribution plus difficiles.

Décision. GitHub.

### D7. Engagement de maintenance

Options examinées.
- Outil partagé « tel quel ». Aucun engagement, mais peu rassurant pour des utilisateurs non développeurs.
- Petit projet suivi (issues traitées, versions numérotées, accompagnement des premiers utilisateurs). Demande des tests, une documentation et une compatibilité entre versions.
- Projet communautaire ouvert aux contributions. Demande du temps de relecture et d'animation.

Décision. Petit projet suivi, sans promesse communautaire.

### D8. Nom

Décision. `zot-clean`, commande `zc`, sous-titre « pour Zotero ». Le nom est libre sur GitHub et `zc` n'entre pas en conflit avec une commande courante. PyPI répondait par une erreur passagère pour ce nom le matin du 28/09/2026, puis par 404 (nom libre) le même jour. À revérifier au moment de la première publication, PyPI pouvant refuser un nom trop proche d'un projet existant. Un projet voisin, `zotcleanup` (texra-ai/zotero-cleanup-skills), porte un nom proche. Il se limite aux métadonnées et vise surtout les sciences exactes.

## Architecture

### D9. Forme de l'outil

Options examinées.
- Plugin d'agent seul, scripts inclus. Rien ne fonctionne sans abonnement à un agent.
- Bibliothèque Python avec ligne de commande pour le mécanique, skills pour le jugement. Contrôle, annulation, doublons et sauvegarde marchent sans agent et se testent facilement, le rangement et le nettoyage guidé passent par l'agent.
- Ligne de commande seule, avec des règles ou une API de LLM configurée par l'utilisateur. Autonome, mais le jugement serait pauvre ou coûteux à construire.

Décision. Bibliothèque Python avec ligne de commande `zc`, et skills qui s'en servent. Les garde-fous (simulation par défaut, journal, sauvegarde) vivent dans la ligne de commande et non dans les consignes, ils ne dépendent donc pas de l'agent.

### D10. Dossier de travail et portabilité entre agents

Options examinées pour l'emplacement des données de l'utilisateur.
- Dossier de travail créé par `zc init`, séparé de l'outil installé. Journaux visibles et sauvegardables, versionnables au besoin, intacts lors des mises à jour.
- Dossier caché fixe. Invisible, donc difficile à consulter et à sauvegarder.
- Dépôt de l'outil cloné. Mélange outil et données, ce que D3 cherche justement à éviter.

Options examinées pour les consignes de l'agent.
- `AGENTS.md` et skills écrits dans le dossier de travail par `zc init`. Lus par Claude Code, Codex et d'autres agents.
- Plugins séparés pour chaque agent. Confortables, mais un format par agent.

Décision. Dossier de travail créé par `zc init`, avec `config.toml`, `.env`, `AGENTS.md`, `plan.md` facultatif (D23), les skills, `rapports/` et `journal/`. Un `AGENTS.md` seul suffit, Claude Code le lit, aucun `CLAUDE.md` n'est nécessaire. Réserve vérifiée le 28/09/2026 (D44), un `CLAUDE.md` placé dans le dossier de travail ou au-dessus prend la place de l'`AGENTS.md` pour Claude Code. `zc init` (et `zc init --maj`) le détecte et avertit, en proposant d'ajouter `@AGENTS.md` dans un `CLAUDE.md` du dossier de travail. Les skills sont livrés avec le paquet et mis à jour par `zc init --maj`, si bien que l'outil et ses consignes ne se désynchronisent pas. Des plugins pourront venir plus tard pour le confort.

Le dépôt de l'outil a son propre `AGENTS.md`, destiné au développement. Il ne faut pas le confondre avec celui du dossier de travail.

### D11. Systèmes pris en charge

Options examinées.
- macOS seulement. Simple, mais exclut une bonne part du public visé.
- macOS, Windows et Linux dès le départ. Idéal, mais Windows ne peut pas être essayé à la main.
- macOS d'abord, code portable (`pathlib`, sauvegarde de repli), Windows vérifié par l'intégration continue et par un testeur.

Décision. macOS d'abord, code portable. Les tests tournent sous macOS, Windows et Linux par GitHub Actions (D29).

### D12. Lecture de la bibliothèque

Options examinées.
- Copie temporaire de `zotero.sqlite` (et de son `-wal`), effacée après usage. Quelques dizaines de mégaoctets pour plusieurs milliers de fiches (les fichiers joints ne sont pas copiés). Fonctionne Zotero ouvert ou fermé, donne accès à tout (état de synchronisation, chemins, clés invalides). Le schéma interne peut changer d'une version de Zotero à l'autre.
- API locale de Zotero (lecture seule, `localhost:23119`). Format stable, mais Zotero doit être ouvert et l'option activée, et l'état de synchronisation comme les chemins bruts n'y seraient pas.
- API web. Lente pour une grande bibliothèque, ignore les fichiers locaux.
- API locale par défaut, copie de la base pour le reste. Double le travail et les tests.

Décision. Copie temporaire de la base, lue par un seul module, qui contrôle au démarrage la version du schéma et s'arrête proprement si elle est inconnue. Les requêtes filtrent toujours la bibliothèque personnelle (`libraryID = 1`) sauf lecture explicite d'un groupe déclaré (D18). L'API locale pourra devenir une seconde source derrière la même interface si le schéma change trop souvent.

### D13. Écriture

Options examinées pour le client de l'API web.
- Le client du prototype (90 lignes, lots de 50, `If-Unmodified-Since-Version`, nouvel essai après un 412). Éprouvé, sans dépendance.
- `pyzotero`, bibliothèque de référence. Maintenue par d'autres, sait aussi interroger l'API locale.

Options examinées pour la clé API.
- Fichier `.env` du dossier de travail, exclu du versionnement. Simple et identique sur tous les systèmes.
- Trousseau du système. Plus sûr, mais variable selon les systèmes.

Décision. Écriture uniquement par l'API web, jamais dans `zotero.sqlite`, par `pyzotero`, en lots de 50 au plus avec contrôle de version. Clé dans le `.env` du dossier de travail. `zc init` guide l'utilisateur jusqu'à la page de création de clé, vérifie les droits d'écriture et n'affiche jamais la clé.

### D14. Installation

Options examinées.
- `uv tool install zot-clean` depuis PyPI (ou depuis GitHub avant la première publication). Un seul prérequis, `uv`.
- Cloner le dépôt et lancer `uv sync`. Suppose git.

Décision. `uv tool install`, Python 3.11 au minimum.

### D15. Sauvegarde avant une opération de masse

Options examinées.
- Clone du dossier Zotero si le système le permet (APFS), sinon copie de la base seule, Zotero fermé. Les écritures par l'API ne touchent que les métadonnées, les fichiers ne sont concernés que par le renommage et la compression, qui ont leurs propres garde-fous.
- Copie complète toujours exigée. Plusieurs dizaines de gigaoctets hors APFS.
- Aucune sauvegarde locale, le journal suffisant. Aucun recours si le journal est insuffisant.

Décision. Clone si possible, sinon copie de la base. `zc` refuse une opération de masse sans sauvegarde récente. Seules les deux plus récentes sont conservées.

### D16. Journal et annulation

Options examinées.
- Format de journal unique (une ligne JSON par fiche modifiée, avec l'état d'avant et la version) et commande générique `zc annuler <journal>`, simulée puis appliquée.
- Annulation propre à chaque type d'opération. Plus fine, mais un script à écrire à chaque fois.

Décision. Format unique et `zc annuler`. Les fusions de doublons sont le cas délicat, puisque la fiche absorbée passe à la corbeille et doit en ressortir.

### D17. Sources de métadonnées

Options examinées.
- Celles du prototype, Crossref pour les articles, BnF, Sudoc puis Open Library pour les livres.
- Les mêmes plus OpenAlex, qui couvre articles et livres, complète mieux les sciences humaines que Crossref et fournit les citations utiles aux suggestions.

Décision. Crossref, OpenAlex, BnF, Sudoc et Open Library, activables une par une, avec des caches locaux. L'adresse de contact envoyée à Crossref et OpenAlex est celle de l'utilisateur, saisie dans `config.toml`.

### D18. Confidentialité et bibliothèques de groupe

Quand l'agent trie ou nettoie, les titres, résumés, notes et parfois le texte des PDF partent chez le fournisseur de l'agent.

Options examinées.
- Une mention dans le README et lors de `zc init`.
- En plus, un filtre configurable qui exclut du matériau transmis à l'agent les notes, le texte intégral, ou certaines collections ou certains tags (par exemple `_privé`).

Décision. Mention et filtre. Les commandes `zc` qui préparent le matériau pour l'agent appliquent le filtre, qui ne dépend donc pas de l'agent. Ce qui reste local (audit, contrôle) n'est pas concerné. Révisé par D126, puisque l'agent lit aussi l'audit.

Pour les bibliothèques de groupe, trois options ont été examinées (bibliothèque personnelle seule, groupes déclarés avec un rôle, groupes gérés comme des bibliothèques à part entière). Décision. Seule la bibliothèque personnelle est nettoyée et gérée. Des groupes peuvent être déclarés dans `config.toml` avec un rôle (inventaire papier, consultation pour les doublons et les suggestions), en lecture seule sauf pour l'inventaire papier (D28). Nettoyer un groupe partagé toucherait aux fiches d'autres personnes.

## Méthode par défaut

Chaque élément de cette section se désactive ou se renomme dans `config.toml`. `docs/methode.md` en expose les raisons.

### D19. Collections racines

Options examinées.
- Numérotées pour fixer l'ordre (`00 Inbox`, `10 Projets`, `40 Fonds`, `80 Archives`).
- Sans numéros. Plus sobres, mais triées par ordre alphabétique dans Zotero.

Décision. `Inbox`, `Projets`, `Fonds`, `Archives`, sans numéros. Plusieurs racines de projets sont possibles (D108). `Projets` contient une sous-collection par projet (cours, article, livre), éventuellement regroupées par type. Le prototype avait plusieurs racines de projets selon leur nature, jugées trop propres à un usage.

### D20. Toute référence a sa place dans le fonds

Options examinées.
- Règle par défaut. Chaque fiche est rangée dans le fonds, les projets et les archives n'en sont que des vues (une fiche peut appartenir à plusieurs collections sans être copiée).
- Règle facultative, une fiche pouvant ne vivre que dans un projet.

Décision. Règle par défaut. Une fiche absente du fonds signale un oubli, et un projet s'archive sans rien perdre.

### D21. Profondeur du fonds

Options examinées pour le troisième niveau (sous-thème).
- Créé librement.
- Proposé quand un thème dépasse un seuil. Évite les sous-thèmes de trois fiches, le fonds se creuse là où il grossit.
- Profondeur fixée pour tout le fonds.

Décision. Deux niveaux (discipline, thème), un troisième proposé par l'agent au tri ou au contrôle quand un thème dépasse un seuil réglable (40 fiches par défaut). Le contrôle signale au-delà de trois niveaux. La liste des disciplines et des thèmes est construite par chaque utilisateur pendant le nettoyage.

### D22. Tags

Décision. Tags d'état `1 à lire`, `2 en cours`, `3 lu`, tag `★ essentiel`, concepts préfixés `#`, tags techniques préfixés `_`, tag `papier` pour un exemplaire imprimé. Aucun tag automatique (mots-clés d'éditeurs), ils sont supprimés au nettoyage.

### D23. Plan du fonds et concepts

Options examinées.
- Zotero fait foi. Le plan est la hiérarchie des collections, les concepts sont les tags `#…`. Aucune double saisie, mais aucune définition pour guider l'agent.
- Un fichier fait foi, avec une définition pour chaque thème et chaque concept, et Zotero doit s'y conformer. Idéal pour concevoir le plan, mais chaque geste fait dans Zotero (créer un thème, ajouter un concept au vol) devient une infraction à corriger.
- Zotero fait foi pour l'existence, un fichier facultatif `plan.md` ajoute les définitions et consignes de rangement. Le contrôle signale les thèmes sans définition et les définitions sans thème, l'agent peut proposer une définition manquante lors du tri.

Décision. Troisième option. Pendant le nettoyage (D27, étape 4), `plan.md` sert de proposition validée puis appliquée. Ensuite, il suit Zotero au lieu de le commander.

### D24. Clés de citation

Options examinées.
- Better BibTeX exigé.
- Better BibTeX recommandé. Sans lui, l'étape des clés et les contrôles associés sont sautés.

Décision. Recommandé. `zc init` détecte sa présence et règle la configuration. Par défaut, clés au format `auth.lower + shorttitle(3, 3) + year`, stockées dans le champ natif `citationKey` (Zotero 7 et suivants), où elles restent fixes.

### D25. Noms des fichiers

Décision. PDF nommés `Auteur - Année - Titre` par le renommage automatique de Zotero.

## Contenu et jalons

### D26. Audit

Décision. `zc audit` fait onze contrôles en lecture seule et écrit un rapport Markdown daté dans `rapports/`, avec un résumé en tête et, pour chaque point, ce que le nettoyage pourra y faire.
1. Chiffres d'ensemble (fiches par type, pièces jointes, notes, collections, tags).
2. Fiches sans collection, taille de l'Inbox.
3. Doublons probables (DOI, ISBN, titre et année proches).
4. Métadonnées manquantes (auteur, année, DOI d'un article, ISBN d'un livre, type « Document » par défaut).
5. PDF absents du disque, fiches sans pièce jointe.
6. PDF identiques rattachés à des fiches différentes.
7. Tags automatiques et tags quasi identiques (casse, accents, pluriel).
8. Clés de citation absentes ou en double, présence de Better BibTeX.
9. Noms de fichiers hors du modèle de renommage.
10. Structure des collections (profondeur, collections vides, fiches rangées à plusieurs endroits).
11. Éléments non synchronisés et éléments à clé invalide (ces derniers bloquent la synchronisation).

### D27. Nettoyage

Options examinées.
- Ordre imposé, chaque étape se débloquant quand la précédente est finie.
- Ordre conseillé, chaque étape optionnelle et reprenable, l'avancement étant conservé dans le dossier de travail.

Décision. Ordre conseillé, avec deux dépendances dures, les doublons puis le plan du fonds avant le rangement. Chaque étape suit le même déroulé (simulation et rapport, validation, essai sur quelques fiches, exécution journalisée).
0. Audit et sauvegarde.
1. Décisions de méthode, écrites dans `config.toml`.
2. Doublons, fusionnés à la manière de Zotero.
3. Métadonnées (types, auteurs, années, identifiants, compléments par les sources de D17).
4. Plan du fonds, proposé à partir des collections et tags existants, puis validé dans `plan.md`.
5. Rangement (correspondance entre ancien et nouveau classement, application, anciennes collections archivées puis supprimées).
6. Tags (suppression des tags automatiques, regroupement des variantes, concepts).
7. Clés de citation.
8. Noms des PDF.
9. Contrôle final.

### D28. Outils annexes du prototype

Décision.
- Dans le cœur. Détection des PDF identiques sur des fiches différentes, fusion de doublons et changement de type complété par les sources de métadonnées, scripts JavaScript relus à coller dans Zotero pour ce que seul Zotero sait faire (renommage des fichiers, réparation des clés invalides), avec un mode essai.
- En option, désactivée par défaut. Compression des PDF par Ghostscript, qui perd liens, annotations intégrées et vidéos, avec ses contrôles.
- Plus tard, en module facultatif. Inventaire des livres papier dans un groupe, à partir de photos (codes-barres lus par une bibliothèque portable plutôt que par Vision, propre à macOS) ou d'une simple liste d'ISBN.

### D29. Tests

Options examinées.
- Bibliothèque synthétique. Un compte Zotero de test avec une centaine de fiches volontairement sales, et une copie de sa base versionnée comme donnée de test.
- Une vraie bibliothèque en lecture seule comme seul terrain d'essai.

Décision. Bibliothèque synthétique pour les tests automatiques, sans donnée personnelle, donc publiable. Une vraie bibliothèque en lecture seule sert d'essai de charge. GitHub Actions lance les tests à chaque envoi sous macOS, Windows et Linux. Les tests qui écrivent sur le compte de test restent manuels, pour ne pas exposer sa clé.

### D30. Documentation

Options examinées.
- README seul.
- README court (ce que c'est, installation, premier audit), guide pas à pas dans `docs/` (installation sous macOS et Windows, clé API, premier nettoyage, routine hebdomadaire), et `docs/methode.md` qui explique et justifie la méthode par défaut.

Décision. Deuxième option. `docs/methode.md` est tiré des décisions du prototype, réécrites sans données personnelles. C'est lui qui transmet le raisonnement derrière la méthode. Écrits le 01/10/2026, `docs/guide.md` (installation, clé API, audit, travail avec l'agent, déroulé d'une étape, annulation, confidentialité, refus courants) et `docs/methode.md` (D19 à D25). La routine hebdomadaire y entrera avec la v0.3. Le 03/10/2026, le guide reçoit le contrôle régulier (section 10) et une routine, Inbox chaque semaine et contrôle chaque mois.

### D31. Jalons

Décision.
- v0.1. Squelette, `zc init`, configuration, lecture, audit.
- v0.2. Journal, annulation, sauvegarde, puis nettoyage étape par étape.
- v0.3. Gestion (tri de l'Inbox, contrôle). L'outil sert au quotidien sur une vraie bibliothèque.
- v0.4. Suggestions de textes manquants.
- Plus tard. Production de notes et autres fonctions avancées, inventaire papier.

### D32. Consignation des décisions

Options examinées.
- Un seul fichier, `docs/decisions.md`, décisions numérotées avec options, avantages et inconvénients.
- Un fichier par décision (format ADR).

Décision. Un seul fichier, celui-ci.

## v0.2, écriture, journal, annulation, sauvegarde

Décisions prises le 28/09/2026 pour préparer la v0.2 (D31).

### D33. Couche d'écriture autour de pyzotero

`pyzotero` (1.15.2) envoie bien `If-Unmodified-Since-Version` avec la version de la fiche dans `update_item`, et lève `PreConditionFailedError` sur un 412. Mais `update_items` renvoie seulement `True` et ignore la réponse de l'API, qui indique pour chaque objet d'un lot s'il est `success`, `unchanged` ou `failed` (un 412 dans un lot arrive là, et non comme erreur HTTP). Il attend après un 429 mais ne relance rien après un 5xx ou une coupure réseau. Son constructeur accepte un client `httpx`, ce qui permet de lui brancher un faux serveur.

Options examinées.
- `pyzotero` seul, une requête par fiche. Tout est contrôlé, mais cinquante fois plus de requêtes.
- Un module `ecriture.py`, seul à écrire, qui se sert de `pyzotero` pour l'authentification, les lectures et les requêtes unitaires, et envoie lui-même les lots de 50 par le client `httpx` de `pyzotero` pour lire le résultat de chaque objet. Il ajoute les nouveaux essais après un 5xx ou une coupure.
- Abandonner `pyzotero` pour le client du prototype.

Décision. Deuxième option. D13 reste valable, précisée par celle-ci.

### D34. Plans

Options examinées.
- La simulation affiche un rapport, puis `--appliquer` recalcule tout. Simple, mais ce qui est appliqué peut différer de ce qui a été relu.
- La simulation écrit un plan (fichier JSON dans le dossier de travail, avec l'état attendu de chaque fiche et sa version) et un rapport lisible. Une commande générique `zc appliquer <plan>` exécute ce plan et rien d'autre.

Décision. Plans. Ce qui a été relu est ce qui part. Chaque étape de nettoyage se borne à produire un plan, que le socle commun applique, journalise et reprend, ce qui impose les garde-fous à toutes les étapes futures.

### D35. Essai obligatoire

Options examinées.
- Essai facultatif (`--essai N`).
- Essai obligatoire. L'application complète d'un plan est refusée tant qu'un essai de ce plan n'a pas été appliqué. L'utilisateur vérifie dans Zotero entre les deux.
- Application en deux temps avec confirmation interactive, inutilisable quand un agent lance la commande.

Décision. Essai obligatoire, 5 fiches par défaut, réglable dans `config.toml`. Pour un plan de cette taille ou moins, l'essai vaut application complète.

### D36. Conflit de version pendant l'application

Options examinées.
- Ignorer la fiche et la signaler.
- Relire la fiche. Si les champs que le plan modifie ont encore la valeur attendue, réécrire avec la version relue, une seule fois. Sinon, conflit, fiche laissée intacte et signalée.
- Écraser avec la version relue.

Décision. Deuxième option. Une synchronisation qui fait seulement monter la version ne bloque rien, une correction faite à la main dans Zotero n'est jamais écrasée.

### D37. Forme du journal

Options examinées.
- Un fichier JSON par opération, écrit à la fin (prototype). Une interruption perd la trace des lots déjà écrits.
- Un fichier JSON Lines par opération, `journal/<date>_<étape>.jsonl`. Une ligne d'en-tête (commande, plan, version de `zc`, bibliothèque), une ligne par fiche écrite, ajoutée dès que son lot est confirmé par l'API, une ligne de fin.
- Un journal continu pour toute la bibliothèque.

Décision. JSON Lines, un fichier par opération. L'absence de ligne de fin signale une opération interrompue.

### D38. Contenu du journal

Options examinées.
- Seulement les champs touchés, avec leurs valeurs et versions d'avant et d'après.
- L'objet complet d'avant, relu par l'API juste avant l'écriture, plus les champs modifiés, leur nouvelle valeur et la nouvelle version.

Décision. Objet complet d'avant. Il est relu par l'API et non tiré de la copie de la base, qui peut être en retard sur le serveur. Il sert de filet si une annulation fine ne suffit pas.

### D39. Annulation d'une fiche modifiée depuis l'opération

Options examinées.
- Refuser la fiche dès que sa version a changé.
- Comparer champ par champ. Valeur actuelle égale à celle d'après l'opération, on restaure. Égale à celle d'avant, rien à faire. Autre valeur, conflit, champ laissé tel quel et signalé.
- La même chose avec une option pour forcer.

Décision. Comparaison champ par champ, sans option pour forcer. L'annulation passe par le socle (plan, simulation, essai, journal), elle est donc elle-même annulable.

### D40. Zotero fermé pour la sauvegarde

Options examinées.
- Liste des processus, sans dépendance (`pgrep` sous macOS et Linux, `tasklist` sous Windows).
- `psutil`, portable mais compilé.
- Aucune vérification, copie à chaud contrôlée par `PRAGMA integrity_check`. Le clone du dossier entier pourrait saisir un fichier en cours d'écriture.

Décision. Liste des processus. Si la vérification échoue, `zc` refuse plutôt que de supposer Zotero fermé.

### D41. Emplacement des sauvegardes

Un clone APFS n'est possible que sur le même volume que le dossier Zotero, et un dossier de travail placé dans un dossier synchronisé (iCloud, OneDrive) enverrait un clone de plusieurs dizaines de gigaoctets dans le nuage.

Options examinées.
- `sauvegardes/` dans le dossier de travail.
- À côté du dossier Zotero (`~/Zotero-sauvegardes/`), réglable dans `config.toml`.

Décision. À côté du dossier Zotero. Chaque sauvegarde porte un fichier descriptif (date, méthode, version de la bibliothèque, version de `zc`) que `zc` lit pour connaître les sauvegardes existantes. La synchronisation des fichiers par WebDAV ne change rien ici, puisque les fichiers joints restent dans le dossier Zotero local.

### D42. Sauvegarde récente et opération de masse

Décision. Une sauvegarde est récente si elle a moins de 24 heures (réglable). Elle est exigée pour toute application au-delà de l'essai (D35). Aucune option pour s'en passer, puisque la copie de la base seule, repli de D15, prend quelques secondes sur tout système.

### D43. Première étape de nettoyage

Options examinées.
- Doublons (étape 2). Prioritaire selon D27, la plus riche (fusion, enfants, corbeille), donc celle qui éprouve tout le socle. Annulation la plus délicate.
- PDF identiques sur une même fiche. Simple, mais secondaire pour l'utilisateur.
- Suppression des tags automatiques. Massive et simple, mais la suppression d'un nom de tag est globale et son annulation demande de remettre le tag fiche par fiche.

Décision. Doublons.

### D44. Emplacement des skills

Options examinées.
- `.claude/skills/` seulement (Claude Code).
- `.agents/skills/` seulement, emplacement ouvert lu par Codex, Cursor, Gemini CLI et d'autres.
- Les deux, copies identiques.

Décision. Dans le paquet, `src/zot_clean/modeles/skills/<nom>/SKILL.md`. Dans le dossier de travail, `.agents/skills/<nom>/` et une copie identique dans `.claude/skills/<nom>/`, écrites par `zc init` et remplacées par `zc init --maj`, donc sans risque de divergence. L'`AGENTS.md` livré liste aussi les skills avec leur chemin.

`.agents/skills/` seul avait d'abord été retenu. Vérifié le 28/09/2026 dans la documentation de Claude Code, celui-ci charge les skills depuis `.claude/skills/` uniquement et ne lit rien sous `.agents/`. Sans la copie, un skill ne se déclencherait pas par sa description sous Claude Code. La même documentation confirme que Claude Code lit `AGENTS.md` (depuis la v2.1.277), à condition qu'aucun `CLAUDE.md` ne se trouve dans le dossier de travail ou au-dessus. Sinon, c'est le `CLAUDE.md` qui est lu, et il faut y importer `@AGENTS.md` (voir D10).

### D45. Tests d'écriture

Décision.
- Tests automatiques sur un faux serveur en mémoire (`tests/faux_serveur.py`), branché sur `pyzotero` par `httpx.MockTransport`. Il reproduit le sous-ensemble utile de l'API (versions des fiches et de la bibliothèque, lots avec `success` et `failed`, 412, corbeille, enfants, 429 et 5xx à la demande).
- Tests manuels sur un compte Zotero de test, rempli par l'API depuis un script. Un second profil Zotero, avec son propre dossier de données (`~/Zotero-test`), synchronise ce compte en local, et un dossier de travail de test pointe vers lui. C'est la seule façon d'éprouver la chaîne complète sans toucher la vraie bibliothèque.
- Les tests manuels refusent d'écrire si l'identifiant de la clé n'est pas celui du compte de test déclaré. Aucune écriture sur un compte réel pendant le développement.

### D46. Structure d'un plan

Options examinées.
- Plan à plat, une opération par fiche.
- Plan en groupes. Chaque groupe est une suite ordonnée d'opérations élémentaires (modifier des champs, rattacher à un parent, mettre à la corbeille, sortir de la corbeille), chacune avec la clé, la version attendue, l'avant et l'après des champs touchés.

Décision. Groupes. L'essai (D35) et les lots respectent leurs limites, l'essai porte donc sur 5 groupes. Si une opération échoue, le reste du groupe s'arrête, ce qui évite par exemple de mettre à la corbeille une fiche dont les enfants n'ont pas été rattachés. Une modification simple forme un groupe d'une seule opération. Les plans sont rangés dans `plans/` du dossier de travail.

### D47. Reprise d'un plan interrompu

Options examinées.
- Relancer `zc appliquer <plan>`, qui lit les journaux de ce plan et saute les groupes déjà faits.
- Commande dédiée `zc reprendre <journal>`.

Décision. Relancer `zc appliquer`. Chaque exécution a son propre journal, dont l'en-tête signale une reprise. Un plan est identifié par l'empreinte de son contenu, et c'est aussi par les journaux que `zc` sait si l'essai a été fait. Un plan n'expire pas, puisque chaque fiche est contrôlée par sa version (D36) et que la sauvegarde doit être récente (D42).

### D48. Annulation d'une fusion

L'annulation rejoue le groupe à l'envers. Elle sort les fiches absorbées de la corbeille, remet chaque enfant sous sa fiche d'origine, restaure les champs de la fiche conservée selon D39 (y compris `relations`, donc `dc:replaces`, les collections et les tags) et ressort de la corbeille les pièces jointes identiques qui y avaient été mises. Zotero vide la corbeille automatiquement (après 30 jours par défaut), une fiche absorbée peut donc avoir disparu.

Options examinées.
- Groupe entier déclaré non annulable dès la simulation, rien n'y est touché, le rapport renvoie à la sauvegarde et à l'état d'avant conservé dans le journal.
- Recréer la fiche disparue par l'API. Nouvelle clé, pièces jointes perdues, citations existantes rompues.
- Annuler le reste du groupe et signaler la fiche manquante. Laisse une bibliothèque plus confuse qu'avant.

Décision. Groupe non annulable. Le rapport de fusion rappelle ce délai.

### D49. Repérage des doublons

Options examinées.
- `zc` repère les groupes candidats, les classe en « sûrs » et « à juger » et écrit un fichier de décisions. L'agent examine les groupes à juger avec l'utilisateur et remplit les décisions. `zc` construit le plan à partir des décisions validées.
- Fusion automatique des groupes sûrs.
- Tout à la main dans le fichier de décisions.

Décision. Première option. Est sûr un groupe de même type qui partage le DOI, ou le titre normalisé, les créateurs et l'année. Le même ISBN ne suffit pas, les chapitres d'un livre le partagent. Les groupes sûrs s'acceptent en bloc, mais rien ne fusionne sans passer par le fichier de décisions, qui se lit et s'édite aussi sans agent.

### D50. Mémoire des groupes jugés

Options examinées.
- Un fichier du dossier de travail, avec les clés des fiches et la raison.
- Une relation ou un tag technique dans Zotero. Survit à la perte du dossier de travail, mais encombre la bibliothèque.

Décision. Fichier `suivi/doublons.toml`. L'audit et le contrôle ne signalent plus les groupes jugés distincts. Le dossier `suivi/` accueille aussi l'avancement des étapes (D27).

### D51. Règles de fusion

Décision.
- Fiche conservée, celle qui a le plus de pièces jointes, puis la plus ancienne (prototype), sauf choix contraire dans le fichier de décisions.
- Les champs vides de la fiche conservée sont complétés par les autres. Quand deux valeurs diffèrent, celle de la fiche conservée l'emporte, la différence est montrée dans le rapport, et le fichier de décisions permet d'imposer une valeur.
- Collections et tags réunis, relation `dc:replaces` ajoutée, fiches absorbées à la corbeille, comme la fusion de Zotero.
- Un groupe de types différents est refusé, comme dans Zotero, avec renvoi au changement de type (étape 3).
- Les pièces jointes identiques sont repérées par l'empreinte des fichiers locaux, car le `md5` de l'API est vide quand les fichiers sont synchronisés par WebDAV. Une copie identique va à la corbeille seulement si elle n'a ni annotation, ni note, ni tag. Sinon elle est rattachée comme les autres.

### D52. Noms des commandes

Options examinées.
- Un sous-groupe par étape (`zc doublons chercher`, `zc doublons planifier`) et des commandes communes (`zc appliquer <plan>`, `zc annuler <journal>`, `zc sauvegarder`, `zc journal`).
- Tout sous `zc nettoyer <étape>`.

Décision. Première option. `zc annuler` produit un plan, appliqué ensuite par `zc appliquer` (D39). `zc journal` liste les opérations et leur état (essai, complète, interrompue, annulée).

### D53. Restauration d'une sauvegarde

Remettre une ancienne copie de `zotero.sqlite` alors que le serveur est plus récent expose à des conflits de synchronisation.

Décision. Pas de `zc restaurer` en v0.2. Le guide décrit la marche à suivre en dernier recours. Le recours normal est `zc annuler`.

### D54. Contenu du compte de test

Options examinées.
- Un fichier de fixtures dédié (une centaine de fiches sales, doublons de chaque sorte, pièces jointes identiques avec et sans annotation, types différents), créé par `tests/manuel/peupler.py`, avec de petits PDF générés stockés chez Zotero.
- La même source que la bibliothèque synthétique des tests automatiques, construite en SQL, qu'il faudrait réécrire.

Décision. Fichier dédié pour la v0.2. Les deux sources pourront être rapprochées plus tard.

### D55. Skill des doublons

Décision. Un skill `doublons`, court, avec un déclencheur précis. Il décrit le déroulé (sauvegarde, `zc doublons chercher`, jugement des groupes à juger par paquets de 10 avec l'utilisateur, `zc doublons planifier`, lecture du rapport, essai, vérification dans Zotero, application, audit) et les critères pour distinguer éditions, traductions et vrais doublons. Il renvoie aux commandes au lieu de les répéter et ne double aucun garde-fou du code.

### D56. État de la synchronisation avant d'écrire

Les plans sont construits sur la copie de la base locale. Des éléments non remontés sur le serveur, ou des clés invalides qui bloquent la synchronisation (incident du 24/09/2026 dans le prototype), font diverger la base et le serveur.

Options examinées.
- Aucun contrôle, celui des versions (D36) suffit.
- Refus en présence d'éléments à clé invalide, avec renvoi au script de réparation (D28), simple avertissement s'il reste des éléments non synchronisés.
- Refus dans les deux cas. Gênant juste après une modification dans Zotero, avant la synchronisation suivante.

Décision. Deuxième option, pour la planification comme pour l'application. Le contrôle reprend celui de l'audit (D26, point 11).

### D57. Ordre de travail de la v0.2

Décision. Couche d'écriture et faux serveur, puis plans, `zc appliquer`, journal, essai et reprise, puis `zc sauvegarder`, puis `zc annuler` et `zc journal`, puis les doublons (repérage, plan, fusion et son annulation), puis le skill et son installation, enfin le compte de test et un essai réel. Chaque étape est testée et commitée, la version 0.2.0 est posée à la fin.

Essai réel du 28/09/2026 sur le compte de test, avec un second profil Zotero. Garde-fous (essai, sauvegarde, Zotero ouvert), fusion de doublons, annulation, annulation d'une annulation, conflit sur un champ retouché, changement de type et son annulation se sont comportés comme dans les tests automatiques. L'API accepte de vider dans la même requête les champs que le nouveau type n'admet pas. Un défaut a été trouvé et corrigé, le clone APFS de la sauvegarde échouait et se repliait sans le dire sur la copie de la base. Version 0.2.0 posée.

## v0.2, étape 3, métadonnées

Décisions prises le 28/09/2026. Dans le prototype, la phase 3 avait corrigé des DOI, complété des fiches par Crossref, fait des changements de type sûrs et laissé des cas à juger.

### D58. Découpage de l'étape 3

Options examinées.
- Une commande pour tout.
- Des sous-commandes, `zc metadonnees identifiants`, `completer` et `types`, chacune produisant son plan, et un skill pour les cas à juger.

Décision. Sous-commandes. Livraison dans l'ordre, identifiants (forme et existence des DOI, DOI ou ISBN manquant) et compléments d'abord, puis changements de type, puis le skill des cas à juger (sans auteur, sans date, titre douteux). L'ordre d'exécution devient identifiants, types, compléments (D87).

### D59. Sources de la première livraison

Options examinées.
- Toutes les sources de D17 d'un coup.
- Crossref et OpenAlex d'abord, puis les sources de livres (Open Library, BnF, Sudoc), qui ont chacune leur format.

Décision. Crossref et OpenAlex d'abord.

### D60. Règle de complétion

Options examinées.
- Remplir seulement les champs vides, signaler les valeurs différentes dans le rapport.
- Écraser quand la source fait autorité.

Décision. Champs vides seulement, comme la fusion (D51). Une valeur peut être imposée par le fichier de décisions.

### D61. Champs complétés

Décision. Par défaut, réglable dans `config.toml`, DOI, ISBN, ISSN, date, revue ou ouvrage (`publicationTitle`, `bookTitle`), volume, numéro, pages, éditeur, lieu, langue, et créateurs seulement si la fiche n'en a aucun. Le résumé est exclu par défaut, Crossref le livre souvent en balisage JATS.

### D62. Rattacher une fiche sans identifiant à un résultat de recherche

Décision. Un résultat est sûr si le titre est très proche (similarité d'au moins 0,95, ou titre de la fiche préfixe du titre complet), le premier auteur identique et l'année égale à un an près. Il va alors directement au plan. S'il reste un candidat plausible sans atteindre ces seuils, le cas est écrit dans `suivi/metadonnees.toml` et jugé avec l'agent. Seuils réglables, repris du prototype.

### D63. Contact et débit

Options examinées.
- Adresse de contact obligatoire pour l'étape 3.
- Adresse demandée par `zc init`, facultative, avec un avertissement si elle manque, et un débit limité dans tous les cas.

Décision. Deuxième option, débit d'environ 3 requêtes par seconde.

### D64. Caches

Options examinées.
- Un cache par source dans le dossier de travail (`cache/`, exclu du versionnement), sans expiration, vidé par `--rafraichir`.
- Un cache dans un dossier système, avec expiration.

Décision. Dans le dossier de travail. Relancer une simulation ne réinterroge rien.

### D65. Confidentialité des recherches par titre

Options examinées.
- Appliquer le filtre de D18. Une fiche filtrée n'est jamais cherchée par titre, mais son DOI peut être vérifié.
- Aucun filtre pour les services de métadonnées.

Décision. Filtre de D18, créé à cette occasion dans `config.toml`.

### D66. Forme du filtre de confidentialité

Décision. Section `[confidentialite]` de `config.toml`, avec `tags_exclus = ["_privé"]`, `collections_exclues = []` (une collection exclut ses sous-collections), `exclure_notes` et `exclure_texte_integral`. Les deux derniers servent au matériau transmis à l'agent, l'étape 3 n'utilise que les deux premiers. Le filtre vit dans un module unique, réutilisé par les étapes futures.

### D67. Ordre des sources

Décision. Pour vérifier un DOI et compléter depuis lui, Crossref, puis OpenAlex si Crossref ne le connaît pas (DOI d'autres agences comme DataCite). Pour chercher un DOI manquant, Crossref, puis OpenAlex s'il n'y a aucun candidat sûr. Une première passe sur plusieurs milliers de fiches prend environ une demi-heure, les suivantes presque rien grâce au cache. La commande affiche sa progression.

### D68. DOI qui n'existe pas

Options examinées.
- Le retirer automatiquement.
- Cas à juger, avec la proposition de le retirer ou de le remplacer par un candidat trouvé par titre.

Décision. Cas à juger. Un DOI inconnu vient souvent d'une faute de frappe, que le candidat trouvé par titre révèle.

### D69. DOI qui pointe vers une autre publication

Décision. Quand le titre de la source ne ressemble pas à celui de la fiche (similarité inférieure à 0,8, sans relation de préfixe), le cas est à juger et rien n'est complété depuis ce DOI tant qu'il n'est pas confirmé.

### D70. Chapitres et DOI

Options examinées.
- Chercher aussi le DOI des chapitres, en exigeant un résultat de type chapitre.
- Ne jamais chercher de DOI pour un chapitre.

Décision. Première option. Un DOI de livre n'est jamais proposé pour un chapitre.

### D71. Fichier de suivi des métadonnées

Décision. `suivi/metadonnees.toml`, sur le modèle des doublons. Une entrée par cas à juger (clé, sous-étape, problème, propositions avec leur source, `decision` parmi `accepter`, `refuser` ou vide, `forcer`). Les cas sûrs vont directement au plan. Un cas refusé n'est plus reproposé.

### D72. Forme de la date complétée

Options examinées.
- La date telle que la source la donne.
- L'année seule (prototype).

Décision. Telle que la source la donne. Clé de citation et nom de fichier n'en retiennent que l'année.

### D73. Créateurs complétés

Décision. Pour une fiche sans créateur, les auteurs de la source, plus les directeurs d'ouvrage pour un livre ou un chapitre, en nom et prénom, ou en champ unique pour une institution. Le cas reste sûr quand le rattachement l'est.

### D74. Clé OpenAlex

Depuis 2026, OpenAlex fait payer à l'usage. La lecture d'une œuvre par son DOI est gratuite et illimitée, une recherche coûte 1 dollar les 1 000. Une clé gratuite donne 1 dollar par jour (environ 1 000 recherches), l'accès anonyme 0,10 dollar par jour, avec des recherches freinées quand le service est chargé. L'essai de charge du 28/09/2026 a été refusé dès les premières recherches anonymes.

Options examinées.
- Clé facultative dans `.env` (`OPENALEX_API_KEY`), proposée par `zc init`. Lecture par DOI toujours, recherches seulement avec une clé, arrêtées d'elles-mêmes vers 900 par jour et reprises le lendemain grâce au cache.
- Clé obligatoire pour activer OpenAlex.
- Lecture par DOI seulement.

Décision. Clé facultative.

### D75. Titres génériques et chapitres

L'essai de charge a rattaché avec certitude quatre chapitres intitulés « Introduction » sur la foi du titre, de l'auteur et de l'année.

Décision. Jamais de certitude pour un titre de moins de quatre mots significatifs ou pour un titre générique (introduction, conclusion, préface, avant-propos, editorial, compte rendu…). Pour un chapitre, la certitude exige aussi que le titre de l'ouvrage corresponde à celui de la source quand les deux sont connus. Ces cas vont au jugement. Complète D62.

### D76. Éditeur et lieu des articles

Pour un article de revue, Crossref donne l'éditeur commercial, que les styles de citation n'utilisent pas. Dans l'essai de charge, plus de neuf fiches à compléter sur dix ne recevaient que lui.

Décision. Par défaut, `publisher` et `place` ne sont pas complétés pour les articles de revue. Réglable par type (`exclus_par_type` dans `[metadonnees]`). Complète D61.

### D77. Langue

Les styles de citation se servent de la langue, par exemple pour la casse des titres anglais.

Options examinées.
- Compléter la langue seulement si elle correspond à la langue détectée du titre (anglais ou français, par les mots courants).
- Recopier la langue de la source.
- Ne pas la compléter.

Décision. Première option. Une autre langue, ou un titre sans langue reconnaissable, n'est pas complété.

### D78. Skill de l'étape 3

Options examinées.
- Un skill `metadonnees` pour toute l'étape 3 (identifiants, jugement, plans, essai, application, compléments), sur le modèle de celui des doublons.
- Un skill limité au jugement des cas.

Décision. Un skill pour toute l'étape.

### D79. Ce que l'agent voit pour juger

Options examinées.
- Enrichir `suivi/metadonnees.toml`. La fiche y gagne sa revue ou son ouvrage, chaque proposition la revue ou l'ouvrage de la source, le volume, les pages et l'éditeur, tirés de la copie de la base et du cache.
- Une commande de comparaison détaillée.
- Laisser l'agent chercher sur le web, ce qui enverrait des titres à d'autres services (D18, D65).

Décision. Enrichir le fichier, sans nouvel appel réseau.

### D80. Ordre et présentation des cas

Décision. Par paquets de 10. D'abord les DOI malformés ou inconnus qui ont un candidat, puis les DOI discordants, puis les DOI manquants. Chaque cas reçoit une recommandation et une phrase de justification.

### D81. Décisions en bloc et cas en attente

Décision. L'utilisateur peut approuver les recommandations d'un paquet d'un seul accord explicite. Un cas peut rester sans décision sans rien bloquer. Sur demande explicite, l'agent peut refuser en une fois les cas restants d'un type.

### D82. Critères de jugement des métadonnées

Décision. Accepter un candidat qui désigne la même publication (titre à un sous-titre, une ponctuation ou une casse près, même premier auteur, même revue ou ouvrage s'ils sont connus, année à un an près). Refuser un compte rendu, un erratum, un autre chapitre, une autre édition, une traduction ou un type différent. Pour un DOI discordant de livre porté par un chapitre, retirer le DOI ou choisir le candidat du chapitre. Pour un DOI inconnu, préférer un candidat à un ou deux caractères près, sinon retirer. En cas de doute, laisser sans décision.

### D83. Écriture des décisions

Options examinées.
- L'agent modifie directement le fichier de suivi, que les commandes valident.
- Une commande qui écrit les décisions.

Décision. Modification directe, comme pour les doublons. Une commande pourra venir si des erreurs apparaissent en pratique.

### D84. Fiches à changer de type

Options examinées.
- Les fiches dont le DOI est confirmé et dont le type chez la source diffère, sûres quand l'auteur et l'année concordent et que la transition est sans risque, à juger sinon.
- En plus, deviner le type des fiches sans identifiant.

Décision. Première option, commande `zc metadonnees types`.

### D85. Champs que le nouveau type n'admet pas

Options examinées.
- Jamais sûr s'il y a une perte, jugement avec les champs perdus affichés.
- Recopier les valeurs perdues dans `extra`.
- Supprimer comme Zotero, le journal gardant l'état d'avant.

Décision. Recopie dans `extra` (« ISSN : 0096-3445 »). Les champs qui ont un équivalent dans le nouveau type (champs de base de Zotero, comme titre de revue et titre d'ouvrage) sont transférés. Les rôles de créateur que le nouveau type n'admet pas deviennent « contributeur », comme dans le prototype.

### D86. Transitions sûres

Décision. Sûres, si l'auteur et l'année concordent : article et chapitre dans les deux sens, article vers communication, chapitre et communication dans les deux sens, « Document » vers tout type reconnu. Toujours à juger : tout passage vers ou depuis un livre, et les types prépublication, rapport, thèse et article d'encyclopédie.

### D87. Ordre des sous-étapes de l'étape 3

Options examinées.
- Identifiants, types, compléments. Compléter après le changement de type remplit directement les bons champs.
- Identifiants, compléments, types (D58).

Décision. Identifiants, types, compléments. `completer` saute les fiches dont le type diffère encore de celui de la source. Révise l'ordre de D58.

### D88. Fiches sans identifiant et livres sans ISBN

Décision. Laissés à la livraison des sources de livres (Open Library, BnF, Sudoc), Crossref couvrant mal les livres de sciences humaines.

### D89. Suivi des changements de type

Décision. Les cas à juger vont dans `suivi/metadonnees.toml` avec la sous-étape `types`. Chaque proposition montre le nouveau type, les champs transférés et les valeurs recopiées dans `extra`. Le skill `metadonnees` reçoit une étape et des critères de plus.

### D90. Périmètre des sources de livres

Décision. Quatre cas. Livres avec ISBN, dont on vérifie la somme de contrôle et complète les champs vides. Livres sans ISBN, cherchés par titre, auteur et année. Fiches « Document » sans identifiant, pour lesquelles un livre correspondant est proposé, toujours à juger. Chapitres qui portent l'ISBN de leur ouvrage, dont on complète les champs d'ouvrage vides depuis la notice du livre.

### D91. Ordre des sources de livres

Décision. Par ISBN, BnF, Sudoc puis Open Library pour un ISBN francophone (978-2, 979-10), Open Library, Sudoc puis BnF pour les autres. Par titre, BnF puis Open Library, le Sudoc n'ayant pas de recherche par titre. Réglable dans `config.toml`.

### D92. Choix de l'édition

Options examinées.
- Certitude seulement si un seul candidat réunit titre (similarité d'au moins 0,95), premier auteur, même année exactement et même éditeur quand la fiche en a un. Sinon jugement, cinq éditions au plus.
- L'édition la plus proche de l'année de la fiche.

Décision. Première option. La mauvaise édition fausse les pages citées.

### D93. Champs complétés pour les livres et les chapitres

Décision. La liste de D61, plus pour les livres le nombre de pages, l'édition, la collection et son numéro. Créateurs seulement si la fiche n'en a aucun (D73), avec les rôles de la notice. Les vedettes-matières ne deviennent jamais des tags (D22).

### D94. Place dans les commandes et ISBN invalides

Décision. Pas de nouvelle commande. `identifiants` vérifie les ISBN et cherche l'ISBN manquant, `types` traite les fiches « Document », `completer` complète livres et chapitres. Un ISBN à somme de contrôle fausse est un cas à juger (`isbn_invalide`), avec la proposition de le retirer et un candidat trouvé par titre. Un ISBN valide n'est jamais reformaté.

## v0.2, étape 4, plan du fonds

Décisions prises le 29/09/2026. L'étape 4 (D27) propose une hiérarchie de disciplines et de thèmes à partir du classement existant et la fait valider dans `plan.md` (D23). C'est une étape de jugement, qui repose surtout sur l'agent et sur un skill.

### D95. Périmètre de l'étape 4

Options examinées.
- L'étape 4 n'écrit rien dans Zotero et s'arrête sur un `plan.md` validé. L'étape 5 fait toutes les écritures en un seul plan (création des collections du fonds, rangement, archivage puis suppression des anciennes collections). Étape de pur jugement, sans sauvegarde ni essai, un seul journal et une seule annulation pour le rangement, pas de collections vides si le rangement tarde.
- L'étape 4 crée déjà les collections vides du fonds. Le plan se voit plus tôt dans Zotero, mais chaque retouche du plan oblige à renommer ou supprimer des collections.

Décision. Première option, l'étape 4 est en lecture seule. L'étape 5 se fait en plusieurs passes (D119).

### D96. Commandes de l'étape 4

Décision. Un sous-groupe `zc fonds` (D52). `zc fonds inventaire` écrit l'inventaire (D97) et prépare `suivi/fonds.toml` (D100). `zc fonds valider` contrôle `plan.md` et `suivi/fonds.toml` et enregistre la validation (D102). `zc fonds planifier` construira le plan de rangement de l'étape 5, appliqué par `zc appliquer`. Si la racine du fonds est désactivée dans `config.toml` (D19), `zc fonds` refuse de s'exécuter et le dit.

### D97. Inventaire donné à l'agent

Options examinées.
- Rapport Markdown daté dans `rapports/`, lisible par l'utilisateur comme par l'agent.
- Fichier JSON dans `suivi/`. Commode pour un programme, peu lisible. L'inventaire est un instantané qui sert à juger, `zc` n'a pas à le relire.

Décision. Rapport Markdown dans `rapports/`. Il contient l'arbre des collections (effectif, profondeur, fiches communes avec d'autres collections, dix titres au plus en échantillon), les tags manuels avec leur effectif (sans tags automatiques, tags d'état, `★ essentiel`, `papier` ni tags techniques `_`), les tags qui reviennent ensemble et les tags dominants de chaque collection, et le nombre de fiches sans collection. Ni résumé ni texte intégral. Le filtre de D18 s'applique aux collections, aux tags et aux titres.

### D98. Base de la proposition

Options examinées.
- Les collections et les tags existants seulement (D27 à la lettre).
- En plus, le contenu des fiches sans collection, pour prévoir des thèmes que rien n'annonce encore.
- Si une racine `Fonds` existe déjà, partir de son arbre comme d'un brouillon.

Décision. Première et troisième options. Les fiches qui ne trouveront aucun thème seront signalées à l'étape 5, et `plan.md` sera retouché, ce que D23 prévoit de toute façon.

### D99. Sort des anciennes collections

Décision. Chaque collection existante reçoit un sort, à savoir thème ou sous-thème du fonds (avec ou sans nouveau nom), répartition fiche par fiche à l'étape 5 (avec les thèmes candidats), projet sous `Projets`, archives, dissolution, ou « hors plan » (laissée telle quelle). Les collections déjà placées sous `Projets` ou `Archives` ont un sort prérempli, que l'agent ne revoit qu'à la demande de l'utilisateur. Celles de `Fonds` sont proposées comme thèmes à garder, renommer ou fusionner (D98). Les collections exclues par le filtre (D18) n'apparaissent pas dans l'inventaire et reçoivent le sort « hors plan », que l'utilisateur peut changer à la main sans passer par l'agent. Seule la collection désignée dans `config.toml` figure dans `fonds.toml`, ses sous-collections la suivent sans y être nommées. Les tags thématiques existants peuvent désigner un thème, comme indice de rangement pour l'étape 5. Leur sort comme tags se règle à l'étape 6.

### D100. Correspondance entre ancien et nouveau classement

Options examinées.
- Dans `plan.md`, sous chaque thème. Tout est au même endroit, mais `plan.md` survit au nettoyage (D23) et garderait les traces d'un classement disparu.
- Dans un fichier de suivi, `suivi/fonds.toml`, sur le modèle de `doublons.toml` et `metadonnees.toml`.

Décision. `suivi/fonds.toml`. `plan.md` décrit le fonds, `fonds.toml` la transition, et l'agent les présente ensemble. `zc fonds inventaire` y inscrit une entrée par collection (clé, chemin, effectif) avec un sort vide ou prérempli (D99) et une section qui relie des tags à des thèmes. Relancé, il garde les sorts remplis, ajoute les nouvelles collections et signale celles qui ont disparu. L'agent modifie le fichier directement (D83). Le fichier reste ouvert à ce que l'étape 5 devra y ajouter.

### D101. Forme de `plan.md`

Options examinées pour les noms.
- Noms uniques dans tout le fonds, références par le nom seul. Aucune ambiguïté, mais « Méthodes en sociologie » là où « Méthodes » suffirait.
- Noms uniques sous un même parent, comme dans Zotero, références par le chemin (`Sociologie/Méthodes`).

Décision. Structure stricte, lisible à la main et analysable par `zc`. `##` pour une discipline, `###` pour un thème, `####` pour un sous-thème, le titre donnant le nom exact de la collection. Sous chaque titre, un paragraphe de définition et des lignes facultatives « Inclut » et « Exclut », qui tranchent les frontières entre thèmes voisins. Le reste est du texte libre que `zc` ignore. Noms uniques sous un même parent, références par le chemin partout (`plan.md`, `fonds.toml`, échanges avec l'agent). Précision à la construction, la hiérarchie se lit sous un titre de premier niveau portant le nom de la racine (`# Fonds`), ce qui laisse à `plan.md` d'autres sections (`# Concepts`, D103) sans les confondre avec des disciplines. Un nom réservé à une racine n'est refusé qu'au niveau des disciplines, où il prêterait à confusion avec la racine.

### D102. Validation du plan

Options examinées pour l'effet d'une retouche après validation.
- Toute modification de `plan.md` ou de `fonds.toml` annule la validation.
- Seule une modification de structure l'annule. Retoucher une définition ne bloque pas le rangement.

Décision. `zc fonds valider` signale les noms en double sous un même parent, la profondeur au-delà de trois niveaux, un nom réservé à une racine, un chemin qui ne mène à rien, une ancienne collection sans sort, et avertit pour un thème sans définition. Sans erreur et après accord explicite de l'utilisateur, il enregistre dans `suivi/` l'empreinte de la structure (chemins, sorts et cibles), et montre à la validation suivante ce qui a changé. L'étape 5 refuse de planifier si la structure a changé depuis. Une fois le rangement fait, `plan.md` suit Zotero (D23) et l'empreinte ne sert plus.

### D103. Concepts

Options examinées.
- L'étape 4 ne traite que la hiérarchie, la section des concepts de `plan.md` est remplie à l'étape 6.
- L'étape 4 propose aussi les concepts, l'inventaire des tags étant déjà là.

Décision. Première option. Les concepts se jugent mieux après la suppression des tags automatiques et le regroupement des variantes.

### D104. Déroulé avec l'utilisateur

Options examinées.
- L'arbre entier d'abord (noms et effectifs prévus), retouché par l'utilisateur, puis définitions et sorts discipline par discipline.
- Discipline par discipline dès le départ.
- Tout d'un bloc, définitions comprises.

Décision. Première option. La structure se juge d'un coup d'œil, les définitions demandent de l'attention.

### D105. Critères d'un bon plan

Décision. Consignes souples dans le skill. Entre 3 et 12 disciplines environ, un thème de moins de 5 fiches prévues fusionné avec un voisin, un sous-thème seulement au-delà du seuil de D21, des noms courts en français sauf usage établi, au singulier et sans numéros, aucun thème qui double un projet, les disciplines de l'utilisateur plutôt qu'une classification de bibliothèque plaquée. Seul le seuil de D21 est dans `config.toml`, et seuls la profondeur et les chemins sont contrôlés par le code (D102).

### D106. Skill de l'étape 4

Options examinées.
- Un skill `fonds` pour les étapes 4 et 5, livré pour l'étape 4 et complété ensuite.
- Un skill par étape.

Décision. Un skill `fonds`, comme `metadonnees` pour toute l'étape 3.

### D107. Essais et suite

Options examinées pour l'étape 5.
- Même grilling que l'étape 4.
- Grilling séparé, nourri par un essai réel de l'étape 4.

Décision. Tests automatiques sur la bibliothèque synthétique enrichie (arbre sur plusieurs niveaux, collection de projet, collection à répartir, tags thématiques, collection exclue par le filtre). Le compte de test, avec ses six collections, ne suffit pas à juger une proposition. L'essai de jugement se fait donc sur la vraie bibliothèque, l'étape 4 étant en lecture seule et seuls les titres filtrés partant chez l'agent. L'étape 5 aura son propre grilling, nourri par cet essai.

### D108. Plusieurs racines de projets

Décision prise pendant l'essai de l'étape 4 sur une vraie bibliothèque, dont les projets se répartissaient en plusieurs racines. Révise D19. `projets` dans `config.toml` accepte une liste de racines, `["Projets"]` par défaut. La catégorie générique reste le projet, et chacun décide s'il la divise (cours, articles, livres). Une collection placée sous l'une de ces racines reçoit le sort « projet » prérempli. Sa `cible` dans `fonds.toml` s'écrit avec le nom de la racine (`Articles/Revue de littérature`), et `zc fonds valider` vérifie qu'elle commence par une racine déclarée. Une cible vide n'est admise qu'avec une seule racine de projets. Les archives gardent une seule racine.

### D109. Sous-thèmes proposés sur la liste complète des titres

Options examinées.
- Dix titres par collection, comme pour le reste de l'inventaire. L'essai a montré que c'est trop peu pour découper un thème de plusieurs centaines de références.
- Tous les titres des collections qui dépassent `seuil_sous_theme` (D21), sans résumés, le filtre de D18 s'appliquant toujours.

Décision. Deuxième option, pour les collections du fonds. Le seuil reste réglable, 40 par défaut. Un découpage n'est proposé que s'il est net, jamais pour le seul franchissement du seuil.

### D110. Singulier ou pluriel

Décision. Précise D105. Un nom de thème est au singulier quand il sonne naturellement (« Mémoire », « Perception »), au pluriel sinon (« Méthodes qualitatives », « Relations internationales »). L'agent propose les renommages avec le reste de la discipline, jamais pour le seul nombre sans l'accord de l'utilisateur.

### D111. `zc init --maj` réservé aux dossiers de travail

Décision prise après l'essai de l'étape 4, où `zc init --maj` lancé par erreur dans le dépôt du code a remplacé son `AGENTS.md` de développement. `--maj` remplace `AGENTS.md` et les skills sans demander, il refuse donc de s'exécuter dans un dossier sans `config.toml` et n'y écrit rien.

### Essai de l'étape 4 et questions pour l'étape 5

Essai fait sur une vraie bibliothèque, en lecture seule, jusqu'à un plan validé. Il a donné D108 à D110 et laisse ces questions au grilling de l'étape 5.
- Une bibliothèque déjà rangée à la manière du prototype a des racines numérotées (première option de D19). L'essai les a déclarées dans `config.toml`. Reste à décider si le rangement renomme les racines vers la méthode (D19) et comment il reconnaît un classement déjà conforme.
- L'utilisateur donne pendant l'étape 4 des consignes fiche par fiche (mettre trois manuels à la corbeille, envoyer les références d'un auteur dans un autre thème). `fonds.toml` n'a pour elles que le champ `note`. Il leur faut une place lisible par `zc fonds planifier`.
- Une dizaine de collections, soit plus d'un millier de références, sont à répartir fiche par fiche entre un thème et ses nouveaux sous-thèmes. Le jugement de l'agent doit tenir à cette échelle (paquets, fiches qui gardent le thème parent, fiches rangées à plusieurs endroits).
- Un nom de collection peut contenir « / » (par exemple `Histoire/moderne`), ce qui rend son chemin ambigu, et deux collections sœurs peuvent porter le même nom (deux `Méthodes` sous une même collection d'archives). Les chemins de `fonds.toml` ne suffisent pas toujours à désigner une collection, la clé si.

## v0.2, étape 5, rangement

Décisions prises le 29/09/2026, nourries par l'essai de l'étape 4 sur la vraie bibliothèque. L'étape 5 range les fiches d'après le plan validé (`plan.md`, `suivi/fonds.toml`) et fait les premières écritures massives sur les collections.

### D112. Racines

Options examinées.
- Le rangement ne renomme jamais une racine, `config.toml` déclare les noms en usage.
- Le rangement ramène les racines aux noms de la méthode.

Décision. Deuxième option. `zc fonds inventaire` préremplit une table `[racines]` dans `fonds.toml`, qui donne le nouveau nom de chaque racine en retirant le numéro de tête (`40 Fonds` devient `Fonds`). L'utilisateur la corrige à son gré, et plusieurs racines de projets restent distinctes (D108). Les renommages sont les derniers groupes du plan. Une fois le plan appliqué, l'agent met à jour `config.toml` et le titre de la section du fonds dans `plan.md`, `zc` le rappelle et vérifie la concordance au lancement suivant. `zc` n'écrit pas lui-même dans `config.toml`, qui porte les commentaires de l'utilisateur. Précise D19.

Constat sur une vraie bibliothèque. Après le renommage, les cibles des projets de `fonds.toml`, qui commencent par le nom de leur racine, n'étaient plus valides (une erreur par projet). `zc fonds valider` et `zc fonds inventaire` y reportent désormais les nouveaux noms, d'après la table `[racines]`, une fois `config.toml` à jour. La validation est ensuite à enregistrer de nouveau.

### D113. Transformation sur place

Options examinées.
- Sur place. Une ancienne collection de sort « thème » est renommée ou déplacée vers sa cible et garde sa clé et ses fiches, seules les collections manquantes sont créées, l'archivage se fait par déplacement.
- Reconstruire un fonds neuf, y ranger les fiches, puis archiver et supprimer l'ancien classement. Des milliers d'écritures, et les clés des collections, que d'autres outils peuvent citer, sont perdues.

Décision. Sur place. Révise la fin de D27, « archivées puis supprimées » valant pour un classement abandonné, pas pour un classement qui devient le fonds.

### D114. Collections dans les plans

Options examinées.
- `Operation` étendue aux collections (`nature = "collection"`, champs `name`, `parentCollection`, `deleted`), avec des clés de collections nouvelles tirées à la planification et fournies à l'API à la création, pour que les opérations sur les fiches y renvoient déjà. Journal, reprise et annulation restent génériques.
- Un plan de structure appliqué d'abord, puis un plan de rangement calculé avec les vraies clés.

Décision. Première option, si le test sur le compte de test confirme que l'API accepte une clé fournie à la création. Sinon, repli sur la seconde. Confirmé le 29/09/2026 par `tests/manuel/sonde_collections.py`. L'API accepte des clés fournies, un parent et son enfant dans la même requête, le renommage et le déplacement avec contrôle de version (412 sur une version périmée), la corbeille des collections (`deleted`) et la sortie de corbeille.

### D115. Répartir

Options examinées.
- Une fiche reste dans son thème actuel par défaut, l'agent ne propose que les déplacements nets, par paquets d'une cinquantaine, sur titre, auteur, année, type, tags et autres collections.
- Chaque fiche doit recevoir une place avant le rangement.
- Juger aussi sur le résumé.

Décision. Première option. Le résumé se demande pour une fiche douteuse seulement (D121). Une fiche déplacée vers un sous-thème quitte le thème parent et se range au niveau le plus précis, Zotero pouvant montrer dans une collection les fiches de ses sous-collections. L'action `ajouter` garde une double place voulue.

### D116. Fichier `suivi/rangement.toml`

Décision. Un seul fichier pour tout ce qui concerne des fiches précises, séparé de la structure, qui reste validable sans lui. Il recueille les consignes de l'utilisateur (« ces références vont dans tel thème », « ces fiches à la corbeille »), les répartitions (D115) et les fiches sans place dans le fonds (D20), sauf celles de l'Inbox, qui relèvent du tri. Une entrée par fiche, avec la clé, l'action (`déplacer`, `ajouter`, `corbeille`), la cible (chemin du plan), la source (`agent`, `tag`, `consigne`) et la décision (`""` pour proposé, `"accepter"`, `"refuser"`). Un commentaire au-dessus donne auteur, année, titre et collections actuelles. L'agent y écrit ses propositions par paquets, l'utilisateur approuve le paquet, `zc fonds planifier` ne prend que les entrées acceptées. Les tags reliés à un thème (D100) produisent d'eux-mêmes des propositions, à valider comme les autres. La `note` de `fonds.toml` n'est plus qu'un commentaire.

Constat sur une vraie bibliothèque. Deux entrées peuvent s'enchaîner sur une même fiche, l'une la menant de A vers B, l'autre de B vers C (une fiche jugée depuis deux collections). Comme le plan part de l'état réel, la première ajoutait B, que la fiche n'avait pas ou plus. `zc fonds planifier` suit désormais la chaîne et mène la fiche directement en C.

### D117. Collections vidées ou dissoutes

Options examinées.
- Mises à la corbeille de Zotero, d'où l'annulation peut les tirer.
- Envoyées aux archives.

Décision. Corbeille. Une collection fusionnée dans une autre (même cible) y passe une fois ses fiches déplacées, une collection « dissoudre » aussi. Ses fiches gardent leurs autres collections, et celles qui n'ont plus de place dans le fonds entrent dans `rangement.toml`.

### D118. Désignation des collections

Décision. Les anciennes collections sont toujours désignées par leur clé dans les fichiers de suivi et les plans, le chemin n'étant qu'un commentaire lisible. L'essai a trouvé un nom contenant « / » et deux collections sœurs de même nom. Les cibles sont des chemins du plan, qui interdit déjà ces deux cas (D101). L'avertissement « leurs fiches seront réunies » de `zc fonds valider` ne vaut que pour deux collections de même cible explicite, puisqu'une collection archivée sous sa cible par défaut garde son nom et reste distincte de ses sœurs.

### D119. Passes successives

Options examinées.
- `zc fonds planifier` se relance, chaque passe planifiant ce qui est décidé et pas encore fait.
- Un seul plan, une fois tout jugé (D95).

Décision. Première option, qui révise D95. `planifier` compare l'état réel de la bibliothèque à l'état visé (`plan.md`, `fonds.toml`, entrées acceptées de `rangement.toml`) et ne planifie que la différence, sans drapeau « fait » dans les fichiers de suivi. Une passe interrompue, une retouche faite dans Zotero ou une annulation sont ainsi prises en compte. La première passe porte la structure et les fiches déjà jugées, les suivantes les nouveaux paquets, les renommages de racines vont dans la passe où l'utilisateur les demande. Chaque passe exige une validation à jour (D102). Ajout après la première passe réelle du 29/09/2026 : `planifier` refuse tant que la copie locale n'a pas reçu la dernière version du serveur, sinon les collections créées par la passe précédente, absentes de la copie, seraient recréées. L'étape se termine quand `planifier` n'a plus rien à faire et que `rangement.toml` n'a plus de proposition en attente. Ensuite, `plan.md` suit Zotero (D23) et le contrôle (v0.3) prend le relais.

### D120. Groupes du plan de rangement

Options examinées.
- Un groupe par collection cible, avec sa création ou son renommage et les fiches qui y entrent ou en sortent, dans l'ordre de l'arbre, parents d'abord, puis les archives, la corbeille et les racines.
- Des groupes par nature d'opération. L'essai ne créerait que des collections vides.

Décision. Première option. L'essai donne des collections complètes, vérifiables dans Zotero.

### D121. Fiches à juger

Décision. `zc fonds a-ranger` écrit dans `rapports/` les fiches à répartir ou à placer, par paquets de 50. Chaque paquet donne la collection source, les définitions des cibles candidates tirées de `plan.md`, et pour chaque fiche la clé, l'auteur, l'année, le titre, le type, les tags et les autres collections. Les fiches déjà décidées dans `rangement.toml` sont omises, le filtre de D18 s'applique. `--resume <clé>` donne le résumé d'une fiche douteuse. L'agent ne lit jamais la base lui-même.

### D122. Essais de l'étape 5

Décision. Tests automatiques sur la bibliothèque synthétique et le faux serveur. Puis un test manuel sur le compte de test, qui vérifie la création avec une clé fournie (D114), la corbeille des collections, le renommage d'une racine et l'annulation. Puis la vraie bibliothèque, après sauvegarde, en commençant par la passe de structure, avec l'essai d'un groupe et la vérification de l'utilisateur avant le reste. Le skill `fonds` est complété pour l'étape 5 (D106). Test manuel fait le 29/09/2026 sur le compte de test, réussi jusqu'à l'annulation complète. Il a montré qu'une annulation doit rejouer les groupes du dernier au premier, pour sortir une collection d'une collection créée avant de mettre celle-ci à la corbeille, ce qui est corrigé.

### D123. Attente de la synchronisation entre deux passes

Constat sur une vraie bibliothèque. Le refus de planifier sur une copie locale en retard (D119) obligeait l'utilisateur à ouvrir Zotero, le laisser synchroniser, puis relancer, à chaque passe. Décision. `zc fonds planifier` relit la copie locale toutes les 5 secondes, pendant 3 minutes au plus, jusqu'à ce qu'elle ait rattrapé la version du serveur, en le disant. Zotero reste donc ouvert pendant toute la séance. Constaté ensuite, Zotero ouvert ne va pas toujours chercher seul les changements faits sur le serveur. Il faut alors lancer sa synchronisation (flèche verte), ce que le message d'attente demande. Il n'est fermé que pour `zc sauvegarder`, une fois par jour au plus. Passé le délai, le refus reste.

### D124. Collections à répartir entièrement jugées

Constat sur une vraie bibliothèque. Une fiche qui convient au thème où elle est y reste sans entrée (D116). `zc fonds a-ranger` la présentait donc à chaque fois, et rien ne distinguait une fiche jugée et laissée en place d'une fiche jamais vue. Options. A, une entrée « garder » par fiche dans `rangement.toml` (précis, mais des centaines d'entrées sans action). B, marquer la collection comme jugée dans `fonds.toml` (simple, mais ce fichier entre dans la validation, et une fiche arrivée ensuite ne serait plus présentée). C, noter à part les fiches que la collection contient au moment où elle est déclarée jugée. Décision C, choisie par l'utilisateur dans son principe (collection marquée, seules les fiches arrivées ensuite présentées). `zc fonds a-ranger --examinees CLE…` écrit `suivi/rangement-examinees.json` (chemin, date, clés des fiches) et refuse tant qu'une proposition attend sur une fiche de la collection. `a-ranger` ne présente plus ces fiches.

### D125. PDF identiques

Constat sur une vraie bibliothèque. Des PDF étaient rattachés à des fiches différentes. Quelques-uns étaient des doublons que `zc doublons chercher` ne voyait pas (dates ou titres différents), la plupart un PDF sur la mauvaise fiche (celui d'un autre article, d'une autre édition, du livre entier sur un chapitre), quelques-uns voulus (un chapitre et son livre, un commentaire et l'article cible). `zc` ne savait pas retirer une pièce jointe. Décision, choisie par l'utilisateur (option B plutôt que des retraits à la main dans Zotero). D'abord, `zc doublons chercher` propose aussi, à juger, les fiches qui portent le même PDF. Ensuite, `zc pieces chercher` écrit `suivi/pieces.toml`, un groupe par PDF présent en plusieurs copies, et l'on y décide, pour chaque groupe, `appliquer` (avec les copies à mettre à la corbeille et celles à rattacher à une autre fiche) ou `garder` (copies voulues, à ne plus signaler). Enfin, `zc pieces planifier` en tire un plan ordinaire (essai, journal, annulation). Règle de l'utilisateur : une copie qui porte des annotations ou des notes n'est jamais mise à la corbeille. Si elle est sur la mauvaise fiche, on la rattache à la bonne et l'autre copie part à la corbeille. La fusion de doublons appliquait déjà cette règle. `planifier` refuse aussi un groupe dont toutes les copies iraient à la corbeille.

### D126. Fiches confidentielles dans ce que `zc` écrit

Constat, le 01/10/2026, en préparant l'outil pour d'autres chercheurs. L'agent lit tout ce que `zc` écrit dans le dossier de travail. Seuls le plan du fonds et le rangement masquaient les fiches exclues par le filtre (D18, D66). L'audit, `suivi/doublons.toml`, `suivi/pieces.toml`, `suivi/metadonnees.toml`, les rapports de plan et les rapports d'annulation en montraient le titre, et parfois les valeurs (résumé, revue, nom du PDF). Options. A, masquer partout, la fiche restant traitée. B, exclure les fiches des doublons et des PDF identiques, comme le fonds et le rangement, au prix de doublons laissés en place, et masquer quand même ailleurs. C, ne corriger que les doublons et les PDF, l'audit restant « local » selon D18. Décision A, choisie par l'utilisateur, titre du groupe compris dans le fichier `.json` du plan. Une fiche exclue, ses pièces jointes et ses notes n'apparaissent que par leur clé suivie de « (fiche confidentielle) » (`filtre.cles_masquees`, `filtre.MASQUE`). Un rapport donne les noms des champs modifiés, sans leurs valeurs, et la note d'une source (qui décrit l'œuvre trouvée) est masquée dans `suivi/metadonnees.toml`. Les identifiants proposés à juger (DOI, ISBN, type) restent écrits, puisque la décision les reprend. Un groupe de doublons ou de PDF identiques est masqué en entier dès qu'une de ses fiches est exclue, ses fiches se ressemblant. Faute de pouvoir lire la base, `zc annuler` masque toutes les fiches. Le journal garde l'état complet d'avant, nécessaire à l'annulation, et n'est pas présenté à l'agent. L'agent reçoit une consigne (`AGENTS.md` livré) de ne pas chercher à lire une fiche masquée et de demander à l'utilisateur de la regarder dans Zotero.

### D127. L'agent vérifie avant de solliciter l'utilisateur

Constat, à la répétition générale du 02/10/2026 (outil installé depuis GitHub, guide suivi à la lettre sur le compte de test, l'agent ne disposant que des consignes livrées). Devant deux fiches de titres différents qui portaient le même PDF, l'agent a demandé à l'utilisateur d'aller ouvrir les PDF dans Zotero, comme le skill `doublons` le prévoyait (« quand la liste ne suffit pas à trancher »). Or la première page du PDF, lue en local, suffit le plus souvent, et l'agent n'avait aucun moyen prévu pour la lire, sinon fouiller lui-même la base et le dossier `storage` en contournant le filtre de confidentialité. Options, pour la forme. A, une commande générale `zc voir <clés>`, pour les doublons, les PDF identiques et les métadonnées. B, `zc doublons voir`, à répéter pour chaque étape. Pour le texte des PDF. A, `pypdf`, bibliothèque Python sans compilation installée avec l'outil, qui marche partout. B, `pdftotext` s'il est installé, sans dépendance, mais absent par défaut sous Windows et sous macOS sans Homebrew. Pour le moment de la vérification. A, pour tout cas douteux, avant toute recommandation. B, seulement quand la ligne du fichier de suivi ne suffit pas. Décision A dans les trois cas, choisie par l'utilisateur. `zc voir` accepte des clés de fiches ou de pièces jointes (une pièce jointe désigne sa fiche) et montre les champs complets, les créateurs, les collections, les tags, le nombre de notes (jamais leur texte) et, pour chaque PDF, le début du texte de ses deux premières pages (1 500 caractères). Une fiche confidentielle n'y est jamais montrée (D126), ni le texte des PDF si `exclure_texte_integral` est réglé (D66). Les skills `doublons` et `metadonnees` demandent de vérifier ainsi chaque cas douteux et de ne solliciter l'utilisateur que si le doute subsiste, en disant ce qui a été vérifié. Précise D79 et D121, et ajoute `pypdf` aux dépendances.

### D128. DOI inexistant et candidat certain

Constat sur une vraie bibliothèque. La plupart des DOI inconnus ou mal formés étaient des identifiants JSTOR (`10.2307/…`) que l'ancien convertisseur de Zotero rangeait dans le champ DOI, et que ni doi.org ni Crossref ne connaissent. Crossref proposait presque toujours le vrai DOI de l'éditeur, avec titre, auteur, année et revue identiques, mais le cas restait à juger. D'autres étaient de vrais DOI enveloppés dans l'adresse du proxy d'une bibliothèque (`dx.doi.org.ezproxy.exemple.org/10.…`), que `zc` proposait seulement de retirer. Décision, approuvée par l'utilisateur. Un DOI mal formé ou qui n'existe nulle part (D68) est remplacé sans jugement par un candidat qui remplit toutes les conditions de certitude (D62), la note du plan disant quel DOI est remplacé. Sans candidat certain, le cas reste à juger comme avant. La remise en forme d'un DOI reconnaît aussi l'adresse de résolution derrière un proxy.

### D129. Cas évidents approuvés en bloc

Constat, même jour. Les paquets de 10 (D80, D81) font relire à l'utilisateur des cas que l'agent a déjà vérifiés et où tout concorde, soit des dizaines de tours pour les DOI et ISBN manquants d'une grande bibliothèque. L'utilisateur a demandé pourquoi. La raison des paquets, garder de vrais jugements que l'on peut lire et interrompre, ne vaut que pour les cas douteux. Décision, approuvée par l'utilisateur. Le skill `metadonnees` demande à l'agent de vérifier chaque cas d'abord (note de la source, `zc voir`, résolution du DOI), puis de présenter les cas évidents en un seul bloc approuvé d'un mot, avec la liste complète à parcourir, et les seuls cas douteux par paquets de 10 au plus. Précise D80 et D81.

### D130. Communications et chapitres

Constat sur une vraie bibliothèque. Crossref classe en chapitres de livre les communications publiées dans des actes en collection (Lecture Notes de Springer, actes d'Elsevier). Les changements « communication → chapitre » proposés étaient tous faux, l'article de colloque étant le bon type. Un changement sûr refusé par l'utilisateur revenait en outre dans le plan suivant. Décision, approuvée par l'utilisateur. Le passage d'une communication à un chapitre n'est plus une transition sûre (révise D86), il est soumis au jugement. Un changement de type refusé n'est plus jamais proposé, sûr ou non.

### D131. Identifiant déjà posé, titres qui diffèrent

Constat sur une vraie bibliothèque. Presque tous les DOI signalés « discordants » désignaient bien la fiche, et environ six livres ou chapitres sur sept dont l'ISBN « semblait désigner un autre livre » étaient justes. Les titres ne différaient que par un sous-titre, une collection entre parenthèses (« Titre (Collection de l'éditeur) »), un article initial, une apostrophe ou une entité HTML (« &amp;amp; »), ou bien le titre était traduit (Cairn donne le titre anglais d'un article français), ou encore le titre de l'ouvrage était saisi pour un chapitre. Options. A, comparer les titres sans sous-titre, parenthèses ni article initial, puis, s'ils diffèrent encore, se fier au premier auteur et à l'année à un an près, avec un indice de plus (revue, volume, première page). B, seulement la comparaison des titres. C, ne rien changer et laisser l'agent trier avec `zc voir`. Décision A, choisie par l'utilisateur. Deux titres concordent quand leur ressemblance atteint `seuil_discordance` ou quand leurs titres principaux (sans sous-titre, parenthèses, article initial ni apostrophes) sont identiques (`sources.titres_concordants`). Pour un DOI (identifiants, types, compléments), la corroboration par l'auteur, l'année et un indice de plus s'ajoute (`metadonnees.meme_publication`). Pour un ISBN, seule la comparaison des titres s'applique. Le livre trouvé par l'ISBN porte souvent le nom du directeur et l'année de la fiche même quand la fiche est un chapitre saisi comme livre, et la corroboration aurait caché ces vrais problèmes (quelques-uns à l'essai). Ces règles servent seulement à vérifier un identifiant déjà posé. Le choix d'un candidat garde ses conditions de certitude (D62, D92). À l'essai, beaucoup moins d'ISBN signalés, et presque tous les DOI justes reconnus comme tels (les autres restent à juger). Le rapport des compléments liste désormais les fiches sautées, avec les deux titres.

### D132. Différences de pure forme

Constat sur une vraie bibliothèque. Le rapport des compléments listait de nombreuses « valeurs différentes, laissées telles quelles », dont la plupart ne différaient que par l'écriture. Une date plus ou moins précise (« 1991 » et « 1991-02 »), un ISSN sans tiret ou donné en partie, des pages abrégées (« 422-31 » et « 422-431 »), un article initial (« Les Cahiers de la revue »), « & » pour « and », un tiret long. Les vraies différences (autre numéro, autre année, autre revue) s'y perdaient. Options. A, ne plus lister une différence qui disparaît une fois les deux valeurs mises en forme. B, la compter à part sans la détailler. C, tout lister. Décision A, choisie par l'utilisateur (`metadonnees.meme_forme`). Une date est de même forme quand l'année concorde et que le mois et le jour concordent ou manquent d'un côté. Un ISSN ou un ISBN l'est quand les numéros de l'un sont tous chez l'autre. Des pages le sont une fois l'abréviation développée, ou quand seule la première page est donnée d'un côté. Un texte l'est quand les mêmes mots restent, sans accents, casse, ponctuation ni mots vides. Une abréviation (« J. Exp. Psychol. ») reste listée. Rien n'est jamais remplacé, comme avant (D60). À l'essai, beaucoup moins de lignes.

### D133. Fichiers absents encore sur zotero.org

Constat sur une vraie bibliothèque. L'audit comptait les fichiers absents du disque sans dire lesquels pouvaient être récupérés. Une vérification à la main sur zotero.org en a trouvé une partie encore stockés, les autres étant perdus. Options. A, l'audit interroge zotero.org pour chaque fichier absent. B, l'audit reste entièrement local et une commande à part fait la vérification. C, plus tard. Décision A, choisie par l'utilisateur. Pour chaque pièce jointe importée dont le fichier manque (un fichier lié n'est jamais sur le serveur), `zc audit` demande `GET /users/<id>/items/<clé>/file` sans suivre la redirection, qui renvoie vers le fichier s'il est stocké et donne 404 sinon (HEAD répond toujours 200). Une requête par fichier, de l'ordre de 0,2 seconde chacune. Le rapport donne les deux nombres et marque chaque fichier « sur zotero.org » ou « introuvable ». Sans clé API, sans connexion ou avec `--hors-ligne`, il donne le total et dit pourquoi la vérification n'a pas eu lieu. L'audit reste en lecture seule, et c'est sa seule requête au réseau (précise D26, point 5). Récupérer un fichier reste un geste dans Zotero (ouvrir la pièce jointe le retélécharge).

### D134. Cas triés par `zc`

Constat sur une vraie bibliothèque. Pour appliquer D129, l'agent a écrit à part un petit programme qui classait les cas de `suivi/metadonnees.toml` en évidents et douteux, en comparant titre, auteur, année, type, revue et éditeur. L'agent d'un autre utilisateur n'en disposerait pas, et refaire ce tri à la main sur des centaines de cas est long et inégal. Options. A, `zc` fait le tri et l'écrit dans le fichier de suivi, comme `suivi/doublons.toml` distingue déjà les groupes sûrs. B, une commande `zc metadonnees trier` à lancer avant de présenter les cas. C, laisser la méthode au skill. Décision A, choisie par l'utilisateur. Chaque proposition qui désigne une œuvre reçoit un avis (`avis = "concorde"`, ou ce qui diffère, par exemple « titre 0.72, auteur »), d'après les critères du skill `metadonnees` (titre concordant au sens de D131 avec une ressemblance d'au moins 0,9, premier auteur, année à un an près, type, revue ou ouvrage, éditeur et nombre d'éditions pour un livre, titre générique, compte rendu ou erratum). Un cas est `classe = "évident"` quand une seule proposition concorde, son numéro étant mis d'avance dans `choix`, et `"douteux"` sinon. La décision reste vide. L'agent vérifie toujours avant de présenter (résolution du DOI, `zc voir` pour les douteux), puis suit D129. Le rapport des identifiants donne le nombre d'évidents. Précise D129.

## v0.3, gestion

Décisions prises le 02/10/2026. Le nettoyage d'une vraie bibliothèque est fait jusqu'à l'étape 5. L'outil passe à l'usage quotidien (D31), à partir des références qui attendent dans l'Inbox.

### D135. Tri des nouvelles références

Options examinées, pour ce que fait le tri. A, tout le parcours, à savoir doublon déjà présent, métadonnées, thème du fonds d'après `plan.md` et sortie de l'Inbox, en un seul plan. B, le rangement seulement, doublons et métadonnées attendant le contrôle régulier. C, doublons et métadonnées seulement, le rangement restant à la main. Pour le déclenchement. A, sur demande, l'utilisateur disant à l'agent de trier l'Inbox. B, la même chose avec un rappel de l'audit. C, une tâche planifiée qui prépare le plan seule. Pour le périmètre. A, l'Inbox et les références sans place dans le fonds, puisque le connecteur de Zotero enregistre dans la collection sélectionnée et qu'une référence peut arriver directement dans un projet. B, l'Inbox seulement. Quand aucun thème ne convient. A, l'agent propose le thème le plus proche ou un nouveau thème avec sa définition pour `plan.md`, et la référence reste dans l'Inbox tant que l'utilisateur n'a pas tranché. B, toujours un thème existant. C, laisser dans l'Inbox sans proposition. Pour l'état de lecture. A, « 1 à lire » posé sur une référence sans état. B, demander. C, ne pas toucher aux tags. Pour la forme. A, `zc inbox preparer` puis `zc inbox planifier`, un seul plan. B, une option `--inbox` sur les commandes existantes, soit trois plans.

Décision, choisie par l'utilisateur. Tout le parcours, sur demande, pour l'Inbox et les références sans place dans le fonds (une référence d'un projet y reste et reçoit en plus son thème), avec proposition d'un thème proche ou nouveau, sans tag d'état, sous la forme `zc inbox`. `zc inbox preparer` cherche, pour ces seules références, les doublons, les identifiants et compléments, et les thèmes candidats. Il écrit les cas à juger dans les fichiers de suivi déjà connus (`suivi/doublons.toml`, `suivi/metadonnees.toml`, `suivi/rangement.toml`) et un rapport pour l'agent. Après jugement, `zc inbox planifier` fait un seul plan, avec par référence les fusions, les champs et les collections. Un skill `inbox` guide l'agent. Aucun tag n'est posé.

### D136. Sauvegarde et petits plans de gestion

Constat. Au-delà de l'essai, `zc appliquer --tout` exige une sauvegarde de moins de 24 heures, Zotero fermé (D15). Pour un tri de quelques dizaines de références, répété chaque semaine, c'est lourd, alors que le journal et `zc annuler` suffisent à revenir en arrière. Options. A, un plan de tri qui touche moins de 50 fiches s'applique sans sauvegarde récente, au-delà la règle reste. B, une sauvegarde de moins de 7 jours suffit pour la gestion, quelle que soit la taille. C, inchangé. Décision A, choisie par l'utilisateur. L'essai reste exigé, puisque c'est le moment où l'utilisateur vérifie dans Zotero (révisé par D138, le seuil se réglant désormais dans `[ecriture] petit_plan_de_gestion`).

### D137. Contrôle régulier

Options. A, un audit comparé au précédent, qui dit ce qui s'est dégradé (nouveaux doublons, fiches hors fonds, métadonnées manquantes), plus la cohérence entre `plan.md` et Zotero (thèmes sans définition, définitions sans thème, thèmes de plus de 40 fiches à subdiviser), l'agent proposant ensuite les plans qui corrigent. B, l'audit seul. C, plus tard. Décision A, choisie par l'utilisateur. À construire après le tri (D135).

### D138. Petits plans de gestion sans essai

Constat, au premier tri réel de l'Inbox. L'utilisateur a demandé à quoi servent les essais, aucun n'ayant révélé de problème. De fait, les erreurs trouvées sur la vraie bibliothèque l'ont toutes été à la relecture des plans (rôle des créateurs, ISBN avec espaces, faux changements de type), et l'essai coûte un aller-retour à chaque plan. Il garde son sens pour les plans lourds, une fusion ne s'annulant plus une fois la corbeille vidée et un plan de plus d'un millier de fiches étant long à défaire. Options. A, un plan de tri de moins de 50 fiches s'applique d'un coup, sans essai, l'utilisateur vérifiant après. B, tout plan de moins de 50 fiches, quelle que soit l'étape. C, inchangé. Décision A, approuvée par l'utilisateur. Les plans du nettoyage gardent l'essai, fusions comprises. Le seuil commun à D136 et D138 se règle dans `config.toml` (`[ecriture] petit_plan_de_gestion`, 50 par défaut, 0 pour garder essai et sauvegarde partout). Révise D35 et D136 pour les plans de tri.

### D139. Forme du contrôle régulier

Précise D137. Options. A, le contrôle vit dans `zc audit`. Chaque audit garde un instantané des points relevés (clés des fiches, des pièces jointes ou des collections, sans titres) dans `suivi/audits/`, ouvre son rapport par ce qui est apparu et ce qui est réglé depuis l'audit d'un jour précédent, et ajoute un douzième contrôle sur le plan du fonds. Un skill `controle` guide l'agent dans les corrections. B, une commande `zc controle` à part, avec son rapport. C, l'agent compare lui-même deux rapports d'audit, qui tronquent pourtant leurs listes à 100 lignes. Décision A, choisie par l'utilisateur. L'audit étant lancé au début de chaque séance, le contrôle vient sans y penser.

### D140. Gestes faits dans Zotero

Précise D23 et D137. Le lien entre un thème de `plan.md` et sa collection passe par le chemin, si bien qu'un thème renommé dans Zotero passait pour un thème disparu suivi d'un thème inconnu, que `zc fonds planifier` aurait recréé. Options. A, `zc` retient la clé de la collection de chaque thème (`suivi/fonds-collections.json`, tenu à jour par l'audit pour les thèmes où plan et Zotero concordent). Le contrôle repère les thèmes créés, renommés, déplacés ou supprimés dans Zotero, et `zc fonds suivre` met `plan.md` à jour (section renommée ou déplacée avec sa définition, thème nouveau ajouté sans définition, thème supprimé retiré) ainsi que les chemins des fichiers de suivi, puis enregistre la validation. L'agent rédige ensuite les définitions manquantes. B, le contrôle liste les écarts et l'agent corrige `plan.md` et le suivi à la main. C, `plan.md` commande et les gestes faits dans Zotero sont défaits. Décision A, choisie par l'utilisateur. Zotero fait foi après le nettoyage (D23).

### D141. Thèmes trop gros

Précise D21 et D109. Options. A, le contrôle signale les thèmes qui dépassent `seuil_sous_theme`, et `zc fonds titres <thème>` donne à l'agent la liste complète de leurs titres pour proposer des sous-thèmes avec leur définition et la répartition, que l'utilisateur valide avant le rangement habituel. B, le contrôle les signale seulement. Décision A, choisie par l'utilisateur. Un découpage n'est proposé que s'il est net (D109), le signalement reste une information.

### D142. Corrections après le contrôle

Options. A, le skill renvoie aux commandes existantes. Les références hors du fonds passent par `zc inbox`, les doublons et les métadonnées par les commandes des étapes 2 et 3 sur toute la bibliothèque, où les cas déjà jugés sont retenus et les sources gardées en cache, de sorte que seuls les cas nouveaux reviennent. B, `zc inbox` s'étend aux fiches apparues ou modifiées depuis le dernier contrôle. Décision A, choisie par l'utilisateur, à revoir si c'est trop lent sur une grosse bibliothèque.

## Étape 7, clés de citation

Décisions prises le 03/10/2026, à partir d'un document de travail préparé en lecture seule (faits vérifiés dans la documentation et le journal des versions de Better BibTeX, et sur le forum de Zotero). Zotero 7.0.31 a créé un champ natif `citationKey`, synchronisé et inscriptible par l'API web, mais Zotero ne calcule aucune clé. Better BibTeX (BBT) ne se sert de ce champ que depuis sa version 8, pour Zotero 8. Il n'a plus de base à lui, l'épinglage a disparu et toutes les clés sont fixes. Il remplit seul la clé d'une fiche qui n'en a pas (`fillKeyAfter`, 2 secondes par défaut) et ajoute un suffixe en cas de collision. Dans une bibliothèque tenue sous des versions récentes de Zotero et de BBT, aucune clé ne manque ni n'est en double.

### D143. Qui calcule les clés

Options. A, BBT toujours, `zc` contrôlant seulement. B, `zc` calcule toutes les clés manquantes avec une version Python de la formule. C, BBT pour les clés manquantes, `zc` pour ce que BBT ne fait pas, à savoir départager les clés en double et ranger les restes de `Citation Key:` dans Extra. Décision C, choisie par l'utilisateur. Reproduire BBT à l'identique serait un chantier, et un écart donnerait deux styles de clés.

### D144. Clés en double

Options. A, la fiche la plus ancienne (`dateAdded`) garde la clé, les autres reçoivent le premier suffixe libre (a, b…), comparé sans tenir compte de la casse comme BBT par défaut. B, vider la clé des fiches en surnombre et laisser BBT la remplir. C, juger chaque groupe. Décision A, choisie par l'utilisateur. Un groupe dont les fiches forment un groupe de doublons non jugé distinct est renvoyé à l'étape 2, la fusion réglant la clé. L'utilisateur peut imposer la fiche qui garde la clé dans `suivi/cles.toml`. Si BBT est réglé pour distinguer la casse, `zc` suit ce réglage. L'audit passe à la même comparaison.

### D145. Révision de D24, détection de BBT

Révise D24. Options. A, le champ natif sert à partir de Zotero 8 et BBT 8, et l'étape refuse de tourner sous BBT 7. La formule vit dans BBT, `zc` la lit et la montre sans la recopier dans `config.toml`. Un module unique lit le profil de Zotero (`profiles.ini`, puis le `prefs.js` qui désigne le dossier de données, `extensions.json` pour la version et l'état de BBT, `prefs.js` pour la formule, le remplissage, la régénération et la casse), avec en repli la recherche actuelle d'un dossier `better-bibtex/`, en le disant. B, la même chose avec une section `[cles]` dans `config.toml` comparée à BBT. Décision A, choisie par l'utilisateur. La règle de D2 vise ce que `zc` applique, ici c'est BBT qui applique la formule. Un BBT présent mais désactivé compte comme absent. L'audit montre la formule de BBT et signale qu'elle diffère de la méthode par défaut, sans plus.

### D146. Le reste de l'étape 7

Décisions recommandées et acceptées en bloc par l'utilisateur.
- Les clés s'écrivent dans le champ natif seulement.
- Une clé unique n'est jamais touchée, même hors format. Qui veut réformer ses clés le fait dans Zotero par « Refresh » de BBT.
- Sans BBT, l'étape est sautée et l'audit dit pourquoi. Le contrôle des doubles reste, puisqu'il ne demande aucun calcul. Un calcul par `zc` viendra plus tard si un utilisateur en a besoin.
- Une seule commande, `zc cles planifier`, qui compare l'état réel à l'état visé (D119). `suivi/cles.toml`, facultatif, n'est écrit que pour les cas qui demandent un avis (fiche qui garde la clé, ligne d'Extra différente de la clé native, groupe renvoyé à l'étape 2).
- Une ligne `Citation Key:` d'Extra passe dans le champ natif s'il est vide, est retirée si elle est identique, et devient un cas à juger si elle diffère. Le reste d'Extra est intact.
- Plan d'un groupe par clé en double et d'un groupe par fiche pour Extra, avec essai et sauvegarde comme au nettoyage (D35, D42), et l'annulation du socle.
- L'audit, `zc cles planifier` et `zc appliquer` avertissent quand BBT régénère les clés à chaque changement (`resetKeyOnChange`), puisqu'une étape qui touche des milliers de fiches changerait alors autant de clés. Ils signalent aussi `fillKeyAfter = 0` quand des fiches n'ont pas de clé.
- Une fusion de doublons signale dans son rapport la clé de la fiche absorbée qui disparaît. Un alias dans Extra (`tex.ids`) sera examiné après vérification.
- Le tri de l'Inbox ne pose pas de clé, BBT le fait à l'arrivée. Il signale une référence sans clé et départage une clé en double selon D144, dans le groupe de la fiche.
- Avant de construire, une sonde sur le compte de test, avec BBT installé dans son profil, vérifie qu'une clé écrite par l'API est gardée par BBT, si une clé vidée est remplie, si un double reçu par synchronisation reste en place, si une installation neuve crée un dossier `better-bibtex/`, et ce que l'export fait d'une ligne `tex.ids`.

## Étape 8, noms des fichiers

Décisions prises le 03/10/2026, à partir d'un document de travail préparé en lecture seule (code de Zotero 10.0.5 et du serveur, documentation). Depuis Zotero 8, le fichier principal d'une fiche est renommé à chaque modification locale, d'après le modèle `attachmentRenameTemplate`, réglage synchronisé. Les changements reçus par synchronisation ne déclenchent pas ce renommage, si bien que tout ce que `zc` écrit par l'API laisse le nom en retard. Le serveur accepte en revanche une nouvelle valeur de `filename` pour un fichier importé, et Zotero renomme alors le fichier local à la synchronisation suivante. Ce mécanisme n'est pas documenté. Sur une vraie bibliothèque, la plupart des PDF « hors modèle » de l'audit sont des fiches sans année, que Zotero nomme « Auteur - Titre », et seule une petite partie des noms est vraiment en retard.

### D147. Qui renomme

Révise D28 pour le renommage. Options. A, Zotero lui-même, par « Renommer les fichiers… », sans essai ni journal. B, un script JavaScript généré par `zc`, à coller dans Zotero. C, l'API web, par un plan ordinaire (une opération `filename` par pièce jointe), chaque poste renommant ses fichiers à la synchronisation. Décision C, choisie par l'utilisateur, après une sonde sur le compte de test (fichier présent, fichier absent, nom qui ne change que par la casse, ouverture dans Zotero, annulation), comme D114 pour les collections. Si la sonde échoue, repli sur B. B reste l'outil des fichiers liés, que l'API ne renomme pas, et l'oracle des tests.

### D148. Modèle de nom

Révise D25 sur la forme. Options. A, Zotero fait foi. `zc` lit le modèle réglé dans Zotero et le calcule en Python pour les formes courantes, et refuse un modèle hors de ce sous-ensemble en renvoyant au script. B, `config.toml` fait foi et `zc` écrit le modèle dans Zotero. Décision A, choisie par l'utilisateur. D25 est exactement le modèle par défaut de Zotero (`{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}`). `modele_fichier` disparaît de `config.toml`, et le changer se fait dans les réglages de Zotero.

### D149. Noms laissés en retard par les autres plans

Options. A, tout plan qui change les créateurs, la date ou le titre d'une fiche renomme aussi sa pièce jointe principale. B, aucun plan ne renomme, le contrôle régulier signale les retards. C, A pour le tri de l'Inbox, B pour les plans du nettoyage. Décision C, choisie par l'utilisateur. Le tri touche peu de fiches et son plan est déjà unique (D135). Les retards laissés par le nettoyage se rattrapent en une passe de `zc noms planifier`.

### D150. Le reste de l'étape 8

Décisions recommandées et acceptées en bloc par l'utilisateur.
- La conjonction de `firstCreator` (« et » ou « and », selon la langue de Zotero) est déduite des noms existants à deux auteurs, avec un réglage de secours dans `config.toml`.
- Seule la pièce jointe principale de chaque fiche est renommée, pour les types que Zotero renomme, comme Zotero le fait. Les PDF secondaires restent une information de l'audit. Les fichiers liés sont laissés au réglage de Zotero pour l'instant, le script viendra si un utilisateur en a besoin.
- Un fichier absent du disque est renommé s'il est encore sur zotero.org (D133), pas s'il est introuvable partout.
- Un nom en collision dans le dossier de la pièce jointe, refusé par Windows (point final, nom réservé) ou d'un chemin trop long est écarté et listé, sans corriger le nom à la manière de `zc`.
- Un titre de pièce jointe égal à l'ancien nom devient le titre court de Zotero (« PDF ») dans la même opération.
- Plan de nettoyage ordinaire, avec essai et sauvegarde. L'audit vérifie après coup qu'aucune pièce jointe ne pointe vers un nom absent alors que son dossier contient un autre fichier, et signale un renommage automatique désactivé dans le profil.
- L'audit calcule les noms attendus avec le moteur de D148 quand le modèle est pris en charge, et garde une expression régulière corrigée sinon.

## Étape 6, tags

Décisions prises le 03/10/2026, après celles des étapes 7 et 8, à partir d'un document de travail préparé en lecture seule (documentation de l'API web, code et tests du serveur et de Zotero). Supprimer un nom par `DELETE /tags` le retire pour ses deux types, exige la version de toute la bibliothèque et touche la corbeille. L'API n'a pas de renommage, il faut réécrire la liste complète des tags de chaque fiche, en gardant `"type": 1` sur un tag automatique conservé. Les couleurs vivent dans le réglage `tagColors`, que ni la suppression ni la réécriture ne mettent à jour. Le réglage `extensions.zotero.automaticTags` gouverne le connecteur, l'ajout par identifiant et la récupération des métadonnées d'un PDF, mais un import RIS ou BibTeX pose les mots-clés d'éditeurs en tags **manuels**. Faute d'une vraie bibliothèque riche en tags, l'essai réel se fera sur le compte de test puis chez un autre utilisateur.

### D151. Périmètre de l'étape 6

Précise D22. Options. A, tout le jeu de tags dans un seul inventaire et un seul plan, avec des tags protégés. B, tags automatiques et variantes seulement. C, tags automatiques seulement. Décision A, choisie par l'utilisateur. Sont protégés, c'est-à-dire inventoriés sans proposition et changés seulement par une entrée de l'utilisateur, les tags techniques (`_`), les états et marques de `config.toml`, les tags colorés et une liste libre `[tags] proteges`. Les tags de `tags_exclus` ne changent jamais, `zc` s'en servant pour filtrer.

### D152. Tags automatiques

Options. A, une règle globale les supprime, avec des exceptions proposées par `zc` (tag porté par au moins `seuil_candidat` fiches, 5 par défaut, ou de même forme qu'un tag manuel, un concept ou un thème) et jugées par l'agent. B, tout juger. C, tout supprimer. D, les masquer dans Zotero. Décision A, choisie par l'utilisateur. L'utilisateur accepte la règle une fois, et le rapport dit combien de noms et d'occurrences elle retire.

### D153. Mots-clés importés en tags manuels

Options. A, les juger comme les autres tags manuels hors familles. B, `zc` repère les fiches qui portent plus de `seuil_mots_cles` tags manuels hors familles (8 par défaut) dont les tags reviennent rarement ailleurs, et propose de traiter ces lots comme des tags automatiques (règle de D152, mêmes exceptions). C, tout tag manuel porté par une seule fiche est traité comme automatique. Décision B, choisie par l'utilisateur. Les tags d'annotations, posés à la main dans le lecteur, n'entrent jamais dans ces lots.

### D154. Concepts tirés des tags existants

Précise D23 et D103. Options. A, par la dispersion. Un tag candidat réparti sur au moins `dispersion_concept` thèmes du fonds (2 par défaut) est proposé comme concept, l'agent proposant son nom et une définition courte dans la section `# Concepts` de `plan.md`. Un tag concentré dans un seul thème double ce thème. Il est proposé à la suppression une fois que chacune de ses fiches est dans le thème, celles qui manquent étant d'abord proposées dans `suivi/rangement.toml` (source `tag`, D116). B, l'utilisateur choisit librement. C, plus tard. Décision A, choisie par l'utilisateur.

### D155. Prévention après le nettoyage

Révise D135 sur les tags. Options. A, le tri de l'Inbox applique les règles acceptées de `suivi/tags.toml` (tags automatiques retirés, variantes et états ramenés à leur forme) dans l'opération de chaque fiche, et signale les tags manuels nouveaux hors familles. B, l'audit et `zc init` lisent `extensions.zotero.automaticTags` dans le profil et recommandent de décocher le réglage, dans Zotero et dans le connecteur, dont le réglage n'est pas lisible. C, A et B. Décision C, choisie par l'utilisateur.

### D156. Le reste de l'étape 6

Décisions recommandées et acceptées en bloc par l'utilisateur.
- Variantes regroupées par forme normalisée (casse, accents, espaces, tirets, préfixe `#`, pluriel simple), automatiques compris. La forme gagnante suit une règle fixe (le concept, puis le tag manuel le plus porté, puis la forme en minuscules accentuée). Un groupe qui ne diffère que par la casse, les accents, les espaces ou le préfixe est « évident » et s'approuve en bloc (D129, D134), les autres vont par paquets de 10. Une fusion pose le tag gagnant en manuel, comme Zotero.
- États et marques venus d'autres habitudes proposés vers ceux de `config.toml` à partir d'un petit dictionnaire français et anglais, rien d'office. Une fiche qui recevrait deux états garde le plus avancé.
- Tag manuel hors familles porté par une seule fiche et sans ressemblance avec un concept ou un thème, « évident » à supprimer, en bloc. Les autres par paquets de 20, avec effectif, dispersion et trois titres, et un sort parmi `supprimer`, `garder`, `concept`, `fusionner`. Garder est légitime.
- Commandes `zc tags inventaire` (rapport et `suivi/tags.toml`, décisions gardées d'une fois sur l'autre) et `zc tags planifier`. `zc voir --tag <nom>` montre les fiches qui portent un tag.
- `suivi/tags.toml` décrit des règles par nom de tag, jamais par fiche (section `[automatiques]` pour la règle globale, entrées `[[tag]]` et `[[variantes]]`), et sert ensuite au tri.
- Plan d'une opération par élément, qui écrit sa liste complète de tags d'après toutes les règles à la fois, types conservés. Pas de `DELETE /tags`. L'annulation reste celle du socle.
- `zc` ne touche pas à `tagColors` (sauf les couleurs des tags de la méthode, D175). Un tag coloré est protégé, et le skill renvoie à « Renommer le tag… » de Zotero, qui reporte la couleur.
- Les mêmes règles valent pour pièces jointes, notes et annotations, la corbeille étant ignorée, sous réserve de la sonde.
- Un tag porté seulement par des fiches confidentielles est masqué dans l'inventaire, le suivi et les rapports, sous un identifiant stable. Seule la règle globale s'y applique.
- `lecture.py` lit les recherches enregistrées. Un tag cité par l'une d'elles n'est supprimé qu'après confirmation dans le suivi, et le rapport rappelle de mettre la recherche à jour.
- Essai sur 5 éléments choisis pour couvrir chaque sorte de changement, sauvegarde au-delà (D35, D42). Plan relançable qui ne planifie que la différence (D119), sans exiger la fin de l'étape 5. Une proposition de rangement en attente qui repose sur un tag protège ce tag.
- Avant de construire, une sonde sur le compte de test vérifie qu'un tag réécrit avec `"type": 1` reste automatique, qu'une annotation accepte la réécriture de ses tags, ce que devient un tag coloré sans fiche, et si Zotero purge les tags orphelins.

## Stockage des fichiers et sauvegardes

Décisions prises le 03/10/2026, pour tenir compte de la synchronisation des fichiers par WebDAV et des logiciels de sauvegarde. Elles valent pour tous les utilisateurs, qui peuvent synchroniser leurs fichiers par zotero.org, par WebDAV ou pas du tout. Un profil peut aussi avoir la synchronisation des fichiers désactivée alors que des fichiers restent sur zotero.org, d'une synchronisation plus ancienne.

### D157. Où sont stockés les fichiers

Précise D133. L'audit cherchait sur zotero.org les fichiers absents du disque, ce qui ne dit plus si un fichier est récupérable quand Zotero synchronise ses fichiers ailleurs. Options. A, `zc` le détecte dans le `prefs.js` du profil qui sert le dossier de données (`extensions.zotero.sync.storage.enabled` et `.protocol`, valeurs par défaut de Zotero quand elles manquent), par le module qui lit déjà le profil pour Better BibTeX (`bbt.py`). B, un réglage dans `config.toml`. C, A avec un réglage qui l'emporte. Décision A, choisie par l'utilisateur. Les utilisateurs ne savent pas forcément ce qu'ils utilisent, le profil le sait, et `zc` ne reçoit jamais d'identifiants WebDAV. Ajustement à la construction. La vérification sur zotero.org est gardée dans tous les cas, puisque d'anciennes copies peuvent y rester, même quand la synchronisation des fichiers a été désactivée. Ce qui change selon le cas, c'est ce que l'audit en dit. Par zotero.org, ouvrir la pièce jointe la retélécharge (D133). Par WebDAV, un fichier absent de zotero.org est peut-être sur le serveur WebDAV et revient en ouvrant la pièce jointe, une copie restée sur zotero.org se télécharge depuis la bibliothèque en ligne. Sans synchronisation, Zotero ne retélécharge rien et une copie restée sur zotero.org se télécharge de la même façon. L'audit dit aussi comment Zotero synchronise les fichiers. Sans profil trouvé, l'audit parle comme D133.

### D158. Fichiers absents à l'étape 8, hors stockage zotero.org

Précise D150. Options. A, sous WebDAV ou sans synchronisation des fichiers, un fichier absent n'est pas renommé, il est listé dans le rapport. B, il est renommé, Zotero appliquant le nom au téléchargement. Décision A, choisie par l'utilisateur, par prudence. La règle de D150 (renommé s'il est encore sur zotero.org) ne vaut que si Zotero synchronise par zotero.org (D157). Le cas reste rare, une copie locale complète des fichiers étant la règle.

Constat sur une vraie bibliothèque dont la synchronisation des fichiers est désactivée dans Zotero. Huit fichiers renommés par `zc noms` portaient leur nouveau nom sur le disque après la synchronisation des données, sans ancien fichier restant, y compris un changement de casse seul. Le renommage local ne dépend donc pas de la synchronisation des fichiers. Le cas WebDAV reste à sonder (D160, D166).

### D159. Sauvegardes de `zc` et logiciels de sauvegarde

Précise D41. Chaque `zc sauvegarder` clone le dossier Zotero, ce qui ne coûte presque rien sur un volume APFS, mais Time Machine ne garde pas les clones et recopie chacun en entier. Borg le déduplique mais le relit. Options. A, `zc sauvegarder` écarte lui-même son dossier, par un fichier `CACHEDIR.TAG` (convention reconnue par Borg avec `exclude_caches`, restic et tar avec `--exclude-caches`) et, sur macOS, par `tmutil addexclusion`, une seule fois, quand le `CACHEDIR.TAG` manque (`tmutil` prend une dizaine de secondes). Ailleurs, le guide explique quoi faire (D11). B, le guide seul. C, rien. Décision A, choisie par l'utilisateur. Ces copies ne durent que quelques jours et doublent celle du dossier Zotero, que les logiciels de sauvegarde gardent déjà. Un échec de l'exclusion n'empêche pas la sauvegarde. Le dossier de travail, lui, doit être sauvegardé (journaux nécessaires à l'annulation, suivi, `plan.md`), ce que dit le guide.

### D160. Sonde du renommage sous WebDAV

Précise D147. La sonde de D147 téléverse ses PDF par l'API, donc vers zotero.org, ce qui est impossible sous WebDAV, où c'est Zotero qui dépose les fichiers. Elle doit vérifier qu'un nom écrit par l'API est appliqué sur le disque, que la copie WebDAV suit et qu'un autre poste ouvre le fichier sous son nouveau nom. Options. A, un sous-compte WebDAV chez un hébergeur pour le compte de test. B, un petit serveur WebDAV local lancé pour la seule sonde (par exemple `rclone serve webdav`). Décision B, choisie par l'utilisateur. La sonde ne dépend ni d'un hébergeur ni d'une bibliothèque réelle, et n'importe quel développeur peut la refaire. Elle se fait une fois l'étape 8 construite. Si elle échoue, l'étape 8 se replie sous WebDAV sur le script de D147 (option B).

## Sondes des étapes 6 à 8

### D161. Résultats des sondes des tags et des noms de fichiers

Sondes lancées le 03/10/2026 sur le compte de test, Zotero 10 ouvert sur le profil de test.

Tags (D156), 17 vérifications réussies, plus les réponses de l'utilisateur. Un tag réécrit avec `"type": 1` dans la liste complète reste automatique, sur le serveur comme dans Zotero, et un tag réécrit sans type devient manuel. Une annotation accepte la réécriture de ses tags par l'API. Un tag coloré dont on retire la dernière fiche garde sa couleur dans `tagColors` et reste dans le sélecteur, grisé et non sélectionnable, occupant une des neuf places. Il faut donc le laisser à l'utilisateur, ce que fait D156. Zotero garde dans sa table locale un tag qui ne porte plus aucune fiche, mais ne l'affiche plus dans le sélecteur. Rien à nettoyer de ce côté. Aucune erreur de synchronisation.

Noms de fichiers (D147), 33 vérifications réussies. Le serveur accepte un nouveau `filename` pour un fichier importé, sans changer son contenu ni sa date. À la synchronisation suivante, Zotero renomme le fichier sur le disque, y compris quand seule la casse change, met à jour le chemin de la pièce jointe et ne renvoie rien au serveur. Le fichier s'ouvre sans erreur. Remettre l'ancien `filename` (annulation) remet l'ancien nom sur le disque de la même façon. D147 est confirmée, le renommage passe par un plan ordinaire. Le cas d'un fichier pas encore téléchargé, observé le 04/10/2026 (« Télécharger les fichiers » réglé sur « au besoin »), est concluant. Zotero enregistre le nouveau nom sans rien télécharger, puis, à l'ouverture, télécharge le fichier directement sous ce nom et l'ouvre. Il renvoie alors au serveur une modification de la pièce jointe, sans toucher au nom, vraisemblablement l'état de lecture. L'annulation remet l'ancien nom de la même façon. D150 est confirmée pour la synchronisation par zotero.org.

### D162. Résultats de la sonde des clés de citation

Sonde lancée le 03/10/2026 sur le compte de test, avec Better BibTeX installé neuf dans le profil de test, réglages par défaut. 11 vérifications réussies, plus les réponses de l'utilisateur. Une clé reçue avec une fiche nouvelle est gardée. Une fiche reçue sans clé en reçoit une de BBT, qui la renvoie au serveur à la synchronisation suivante. Une clé écrite par l'API sur une fiche qui en avait une est gardée telle quelle, sans être recalculée. Une clé vidée par l'API est aussitôt remplie par BBT. Un double reçu par synchronisation reste en place sans aucun signalement de BBT, ce qui confirme D144 (c'est à `zc` de le départager). Les clés des autres fiches ne bougent pas, et une ligne `tex.ids` d'Extra est laissée intacte. Une installation neuve de BBT crée un dossier `better-bibtex/` dans le dossier de données. La détection de repli de D145 reste donc valable. Aucune erreur de synchronisation. L'export d'un alias `tex.ids` vers le champ `ids` de BibLaTeX n'a pas été vérifié. L'alias de la clé d'une fiche absorbée par une fusion (D146) reste à examiner.

### D163. Clés en double sans Better BibTeX

Précise D146. Sans BBT actif, `zc cles planifier` départage quand même les clés en double, puisque le suffixe ne demande aucune formule et que D162 montre que BBT, même présent, les laisse en place. Les lignes `Citation Key:` d'Extra attendent BBT. Choix fait à la construction le 04/10/2026, confirmé par l'utilisateur.

### D164. Essai de bout en bout des étapes 6 à 8 sur le compte de test

Fait le 04/10/2026, plans appliqués (essai puis reste) puis annulés, résultats vérifiés par l'API et sur le disque. Tags : 2 fiches, tags automatiques retirés avec la règle globale, variante ramenée à sa forme, annulation qui rend tags et types. Un défaut trouvé et corrigé : un tag qui double un thème était retiré d'une fiche pas encore rangée dans ce thème (une décision de rangement acceptée mais pas encore appliquée empêchait la proposition). Il reste désormais sur ces fiches jusqu'à leur rangement (D154). Clés : double départagé malgré une différence de casse, lignes d'Extra retirées (identique, et différente jugée « natif »), double formé de vrais doublons renvoyé à l'étape 2, BBT qui garde la clé suffixée, annulation complète. Le suffixe continue désormais la série de BBT (« …2000a » en double donne « …2000b », et non « …2000aa »). Noms : 9 fichiers renommés sur le disque par la synchronisation automatique de Zotero en une dizaine de secondes, audit ensuite conforme, annulation qui rend les anciens noms. Le tri de l'Inbox avec ces trois étapes n'est couvert que par les tests automatiques.

### D165. Essai du tri de l'Inbox avec les étapes 6 à 8

Fait le 04/10/2026 sur le compte de test, avec une référence volontairement en désordre dans l'Inbox (vrai DOI sans date, deux tags automatiques, clé déjà prise par une fiche plus ancienne, PDF nommé `scan0001.pdf`). `zc inbox planifier` a tout réuni dans le groupe de la fiche : champs complétés par Crossref, clé suffixée (`…1990c`, la série de BBT continuée), tags automatiques retirés par la règle acceptée, et fichier renommé d'après la date que le plan venait de compléter (D149). Plan de moins de 50 fiches appliqué d'un coup (D138), fichier renommé sur le disque par la synchronisation automatique, puis annulation qui a tout rendu.

## Répétition du pilote

Le 04/10/2026, un agent sans contexte, installé depuis GitHub et ne connaissant que les consignes livrées, a mené le nettoyage complet d'une bibliothèque de test en désordre (105 fiches), de l'audit au contrôle régulier. 13 plans appliqués sans conflit, 4 gestes de l'utilisatrice dans Zotero, audit final propre. Il a relevé 40 frictions, dont les corrections suivent. D166 est réservée au résultat de la sonde WebDAV (D160).

### D167. Collection « répartir » vidée

Options. A, une fois vide et marquée examinée (D124), `zc fonds planifier` la met à la corbeille de Zotero, d'où `zc annuler` la reprend. B, le skill dit de passer son sort à « dissoudre ». Décision A, choisie par l'utilisateur. Précision faite à la construction : la collection est « vidée » quand il n'y reste que des fiches jugées et laissées en place. Elles gardent leurs autres collections, et celles qui n'ont pas d'autre place dans le fonds sont signalées comme sans place, comme pour « dissoudre ». Au passage, l'attente de la copie locale (D123) refuse après 3 minutes avec un seul message, qui demande de synchroniser à la main.

### D168. Fichiers pas encore téléchargés à l'étape 2

Constat. Sans les fichiers sur le disque, le contrôle des PDF identiques répondait « OK », `zc pieces chercher` ne trouvait rien et la fusion rattachait les copies identiques au lieu de les mettre à la corbeille. Options. A, l'audit dit « non contrôlé » avec le nombre de fichiers absents, `zc pieces chercher`, `zc doublons planifier` et `zc voir` le rappellent, et le skill des doublons demande de faire télécharger les fichiers avant l'étape 2. B, `zc doublons planifier` refuse tant que des fichiers importés manquent. Décision A, choisie par l'utilisateur.

### D169. DOI introuvable sans autre piste

Précise D134. Options. A, un DOI introuvable (résolution vérifiée) dont la seule proposition est de le retirer est classé « évident », approuvé en bloc avec la liste complète (D129). B, il reste « douteux ». Décision A, choisie par l'utilisateur.

### D170. Audit de comparaison

Confirme D139. Le contrôle compare toujours au dernier audit d'un jour précédent, pour que les corrections de la journée apparaissent comme réglées. Les consignes livrées et le rapport le disent avec la date de cet audit. Choisi par l'utilisateur.

## Durée du nettoyage

La répétition a duré environ une heure pour 105 fiches, dont un quart d'heure bloqué parce que Zotero ne recevait pas les changements de collections, et une demi-heure passée à juger un par un des cas de métadonnées classés douteux. Les décisions suivantes visent ces deux pertes et mesurent le reste.

### D171. Copie locale en retard sur le serveur

Constat. Avant chaque passe, les commandes qui lisent l'état réel (D119) attendaient jusqu'à trois minutes que Zotero ait reçu la passe précédente, puis refusaient. Zotero ne va pas toujours chercher seul les changements de collections faits par l'API, d'où des blocages d'un quart d'heure et un geste de l'utilisateur à chaque passe. Options. A, lire sur zotero.org les seuls objets changés depuis la version de la copie locale (éléments, collections, suppressions définitives, réglages) et les reporter sur la bibliothèque lue, ce qui couvre aussi les changements faits depuis un autre appareil. B, rejouer les journaux de `zc`, sans requête, mais en attendant toujours si le retard vient d'ailleurs. C, garder l'attente. Décision A, tout de suite et sans attente, choisie par l'utilisateur. La commande le signale en une ligne et rappelle de synchroniser Zotero avant d'y vérifier quoi que ce soit. Le socle relit de toute façon chaque élément avant d'écrire, si bien qu'un plan fondé sur cet état reste sûr. Concerne `zc fonds planifier`, `zc tags planifier`, `zc cles planifier`, `zc noms planifier` et `zc inbox planifier`. L'audit lit toujours la seule copie locale.

Vérifié le 04/10/2026 sur le compte de test, en lecture seule. La bibliothèque rebâtie entièrement par l'API depuis la version 0 redonne la copie locale à l'identique (110 éléments, collections, pièces jointes, notes, annotations), une fois les dates mises sous la forme de la base (« 2010-00-00 2010 »). Seule différence, Zotero de bureau met des tirets dans les ISBN qu'il reçoit (« 0-262-54067-3 ») alors que le serveur garde la forme sans tirets, sans effet sur les plans.

### D172. Cas évidents des métadonnées acceptés en bloc

Constat. L'agent écrivait chaque décision à la main dans `suivi/metadonnees.toml` et vérifiait de nouveau la résolution des DOI que `zc` avait déjà contrôlée. Options. A, `zc metadonnees accepter --evidents` accepte d'une commande tous les évidents encore à juger, après l'approbation du bloc par l'utilisateur, et l'agent ne refait plus les vérifications de `zc`. B, la même commande, l'agent gardant la vérification de quelques DOI. C, statu quo. Décision A, choisie par l'utilisateur. Précision faite à la construction, la même commande accepte des fiches données une à une (`<clé>=<numéro>`), `zc metadonnees refuser <clés>` refuse, et `--sauf` écarte des évidents. Ainsi l'agent n'écrit plus de décision dans le fichier, hors des cas `forcer`. Seuls les cas encore à juger changent.

### D173. Durée des commandes

Constat. La durée de la répétition ne se reconstituait qu'à partir des dates des fichiers. Options. A, chaque commande lancée dans un dossier de travail ajoute une ligne à `journal/commandes.jsonl` (commande, arguments, début, durée, code de retour), et les intervalles entre deux commandes donnent le temps de l'agent et de l'utilisateur. Rien ne quitte l'ordinateur. B, la durée affichée à la fin de chaque commande, sans rien garder. Décision A, choisie par l'utilisateur. Précisions faites à la construction. La liste des journaux d'écritures (`zc journal`, reprises, annulations) ignore ce fichier. L'attente de Zotero n'a pas de colonne à part, puisque D171 la supprime. Un échec d'écriture du registre n'empêche jamais la commande.

### D174. Vérification de l'essai par l'agent

Constat. À la seconde répétition (04/10/2026, environ 21 minutes de nettoyage pour 105 fiches, dont 3 min 30 de commandes, 10 minutes d'agent et 8 minutes de gestes), la moitié des gestes demandés à l'utilisateur étaient des vérifications que `zc voir` permettait à l'agent de faire seul. Ils venaient de la règle « Après l'essai, attendre qu'il ait vérifié le résultat dans Zotero » de l'`AGENTS.md` livré, reprise par chaque skill. Décision, choisie par l'utilisateur. L'accord explicite avant chaque plan reste, et vaut pour l'essai et pour le reste. Après l'essai, l'agent vérifie lui-même avec `zc voir`, dit ce qu'il a vérifié et applique le reste, sauf écart avec le rapport. Un geste n'est demandé que pour ce que `zc` ne peut ni faire ni lire (fermer ou rouvrir Zotero, synchroniser, régler), en une seule demande. Pour les noms de fichiers, la synchronisation reste nécessaire (seul Zotero renomme sur le disque), puis `zc voir` montre si chaque fichier porte son nouveau nom.

Va avec D171 étendue. `zc voir`, `zc doublons chercher` et `planifier`, `zc pieces chercher` et `planifier`, `zc metadonnees` (sous-étapes, `accepter`, `refuser`) lisent aussi sur zotero.org ce que Zotero n'a pas encore reçu, si bien que la vérification se fait juste après l'essai, sans attendre la synchronisation. Les commandes qui ne font que lire se contentent de la copie locale si zotero.org est injoignable, en le disant.

### D175. Couleurs des tags de la méthode

Précise D156, où `zc` ne touchait pas à `tagColors`. Constat. Colorer les cinq tags de la méthode les met en tête du sélecteur, marque chaque fiche d'une pastille et donne à chacun la touche de son rang (la touche 3 pose ou retire « 3 lu »). Un nouvel utilisateur n'en aurait rien. Décisions, toutes recommandées et choisies par l'utilisateur. A, `zc tags planifier` propose les couleurs, en premier groupe du plan (donc dans l'essai), avec accord, journal et annulation, et le tri de l'Inbox ne s'en occupe pas. B, une palette par défaut, réglable dans `config.toml` (`[methode] couleurs`, dans l'ordre des états puis des autres tags, liste vide pour n'en proposer aucune). C, les tags de la méthode en tête, les tags déjà colorés gardant leur couleur et suivant, le rapport disant lesquels changent de touche. Un tag de la méthode déjà coloré garde sa couleur. D, tous colorés, même encore inutilisés.

Le socle écrit un réglage synchronisé comme un objet de genre `settings` (`value`), relu avant d'écrire comme les autres. Sonde du 04/10/2026 sur le compte de test. La création avec la version 0 et la modification à version périmée (412) se comportent comme prévu, mais zotero.org refuse une liste vide (on supprime alors le réglage) et ne refuse pas une suppression à version périmée, si bien que la relecture du socle reste le seul contrôle avant de supprimer. Un réglage déjà absent ne demande rien.

### D176. Fiches laissées hors du fonds par décision

Constat, à une répétition du pilote. Les fiches que l'utilisateur avait vues et décidé de laisser hors du fonds (titres trop vagues pour les ranger) revenaient à chaque fois dans `zc fonds a-ranger`, `zc inbox preparer` et le contrôle 12 de l'audit, où elles comptaient comme points nouveaux. Rien ne les distinguait d'une fiche jamais vue, comme les fiches laissées en place avant D124. Options. A, une action « laisser » dans `rangement.toml`, que `planifier` ignorerait. Le fichier mêlerait alors décisions d'écriture et simples notes, et l'entrée ne dirait pas quand la fiche a changé depuis. B, sur le modèle de D124, `zc fonds a-ranger --laisser CLE…` note ces fiches dans `suivi/rangement-laissees.json`, avec la date et les clés de leurs collections. Décision B, proposée à la construction, confirmée par l'utilisateur le 05/10/2026. Une fiche notée ne revient plus dans ces trois endroits tant que ses collections restent les mêmes. Elle reste comptée (« N laissées hors du fonds par décision » dans le rapport de `a-ranger`, le tri, le plan de rangement et le contrôle 12), sans être un point de l'audit. Si ses collections changent, y compris par une collection que le plan de rangement met à la corbeille, elle redevient une fiche sans place. La commande refuse une fiche de l'Inbox (qui se trie toujours), une fiche qui a déjà sa place dans le fonds, et une fiche qui a une décision en attente ou acceptée dans `rangement.toml`.

### D177. Décisions de toutes les étapes par commande

Prolonge D172. Constat. À la répétition du pilote, les fichiers de `suivi/` autres que celui des métadonnées s'éditaient encore à la main. En éditant `suivi/tags.toml`, l'agent a remplacé une ligne de commentaire de l'en-tête (« # [automatiques] retire… ») au lieu de la vraie section `[automatiques]`, et ne l'a vu que parce que le plan ne retirait rien. Décision, sur le modèle de D172 (mêmes verbes, mêmes messages, seuls les cas qui attendent changent, refus clair d'un nom ou d'une clé inconnus, fichier réécrit par les fonctions de l'étape, avec son en-tête et les commentaires de chaque entrée). `zc tags accepter` et `refuser` (noms des `[[tag]]`, `--variantes`, `--regle-automatiques`, `--regle-importes`, `--evidents` et `--sauf`, `--sort` et `--cible` pour changer une proposition, qui passe alors en source « agent »), et `zc tags ajouter` pour un tag sans entrée (tag hors familles signalé par le tri, traduction, tag protégé avec `--utilisateur`). `zc doublons accepter` (fusionner, `--surs`, `--sauf`, `--conserver`) et `refuser` (distinct, `--raison`), chaque groupe désigné par la clé de l'une de ses fiches. `zc pieces accepter` (`--corbeille`, `--rattacher COPIE=FICHE`) et `refuser` (garder), avec les garde-fous du plan (copie annotée jamais à la corbeille, une copie gardée au moins). `zc cles decider FICHE=garder|écarter|natif|extra`, le vocabulaire des clés ne se ramenant pas à accepter et refuser. Restent à la main une décision déjà prise, `forcer` des doublons et un groupe de doublons que `zc` n'a pas repéré. Précisions faites à la construction. Le résumé de la règle globale, écrit en commentaire sous `[automatiques]` et `[importes]`, est relu pour survivre à la réécriture. Un cas d'Extra décidé reste dans `suivi/cles.toml` jusqu'à son règlement dans Zotero, au lieu d'en disparaître dès le plan suivant, ce qui perdait la décision si le plan n'était pas appliqué. `suivi/rangement.toml` et `suivi/fonds.toml` ne sont pas concernés.

## Audits du 05/10/2026

Deux audits indépendants, en lecture seule, sur la bibliothèque synthétique des tests et le faux serveur, ont cherché ce qui peut abîmer une bibliothèque, divulguer des données, tromper l'utilisateur ou l'agent, ou casser chez quelqu'un d'autre que l'auteur. Leurs constats se recoupent en partie. Les corrections suivent, par lots, en commençant par la fiabilité du journal.

### D178. Écriture faite dont la réponse se perd

Constat. Quand zotero.org fait une écriture mais que sa réponse se perd (connexion coupée), `_requete` renvoie la requête, qui reçoit un 412. La relecture trouve alors les valeurs déjà écrites, le groupe passe pour fait, et rien n'est journalisé, si bien que `zc annuler` n'a rien à défaire. Même chose pour une collection créée, et pour une commande interrompue entre l'écriture et le journal. Options. A, inscrire chaque écriture au journal avant de l'envoyer (ligne `intention`, avec l'objet relu et les champs à écrire), puis la confirmer par la ligne `element` habituelle. Une intention restée sans confirmation devient une écriture journalisée dès qu'une relecture du même plan (nouvel essai après le 412, reprise) trouve les valeurs écrites. B, ne plus renvoyer une écriture après une coupure et journaliser ce que la relecture trouve déjà fait. Décision A, choisie par l'utilisateur, puisqu'elle couvre aussi l'interruption. Précisions faites à la construction. Seule une valeur qu'une intention de ce plan attendait est attribuée à `zc`, jamais une valeur déjà conforme sans intention. `zc annuler` défait aussi les intentions restées sans confirmation, sans risque puisque l'annulation est partielle (D39) et ne touche qu'un champ resté à la valeur écrite, et son rapport le dit. Une collection à créer qui n'existe pas est alors ignorée. Le nouvel essai après un 412 vaut désormais aussi pour une création de collection. Les anciens journaux, sans intention, se lisent comme avant.

### D179. Essai relancé

Constat. `zc appliquer <plan> --essai` appliquait les cinq premiers groupes encore à faire, sans contrôle de sauvegarde. Relancé, il prenait les cinq suivants, si bien que quelques essais de suite appliquaient tout un plan de masse sans sauvegarde ni `--tout`, contre D15 et D42. Les skills disant de relancer telle quelle une commande interrompue, la dérive était à portée d'un agent de bonne foi. Options. A, l'essai porte toujours sur les premiers groupes du plan, et un `--essai` relancé ne reprend que ceux de ces groupes qui restent à faire (interruption, conflit corrigé depuis). B, refuser tout second essai. Décision A, choisie par l'utilisateur, puisqu'elle garde la reprise d'un essai interrompu. Un essai relancé alors que ses groupes sont faits ne fait rien et renvoie vers `--tout`, qui garde ses contrôles. Les petits plans et le petit tri de l'Inbox (D136, D138) ne changent pas.

### D180. Journaux annulés dans l'empreinte

Constat. L'empreinte d'un plan ne portait que sur ses groupes, alors que `annule`, la liste des journaux qu'un plan d'annulation défait, sert à savoir quels groupes restent faits (D47). Appliquer un plan, l'annuler, le réappliquer puis l'annuler de nouveau donnait un second plan d'annulation identique au premier, de même empreinte. `zc appliquer` le trouvait déjà fait et répondait « Rien à appliquer », alors que rien n'était défait. Un plan dont on changeait `annule` à la main était aussi accepté. Décision, choisie par l'utilisateur. L'empreinte porte aussi sur `annule` quand la liste n'est pas vide, dans un format de plan 2. Les autres plans gardent la même empreinte, la description et la date de création restant hors de l'empreinte pour qu'un plan recalculé à l'identique la garde (D47). Options pour les plans d'annulation déjà écrits. A, le format 1 reste lu avec l'ancien calcul. B, ils sont déclarés périmés et à regénérer. Décision A.

### D181. Groupe arrêté après une partie de ses écritures

Constat. Dans un groupe à plusieurs rangs (une fusion, par exemple), un rang écrit puis un rang en conflit laissaient le groupe à moitié fait, ce que D46 admet. Mais `zc appliquer` le classait sous « Conflits, laissés intacts », l'excluait des fiches à vérifier, et le skill des doublons disait ces groupes intacts. Décision, choisie par l'utilisateur. Un groupe en conflit ou en erreur après une partie de ses écritures s'affiche à part, sous « Arrêtés après une partie des écritures, à vérifier », avec les clés écrites, que la ligne « Vérifier : zc voir » reprend. Le journal garde son statut (conflit ou erreur, refait par une reprise), avec les clés écrites dans le détail. Le skill des doublons dit de vérifier ces groupes, puis de régler le conflit et relancer, ou de défaire avec `zc annuler`.

### D182. Mise à la corbeille après un ajout

Constat. Le plan des PDF identiques et la fusion des doublons ne mettent à la corbeille qu'une copie sans annotation ni note, contrôlée au moment du plan (D51, D125). L'opération ne portait ensuite que sur `deleted`, si bien qu'une annotation ajoutée entre le plan et `zc appliquer` partait à la corbeille avec sa copie, sans conflit. De même pour une note ajoutée à une fiche absorbée, ou à une fiche que le rangement met à la corbeille. Options. A, chaque opération de mise à la corbeille porte la liste des enfants connus au plan (pièces jointes et notes d'une fiche, annotations d'une pièce jointe), et le socle relit les enfants juste avant d'écrire. Un enfant hors corbeille que le plan ne connaissait pas arrête le groupe en conflit, l'élément reste en place. B, refuser toute mise à la corbeille d'un élément qui a encore des enfants. Décision A, choisie par l'utilisateur, puisque B bloquerait une fusion normale dont les pièces jointes sont rattachées au rang précédent. Précisions faites à la construction. Le contrôle vit dans le socle (`enfants` de l'opération), rempli par les doublons, les PDF identiques et le rangement. Une annotation sur un PDF d'une fiche mise à la corbeille par le rangement n'est pas relue, la fiche ayant été jugée avec ses pièces jointes. Les plans écrits avant, sans liste, ne sont pas contrôlés. Il reste l'instant entre la relecture et l'écriture, qu'une condition de version de la bibliothèque fermerait au prix d'un 412 pour tout changement ailleurs. À vérifier sur le compte de test, que `/items/<clé>/children` d'une pièce jointe rend bien ses annotations.

### D183. Annulation d'une collection créée puis reprise

Constat. L'annulation d'une collection créée par une passe ne vérifiait que `deleted`. Renommée, remplie ou dotée de sous-collections par l'utilisateur depuis la passe, elle partait quand même à la corbeille, contre D39. Options. A, juste avant de la mettre à la corbeille, le socle vérifie qu'elle a gardé le nom et le parent de sa création et qu'elle ne contient plus aucune fiche ni sous-collection hors corbeille, une fois défait le reste de la passe (les groupes sont rejoués du dernier au premier). Sinon elle reste en place et le groupe est signalé, même dans un plan d'annulation partiel. B, signaler sans bloquer. Décision A, choisie par l'utilisateur. Le même mécanisme qu'en D182 (`enfants` vide), avec les champs exigés (`exige`).

### D184. Suppression d'un réglage synchronisé

Constat. zotero.org accepte la suppression d'un réglage (retour à l'absence de `tagColors`) même à version périmée (D175), et le faux serveur des tests la refusait, ce qui donnait aux tests une protection que le serveur n'a pas. Options. A, garder la relecture du socle juste avant la suppression, aligner le faux serveur sur la sonde de D175, et accepter le risque restant, très faible et limité à la palette des tags. B, ne jamais supprimer un réglage automatiquement et demander à l'utilisateur de retirer les couleurs dans Zotero. Décision A, choisie par l'utilisateur.

### D185. Copie de la base pendant que Zotero écrit

Constat. La lecture copie `zotero.sqlite` puis son journal `-wal`, l'un après l'autre. Si Zotero range le journal dans la base entre les deux copies, la copie s'ouvre sans erreur mais perd les derniers changements, contre la lecture cohérente de D12. Options. A, noter la taille et la date des deux fichiers avant la copie, et la refaire s'ils ont changé à la fin, jusqu'à trois fois à une seconde d'écart, puis refuser en demandant d'attendre la fin de la synchronisation. B, la fonction de sauvegarde de SQLite, qui échouerait pendant que Zotero, ouvert, verrouille sa base. Décision A, choisie par l'utilisateur. La sauvegarde (`zc sauvegarder`, Zotero fermé) passe par la même copie.

### D186. Ce que la corbeille cache

Constat. La lecture écartait les éléments et collections de la corbeille, mais pas ce que Zotero cache avec eux. Une sous-collection dont la collection parente est à la corbeille gardait un parent inconnu, et presque toutes les commandes s'arrêtaient sur une erreur. Les pièces jointes et notes d'une fiche à la corbeille restaient comptées, et le rattrapage de D171 en faisait des pièces jointes isolées. Options. A, traiter partout comme à la corbeille les pièces jointes et notes d'une fiche à la corbeille, les annotations d'une pièce jointe à la corbeille et les sous-collections d'une collection à la corbeille, à la lecture de la copie locale comme au rattrapage par zotero.org. B, seulement éviter l'arrêt, en plaçant ces sous-collections à la racine. Décision A, choisie par l'utilisateur, puisqu'elle suit ce que montre Zotero. Leurs tags comptent avec ceux de la corbeille (D156), et les comptes de l'audit changent un peu.

### D187. Rattrapage complet et d'une seule version

Constat. Le rattrapage de D171 ne reprenait pas les réglages ni les recherches enregistrées supprimés sur le serveur, ignorait une annotation passée d'un PDF à un autre, et gardait la version de la première page sans comparer celle des suivantes. Une bibliothèque modifiée pendant la lecture pouvait mêler deux états. Décision, technique et annoncée à l'utilisateur. Le rattrapage lit aussi les recherches enregistrées et les suppressions de réglages et de recherches, suit le nouveau PDF d'une annotation, et vérifie que toutes ses réponses portent la même version de la bibliothèque. Sinon il recommence, jusqu'à cinq fois, comme le demande la documentation de synchronisation de Zotero.

### D188. Descendance d'une fiche confidentielle

Constat. Le masque de D126 couvrait une fiche exclue, ses pièces jointes et ses notes, mais pas les annotations de ses PDF. `zc voir --tag` montrait une annotation avec le titre de sa fiche confidentielle, et classait son tag comme public. Une pièce jointe exclue sous une fiche publique livrait son nom et son texte dans `zc voir`. Le rapport du tri de l'Inbox montrait aussi une clé de citation partagée avec une fiche confidentielle, le masque calculé pour ce cas venant après un `return`. Décision, sans option, puisque c'est la promesse de D126. Le masque couvre toute la descendance d'un élément exclu (pièces jointes, notes, annotations), qu'il s'agisse d'une fiche ou d'une seule pièce jointe ou note, `zc voir` n'en montre que la clé, et le tri de l'Inbox masque le groupe qui partage une clé de citation avec une fiche confidentielle.

### D189. Adresse de contact

Constat. L'adresse de `[sources] contact` partait dans l'en-tête de toutes les requêtes, BnF, Sudoc, Open Library et doi.org compris, alors que `zc init`, `config.toml` et l'`AGENTS.md` livré la disent transmise seulement à Crossref et OpenAlex. Décision, sans option. Elle ne part plus qu'à ces deux services, les autres reçoivent l'en-tête de `zc` sans adresse.

### D190. Forme des tags d'exclusion

Constat. Les tags de `tags_exclus` se comparaient à l'identique, si bien que `_Privé`, ou `_privé` saisi sous une autre forme Unicode, ne protégeait rien, sans avertissement. Options. A, comparer sans tenir compte des majuscules ni de la forme Unicode. B, garder la comparaison exacte et l'écrire dans le guide. Décision A, choisie par l'utilisateur. Vaut aussi pour la règle qui interdit de prendre un tag d'exclusion pour cible et qui ne le change jamais (D151).

### D191. Texte des notes

Constat. La fusion des doublons recopiait les 40 premiers caractères d'une note rattachée dans la nature de l'opération, donc dans le rapport et le plan, et le rapport d'annulation en montrait 70, alors que `zc voir` promet de ne jamais montrer le texte des notes. Le réglage `exclure_notes` de D66 n'était lu nulle part. Options. A, le texte d'une note ne sort plus du journal, les rapports disent « la note », et `exclure_notes` devient sans effet, encore accepté dans `config.toml` pour ne pas refuser une configuration existante. B, garder ces extraits et faire respecter `exclure_notes`. Décision A, choisie par l'utilisateur.

### D192. Plans et journaux, données du moteur

Constat. Les plans (`plans/*.json`), le journal et certains champs du suivi gardent les valeurs complètes des fiches confidentielles, dont l'exécution et l'annulation ont besoin. D126 masque le titre du groupe dans le plan, mais aucune consigne ne disait à l'agent de ne pas ouvrir ces fichiers. Options. A, une règle dans l'`AGENTS.md` livré et le guide. L'agent n'ouvre jamais les plans, les journaux ni `.env`, et tout ce qu'il lui faut est dans les rapports `.md`, `zc journal` et `zc voir`. B, en plus de A, séparer les valeurs confidentielles du plan dans un fichier à part, au prix d'un nouveau format. Décision A, choisie par l'utilisateur, B restant à faire si un vrai parcours montre que la consigne ne suffit pas. Reste à examiner dans un parcours réel, les champs des propositions de métadonnées d'une fiche confidentielle trouvée par son DOI, écrits en clair dans `suivi/metadonnees.toml`, que l'agent lit.

### D193. Ce qui casse chez les autres

Constats. Sous Windows, une sortie redirigée vers un tube, celle que lit un agent, s'écrit dans le jeu de caractères de la machine (cp1252 en Europe de l'Ouest), et un titre grec, polonais ou une flèche arrêtait `zc voir` sur une erreur Python. Windows PowerShell 5.1 ne développe pas `~` pour un programme, alors que le guide fait taper `zc init ~/Zotero-travail`. Sous Linux, selon l'installation, le processus de Zotero s'appelle `zotero-bin`, et `zc sauvegarder` aurait copié une base ouverte. `pyzotero` n'avait pas de borne, alors que `ecriture.py` s'appuie sur son client HTTP, et `httpx2` était importé sans être déclaré, si bien qu'une nouvelle version aurait cassé `zc` chez un nouvel utilisateur seulement. Décisions, techniques et annoncées à l'utilisateur. La sortie et la sortie d'erreur passent en UTF-8 quand elles ne le sont pas. Tout argument de chemin développe `~`. `zc sauvegarder` cherche `zotero` et `zotero-bin`. `pyzotero>=1.15.2,<1.16` et `httpx2>=2.13.1,<3`, à élargir après essai d'une nouvelle version. Restent à vérifier sur de vrais systèmes l'installation neuve depuis le dépôt public, le profil de Zotero installé par Snap et la copie d'une base de plus de 1 Gio sous Windows, Zotero ouvert.

### D194. Commentaires des fichiers de suivi

Constat. Les fichiers de `suivi/` recopient en commentaire des titres, noms de collections et de tags venus de Zotero. Un titre sur deux lignes, ce que permettent certains imports, faisait de sa seconde ligne une instruction TOML, et le fichier devenait illisible pour toute commande, avec un message incompréhensible. Un titre fabriqué pouvait même y glisser une décision. Décision, technique. Une seule fonction écrit tous les fichiers de suivi. Dans un commentaire, la suite d'un saut de ligne qui n'est pas elle-même un commentaire rejoint la ligne, et les caractères de contrôle, refusés par TOML, deviennent des espaces. Le texte est relu comme TOML avant de remplacer l'ancien fichier d'un coup.

### D195. Détails personnels dans le dépôt public

Constat. `outils/publier.sh` publie tous les fichiers suivis de l'atelier, et `docs/decisions.md` comme l'`AGENTS.md` de développement gardaient des détails que ce même `AGENTS.md` interdit (taille d'une bibliothèque personnelle, calendrier de ses passes, réglage d'une machine, exemples tirés de cette bibliothèque). Options pour le contenu. A, réécrire ces passages en termes généraux dans l'atelier, les constats restant attribués à « une vraie bibliothèque », sans date, chiffre ni exemple réel. B, ne plus publier ces deux fichiers. C, les laisser. Décision A, choisie par l'utilisateur. Options pour les versions déjà publiées. A, les laisser. B, remplacer l'historique du dépôt public par un seul commit. Décision B, choisie par l'utilisateur. Un clone fait avant ce remplacement garde l'ancien contenu.

### D196. Noms de tags sous plusieurs formes Unicode

Constat. Un tag peut être stocké sous deux formes Unicode qui s'affichent pareil, « é » composé (NFC) ou « e » suivi d'un accent combinant (NFD). `zc tags accepter` et `zc tags refuser` comparaient les noms sous la seule forme NFC, si bien que juger l'une de deux entrées de même nom affiché jugeait aussi l'autre. `zc tags ajouter` enregistrait le nom tel que l'agent l'avait tapé, et pour un tag stocké sous une autre forme, la règle ne s'appliquait à rien. Décision, technique. Un nom désigne d'abord l'entrée ou le groupe qui porte ce nom exact. La forme NFC ne sert qu'à défaut, et seulement si elle ne désigne qu'une entrée ou un seul groupe. Sinon la commande refuse et liste les formes concernées avec leurs points de code, puisqu'elles ne se distinguent pas à l'écran. `zc tags ajouter` enregistre le nom réellement porté dans la bibliothèque (l'identifiant pour un tag confidentiel) et refuse un nom qui en désigne plusieurs. `--sauf` continue d'écarter toutes les formes d'un nom, puisque trop écarter ne fait que laisser à juger.

### D197. Fichiers absents retenus d'un audit à l'autre

Constat. Pour chaque pièce jointe importée dont le fichier manque, `zc audit` demandait à zotero.org si le fichier y était stocké (D133), à chaque audit et sans rien retenir, à raison d'environ 0,2 seconde par fichier. `zc noms planifier` faisait de même. Avec le réglage « Télécharger les fichiers au besoin », une bibliothèque de 5 000 PDF non téléchargés aurait demandé plus d'un quart d'heure par audit. Décision, technique. Un fichier trouvé sur zotero.org est retenu dans `cache/zotero/fichiers_en_ligne.json`, avec la version de sa pièce jointe (`items.version`, ajoutée au contrôle du schéma, ou celle de zotero.org quand la copie locale est en retard, D171). Il n'est plus demandé tant que cette version ne change pas, puisque l'envoi d'un nouveau fichier la change. Un fichier introuvable est redemandé à chaque fois, puisqu'il peut arriver d'un autre ordinateur avant que Zotero ne reçoive la nouvelle version. Une pièce jointe jamais synchronisée n'est pas retenue. La mémoire est enregistrée tous les 50 fichiers et quand zotero.org devient injoignable, hors de `cache/*.json` que `--rafraichir` vide. Limite acceptée, un fichier retiré de zotero.org sans que sa pièce jointe change de version reste noté « sur zotero.org » jusqu'à la modification suivante de cette pièce jointe.

### D198. Une seule copie de la base par commande

Constat. `lecture.lire`, `lecture.lire_types` et `lecture.etat_synchronisation` copiaient chacune `zotero.sqlite` en entier, si bien que `zc inbox planifier` ou `zc metadonnees types` copiaient trois ou quatre fois une base qui peut peser 1 à 2 Go. Décision, technique. La ligne de commande ouvre autour de chaque commande un bloc `lecture.partager()`, dans lequel ces lectures se partagent une copie, effacée à la fin. Avant chaque lecture, la taille et la date de la base et de son journal sont comparées à celles de la copie, et la copie est refaite, avec le contrôle de D185, si Zotero y a écrit depuis. Hors de ce bloc, chaque lecture fait sa copie comme avant. La sauvegarde garde sa propre copie.

### D199. Fiche qui entre dans plusieurs collections créées

Constat. Dans le plan de rangement, l'opération d'une fiche était rangée dans le groupe de la première collection où elle entre. Si elle entrait aussi dans une collection créée par un groupe plus loin, l'essai ou un paquet précédent l'écrivait vers une collection qui n'existait pas encore, et le groupe finissait en erreur. Décision, technique. La fiche va dans le groupe de la dernière collection créée par le plan qu'elle vise, si celle-ci vient après la première où elle entre. Son écriture ne précède ainsi jamais une création.

### D200. Sauvegardes conservées et sauvegarde récente

Constat. Avec `conserver = 0`, la sauvegarde qu'on venait de faire était aussitôt supprimée. Et `sauvegarde.recente` comptait n'importe quelle sauvegarde du dossier, même celle d'une autre bibliothèque quand deux configurations partagent `[sauvegarde] dossier`, ou après un changement de `[zotero] dossier`. Décision, technique. `config.toml` refuse `conserver` inférieur à 1, et `zc sauvegarder` ne descend jamais sous une sauvegarde gardée. Une sauvegarde d'un autre dossier Zotero ne compte plus comme récente, un ancien descriptif sans ce champ restant accepté.

### D201. Reconnaître le dossier de travail

Constat. `config.charger` remontait jusqu'au premier `config.toml` venu, même celui d'un autre logiciel. Hors d'un dossier de travail, il partait du dossier courant avec les réglages par défaut, et `zc audit` y créait `rapports/` et `suivi/`. Décision, technique. En remontant, seul compte un `config.toml` lisible qui a une section `[zotero]`, que `zc init` a toujours écrite. Sans dossier de travail trouvé, ou avec un `--dossier` sans `config.toml`, la commande est refusée avec un message qui dit quoi faire. Un `config.toml` illisible donne un message au lieu d'une trace.

### D202. Petites corrections de l'audit

Décisions, techniques. `--rafraichir` vide le cache des réponses des sources, mais garde le compte des recherches du jour d'OpenAlex, qu'il remettait à zéro. `zc init` transforme tout incident réseau pendant la vérification de la clé (délai dépassé, connexion coupée, réponse tronquée) en message « Zotero injoignable », au lieu d'une trace Python. Les messages courants d'argparse sont traduits, pluriels compris, sans dépendance nouvelle. Le README et le guide limitent « une valeur déjà présente n'est jamais remplacée » à `zc metadonnees completer`, et disent ce que changent un DOI inexistant (D128), un changement de type et une fusion (clé de citation).

### D203. Clé d'un autre compte que celui que Zotero synchronise

Constat. `zc init` enregistre le compte de la clé API, et `zc appliquer` vérifiait seulement que le plan vise ce compte. Rien ne comparait la clé au compte que la base locale de Zotero synchronise. Un chercheur qui a deux comptes, par exemple un personnel et un institutionnel, peut créer sa clé sur l'autre. Les plans sont alors construits sur la base de son ordinateur, mais les écritures visent l'autre bibliothèque, et `lire_a_jour` (D171) peut même y mêler les changements de celle-ci. Zotero retient le compte synchronisé dans la table `settings` (`setting = 'account'`, `key = 'userID'`) dès la première synchronisation, et refuse ensuite d'en synchroniser un autre sans vider ses données (`users.js` et `syncLocal.js` du code de Zotero). Cette valeur désigne donc sûrement la bibliothèque de la base. Options. A, refuser tant que la clé ne correspond pas au compte synchronisé. B, avertir seulement. Décision A, choisie par l'utilisateur. Un seul contrôle, `appliquer.controler_compte`, local et sans requête, est appelé avant toute écriture par `zc appliquer`, avant toute requête par `lire_a_jour` (toutes les planifications et les commandes qui complètent la copie locale par zotero.org), ainsi que par le tri de l'Inbox, `zc annuler`, `zc init` et `zc audit`. Une base jamais synchronisée est refusée aussi, avec la marche à suivre dans Zotero, et `zc init` ne demande pas de clé tant que la base n'a pas de compte. Avec une clé qui ne correspond pas, `zc audit` refuse, puisque c'est la première commande d'une séance et qu'il chercherait les fichiers absents dans une autre bibliothèque. `zc audit --hors-ligne` donne en attendant l'audit de la copie locale, avec un avertissement. Sans clé, l'audit reste possible et signale au point 11 une bibliothèque jamais synchronisée. Reste à vérifier sur le compte de test la valeur réelle de `account/userID` et le message de refus.

### D204. Doublons sûrs

Constat. Un groupe de même type qui partageait un DOI était classé « sûr » quels que soient ses titres. Deux chapitres importés avec le DOI de l'ouvrage, ou un article et son erratum saisis avec le même DOI, étaient alors présentés en bloc par le skill, et `zc doublons planifier --surs` les fusionnait sans décision, contre D49. Options. A, ne classer « sûr » un groupe de même DOI que si ses titres concordent, et retirer `--surs` de `planifier`. B, seulement exiger des titres concordants. C, ne rien changer. Décision A, choisie par l'utilisateur. Les titres se comparent avec `sources.titres_concordants`, au seuil 0,9 des correspondances évidentes de l'étape 3, puisqu'à 0,8 un « Erratum to » suivi du titre passerait encore. Sinon le groupe est à juger. `zc doublons planifier` ne prend plus que les groupes décidés, et les groupes sûrs s'acceptent par `zc doublons accepter --surs`. Un ancien `suivi/doublons.toml` garde l'ancienne classe tant que `zc doublons chercher` n'a pas été relancé.

### D205. Fusion comme Zotero

Constat. La fusion ne reprenait des fiches absorbées que `dc:replaces`. Les liens « Connexe » restaient sur l'absorbée, à la corbeille, et les fiches liées pointaient encore vers elle. Une copie identique de PDF dont la pièce jointe portait une note partait aussi à la corbeille, alors que D51 exclut une copie avec note. La fusion de Zotero (`moveRelations` dans `mergeItems.mjs`, qui remplace `Zotero.Items.merge`) reporte toutes les relations de l'absorbée sur la fiche gardée sauf un lien vers soi, retire les `dc:replaces` de l'absorbée et fait pointer vers la fiche gardée les fiches qui pointaient vers l'absorbée. Options. A, faire de même. B, seulement la note de pièce jointe, et signaler les liens dans le rapport. Décision A, choisie par l'utilisateur. Chaque fiche liée hors du groupe reçoit, au rang 1, une opération sur ses `relations` avec avant et après, que le socle contrôle et que `zc annuler` défait. Les groupes d'un même plan s'enchaînent comme des fusions successives. Une fiche liée confidentielle n'apparaît que par sa clé. Comme Zotero, `zc` ne crée aucun lien d'une fiche vers elle-même et laisse le lien que la fiche gardée avait vers l'absorbée, et il écarte en plus les liens vers une autre absorbée du même groupe. Les fiches liées se trouvent par les liens de l'absorbée (Zotero pose « Connexe » des deux côtés) et par ceux déjà prévus par le plan, si bien qu'un lien à sens unique vers l'absorbée reste en place. Une copie identique dont la pièce jointe porte une note est rattachée comme une copie annotée, sans recopier la note (D191). Pour les PDF identiques, Zotero déplace annotations et note sur la copie gardée, alors que `zc` garde la règle de D51 et rattache la copie. Restent à vérifier sur le compte de test l'écriture de `relations` (remplacement de tout l'objet) et l'affichage de « Connexe » après synchronisation.

### D206. Note propre d'une pièce jointe

Constat, signalé pendant D205 et vérifié dans le code de Zotero (`_saveData` de `item.js`). Zotero range la note propre d'une pièce jointe dans la table `itemNotes`, comme une note, mais sans parent. La lecture prenait donc chaque pièce jointe ainsi enregistrée pour une note isolée. Les comptes de l'audit et du contrôle étaient faussés, et la note d'une copie de PDF n'était jamais vue, si bien que `zc pieces` pouvait mettre à la corbeille une copie identique qui portait une note, contre D125. Décision, technique. La lecture ne range dans les notes que les éléments de type note, et retient pour chaque pièce jointe si elle porte une note non vide (Zotero enveloppe toute note, même vide, dans un `<div>`). Le rattrapage de D171 fait de même avec le champ `note` de l'API. Une copie dont la pièce jointe porte une note n'est jamais mise à la corbeille, par `zc pieces` comme par la fusion.

### D207. Minuteur dans le terminal

Constat de l'utilisateur, au premier audit de la version 0.3.1. Rien ne s'affiche pendant qu'une commande lit la bibliothèque, si bien qu'on ne sait pas si elle tourne. Décision, demandée par l'utilisateur. Sous un terminal, « zc audit en cours… 12 s » s'affiche dès le lancement sur la sortie d'erreur et se met à jour chaque seconde. Les messages de la commande effacent d'abord cette ligne, que le minuteur redessine ensuite. À la fin, une commande qui a duré au moins deux secondes affiche « zc audit terminé en 14 s. ». Rien ne change quand la sortie n'est pas un terminal, pour ne pas charger ce que lit un agent, ni pour `zc init`, qui pose des questions.

## Questions ouvertes

- Disponibilité du nom `zot-clean` sur PyPI au moment de publier (D8).
- Couverture réelle de l'API locale de Zotero, si elle devient une seconde source de lecture (D12).
