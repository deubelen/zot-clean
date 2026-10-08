# Passage de zot-clean à l'anglais

Plan de travail du 06/10/2026, qui remplace la première proposition d'un autre agent (gardée dans l'historique de l'atelier, commit `5531848`). Les arbitrages sont tranchés par D208 à D218. Livraison en version 0.4.0.

## Ce qui change

- Le code, les commentaires, les tests, les commandes et les options passent à l'anglais (D208). Les anciennes commandes sont refusées avec leur équivalent (D213). Le fonds devient `Subjects` dans le profil anglais et la commande `zc subjects` (D211, D217).
- Chaque bibliothèque est déclarée française ou anglaise à `zc init`. Ce choix fixe les conventions proposées (noms de classement, définitions), la langue des rapports (D210) et celle des messages (D215). Il ne touche jamais aux données bibliographiques. Un dossier existant sans langue déclarée est français (D214).
- Les skills et le `AGENTS.md` livré n'existent qu'en anglais. Le guide et la méthode existent en deux versions, et `zc init` copie celle de la langue choisie (D216). L'agent parle la langue de l'utilisateur.

## Ce qui ne change pas

- Le format des fichiers du dossier de travail (D209). Plans, journaux, suivi, validation du fonds et `config.toml` gardent leurs clés, leurs valeurs (« supprimer », « garder »…) et leurs chemins. Ces clés françaises deviennent un protocole figé, que la sérialisation traduit explicitement depuis les noms anglais du code.
- Les mots relus dans les fichiers écrits par l'utilisateur ou par `zc`, à savoir `Inclut` et `Exclut` dans `plan.md`, et `tag « … »` dans les notes de rangement. Le profil anglais accepte en plus `Includes` et `Excludes`.
- Les garde-fous (essai, sauvegarde, synchronisation, compte, journal, reprise, annulation), la confidentialité (`_privé` reste l'exclusion d'une bibliothèque française) et le nom attendu des PDF, qui suit toujours les réglages de Zotero.
- L'historique de `docs/decisions.md`, qui reste en français. Les décisions s'écrivent en anglais une fois la migration livrée (D212).

## Déroulé

### Phase 0, le filet de sécurité

Avant tout renommage, figer ce que la version 0.3.2 écrit sur disque.

1. Fixtures dorées dans `tests/donnees/v032/`, produites par la 0.3.2 sur la bibliothèque synthétique. Elles comprennent un plan de chaque étape au format 1 et au format 2, un plan d'annulation, des journaux (essai seul, groupe partiel, intention non confirmée, fin), chaque fichier de `suivi/`, une validation du fonds et une configuration minimale. Chaque fixture est accompagnée de ce qu'on doit en tirer, c'est-à-dire l'empreinte, les groupes faits, les intentions en suspens et la configuration effective.
2. Une empreinte indépendante des noms Python. `Plan.empreinte` est aujourd'hui calculée sur `asdict` (`plans.py:96`), si bien que renommer un champ invaliderait tous les plans. Elle sera calculée sur la représentation stockée, produite par une table explicite des champs. Même chose pour `config.py`, qui déduit les clés autorisées des champs des classes (`_section`).
3. Un test par mot relu (`Inclut`, `Exclut`, `tag « … »`, sorts des tags et du fonds, statuts du journal), pour que la traduction d'un texte affiché ne puisse pas changer un traitement.
4. Le registre des commandes, c'est-à-dire chaque commande, sous-commande, option et valeur, avec son ancien nom. Il sert au refus des anciens noms (D213) et au contrôle des commandes citées dans les documents. Les noms anglais sont fixés par D219, dans `src/zot_clean/registre.py`.

Porte de sortie. Suite verte, et les fixtures lues par le code actuel donnent exactement les résultats attendus.

### Phase 1, le code en anglais

Un seul agent renomme d'un bloc les modules, classes, fonctions, variables, commentaires et tests. Les textes affichés restent tels quels à ce stade. Faire ce travail d'un seul tenant évite les adaptateurs transitoires et les conflits d'imports qu'un découpage par module entraînerait.

Porte de sortie. Suite verte, fixtures dorées inchangées à l'octet près et lues avec les mêmes résultats, aucun appel à `Client.ecrire` déplacé hors du socle.

### Phase 2, les textes visibles, en parallèle

Les textes bilingues s'écrivent à côté du code qui les emploie, sous la forme `L(en='…', fr='…')`, résolue d'après la langue de la bibliothèque. Aucun fichier de catalogue n'est partagé, si bien que trois agents peuvent travailler dans des worktrees séparés, chacun sur une liste exclusive de fichiers.

- Lot A. `cli.py`, `init.py`, `config.py`. Commandes anglaises d'après le registre, refus des anciens noms, retrait de la traduction globale d'argparse (`cli.py:54`), `zc init --library-language fr|en` (question posée sous un terminal, refus sans terminal), `zc config show` en lecture seule, `modeles/` renommé `templates/`.
- Lot B. Rapports et messages de l'audit, du contrôle, des doublons, des PDF identiques, des métadonnées, de l'Inbox et de `voir`.
- Lot C. Rapports et messages du fonds, du rangement, des tags, des clés, des noms, du socle d'application et de la sauvegarde. Il couvre aussi les en-têtes des fichiers de `suivi/`.

Je garde l'intégration, `tests/conftest.py`, la version et la CI. Les lots s'intègrent l'un après l'autre.

Porte de sortie. Suite verte, fixtures inchangées, chaque message testé dans les deux langues sur au moins un cas par module.

### Phase 3, profils et documents

- Profils de méthode `fr` et `en` dans `config.py`. Ils partagent les mêmes rôles, couleurs, seuils et protections, seuls les noms changent (`Projets` et `Projects`, `Fonds` et `Subjects`, `1 à lire` et `1 to read`, `_privé` et `_private`…). Un nouveau dossier écrit ses conventions en entier dans `config.toml`, au lieu de dépendre des défauts.
- Skills et `AGENTS.md` livré en anglais. Ils demandent à l'agent de lire la langue par `zc config show` et de parler celle de l'utilisateur.
- Guide et méthode en deux versions. README en anglais, avec un lien vers le guide français.
- `zc init --update` retire les skills livrés sous un ancien nom (`doublons` devenu `duplicates`, etc.), pour qu'aucun jeu périmé ne reste actif. Le `AGENTS.md` livré interdit déjà de les modifier à la main.
- Contrôle automatique des commandes citées dans les skills, le guide, la méthode, les rapports et l'aide, par le registre.

### Phase 4, vérification et livraison

1. CI sur les trois systèmes, puis installation propre depuis la wheel et depuis l'archive Git, hors de l'atelier.
2. Mise à jour d'une copie synthétique d'un dossier 0.3.2 contenant un essai en cours. On vérifie que `zc apply --all` reprend le plan français et que `zc undo` l'annule.
3. Pilote par un agent sans contexte, sur la bibliothèque synthétique, dans les quatre combinaisons de langue de conversation et de bibliothèque.
4. Un parcours réel par langue de bibliothèque sur le compte de test, avec l'accord de l'auteur et ses gestes dans Zotero. Ce parcours va de l'audit à l'annulation, en passant par le plan, l'essai, le reste et la synchronisation.
5. Mise à jour du dossier de travail de l'auteur, qui reste français, puis publication en 0.4.0 par `outils/publier.sh`.

## Charge

Environ 15 à 25 heures, dont la moitié pour les phases 2 et 3, où les agents travaillent en parallèle. Les essais sur le compte de test s'y ajoutent. Les phases 0 et 1 sont sur le chemin critique et ne gagnent rien à être découpées.

## Hors périmètre

Conversion du classement d'une bibliothèque existante d'une langue à l'autre (D214), traduction de l'historique des décisions (D212), autres langues que le français et l'anglais.
