# Tests manuels sur le compte Zotero de test

Ces tests écrivent pour de vrai, sur un compte Zotero réservé aux essais (D45). Ils ne tournent pas dans l'intégration continue, pour ne pas y exposer de clé. Aucune écriture sur un compte réel pendant le développement.

## Mise en place, une seule fois

1. Créer un compte sur zotero.org réservé aux essais, et noter son identifiant (page « Security » des réglages, « Your user ID for use in API calls »).
2. Créer un second profil Zotero. Zotero fermé, le lancer avec le gestionnaire de profils (`/Applications/Zotero.app/Contents/MacOS/zotero -P` sous macOS, `zotero.exe -P` sous Windows). Dans ce profil, choisir `~/Zotero-test` comme dossier de données (Réglages › Avancé › Fichiers et dossiers), se connecter au compte de test et laisser la synchronisation des fichiers sur « Zotero ».
3. Créer le dossier de travail de test, avec la clé du compte de test :
   `zc init ~/zc-test --zotero-dir ~/Zotero-test`
4. Dans `~/zc-test/config.toml`, régler l'essai sur un seul groupe, pour que les petits plans de test passent bien par l'essai puis par l'application complète :
   `[ecriture]` puis `essai = 1`

## Remplir le compte

Bibliothèque de test vide, depuis la racine du dépôt :

    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manual/populate.py --dossier ~/zc-test

Le script refuse d'écrire si la clé du `.env` n'est pas celle de ce compte. Synchroniser ensuite le profil de test dans Zotero.

Pour repartir de zéro, `tests/manual/clear.py` (mêmes arguments) supprime d'abord toutes les fiches, corbeille comprise, les collections, les recherches enregistrées et les couleurs des tags du compte de test.

## Parcours à vérifier

Dans `~/zc-test`, profil de test ouvert sauf pour la sauvegarde :

1. `zc audit` signale doublons, métadonnées manquantes, tags automatiques, PDF identiques, fiche sans collection.
2. `zc duplicates find` propose trois groupes sûrs (même DOI à deux et à trois fiches, même titre), trois à juger (éditions de Robin, traduction de Vygotski, article et communication de Heylen) et laisse les deux chapitres tranquilles.
3. Juger les groupes (`zc duplicates reject` pour Robin et Vygotski, distincts, `zc duplicates accept` pour Heylen), accepter les groupes sûrs avec `zc duplicates accept --certain`, puis `zc duplicates plan`. Le groupe Heylen doit être écarté (types différents).
4. `zc apply <plan> --all` doit être refusé (pas d'essai), `--trial` doit appliquer un groupe, puis `--all` doit être refusé faute de sauvegarde. Vérifier dans Zotero la fusion (PDF identique à la corbeille, PDF annoté et note rattachés, collections réunies).
5. Fermer Zotero, `zc backup`, rouvrir, `zc apply <plan> --all`.
6. Modifier à la main dans Zotero le titre d'une fiche conservée, puis `zc undo <plan>` et appliquer le plan d'annulation. Le titre retouché doit rester, le reste revenir, les fiches absorbées sortir de la corbeille.
7. `zc journal` montre les opérations et l'annulation.
8. Changement de type. Les DOI des fiches de test sont fictifs, créer donc à la main dans le profil de test un article de revue « Self-organization in communicating groups », auteur Heylighen, 2013, DOI `10.1007/978-3-642-32817-6_10` (un vrai chapitre chez Crossref), revue « Revue de test », numéro 4. Synchroniser, puis `zc metadata types` et appliquer. Vérifier que l'API accepte de vider dans la même requête les champs que le nouveau type n'admet pas, puis que l'annulation rend l'article intact. Le faux serveur ne le garantit pas.
9. Collections (D114). Depuis la racine du dépôt, `ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/probe_collections.py --dossier ~/zc-test`. Les huit vérifications doivent réussir (création avec clés fournies, enfant sous son parent, renommage et déplacement, version périmée refusée, corbeille, lecture groupée corbeille comprise, retour de corbeille, fiche rangée). La sonde supprime ensuite tout ce qu'elle a créé.
10. Plan du fonds et rangement (D95 à D122). Dans `~/zc-test`, `zc subjects inventory`, puis écrire un `plan.md` avec `# Fonds`, `## Psychologie`, `### Perception` (sous-thème à créer) et `## Philosophie`. Dans `suivi/fonds.toml`, donner les sorts (Psychologie et Philosophie « thème », `Vieux classement` « archives », `À trier` « répartir » entre Psychologie et Philosophie) et une racine à renommer (`"Inbox" = "Boîte"`). `zc subjects validate --save`. Dans `suivi/rangement.toml`, accepter trois décisions (l'article « Acquisition of categorical color perception » de Psychologie vers `Psychologie/Perception`, la fiche « Une fiche rangée partout » hors de `À trier` vers Philosophie, l'autre fiche Özgen ajoutée à Perception). `zc subjects pending` doit présenter `À trier` et les fiches sans place. `zc subjects plan --roots` doit donner six groupes (Archives créée, Perception créée avec ses deux fiches, `Vieux classement` archivée, la fiche qui quitte `À trier`, `À trier` à la corbeille, `Inbox` renommée). Essai, sauvegarde, `--all`, vérification, puis `zc undo <plan>` appliqué en entier : tout revient, les collections créées vont à la corbeille. Les supprimer ensuite de la corbeille.

Les trois sondes suivantes se font en plusieurs phases, parce qu'elles vérifient ce que Zotero de bureau fait après synchronisation. Chacune se lance depuis la racine du dépôt, toujours avec `ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/<sonde>.py --dossier ~/zc-test` suivi de la phase, et garde son état dans `~/zc-test/sondes/<nom>.json` d'une phase à l'autre. Une phase qui trouve la copie locale en retard sur le serveur, ou des changements pas encore envoyés, s'arrête et demande de synchroniser. Chaque vérification affiche « réussi » ou « échoué » avec ce qui a été observé, puis des questions sur ce qui ne se voit que dans Zotero, dont il faut noter les réponses. Pour certains points (purge des tags orphelins, double laissé par BBT), « échoué » signifie seulement que l'hypothèse écrite ne tient pas, c'est un constat à reporter dans les décisions. `--nettoyer` supprime tout ce que la sonde a créé, même après une phase interrompue.

11. Tags (D156). Profil de test ouvert.
    1. `probe_tags.py --preparer` crée quatre fiches « zc-sonde tags… », un PDF, une annotation et la couleur du tag « zc-sonde coloré ».
    2. Synchroniser dans Zotero. Regarder que « zc-sonde coloré » apparaît en couleur dans le sélecteur de tags.
    3. `probe_tags.py --ecrire` réécrit les listes de tags (tag automatique gardé avec `"type": 1`, un autre sans type, tags de l'annotation, retrait des seules fiches du tag coloré et d'un tag qui devient orphelin).
    4. Synchroniser.
    5. `probe_tags.py --verifier`, puis répondre aux questions (sélecteur de tags, icônes des tags de la fiche « automatique », tag de l'annotation dans le lecteur, conflits).
    6. `probe_tags.py --nettoyer`, synchroniser, et supprimer à la main les tags « zc-sonde » restés dans le sélecteur.
12. Clés de citation (D146). Better BibTeX doit être installé et actif dans le profil de test (Outils › Extensions, version 8 ou plus), avec ses réglages par défaut. Noter avant de l'installer si le dossier `~/Zotero-test` contient déjà un dossier `better-bibtex/`.
    1. `probe_citation_keys.py --preparer` crée six fiches « zc-sonde clés… », dont deux avec une clé et une avec `tex.ids: zcSondeAncienne` dans Extra.
    2. Synchroniser, attendre une dizaine de secondes que BBT remplisse les clés manquantes, synchroniser encore pour les envoyer.
    3. `probe_citation_keys.py --ecrire` vérifie les clés reçues et remplies, puis écrit une clé, en vide une et donne la même clé à deux fiches. Elle s'arrête si BBT n'a rempli aucune clé.
    4. Synchroniser, attendre une dizaine de secondes, synchroniser encore.
    5. `probe_citation_keys.py --verifier`, puis répondre aux questions. Pour l'export, clic droit sur « zc-sonde clés, alias dans Extra », « Exporter la fiche… », formats « Better BibLaTeX » puis « Better BibTeX », et regarder dans le `.bib` si l'entrée porte `ids = {zcSondeAncienne}`. Synchroniser une fois de plus et relancer `--verifier` pour voir si BBT change l'une des deux clés en double après coup.
    6. `probe_citation_keys.py --nettoyer`, puis synchroniser.
13. Noms des fichiers (D147). Profil de test ouvert.
    1. `probe_filenames.py --preparer` crée trois fiches « zc-sonde noms… » avec un PDF chacune.
    2. Dans le profil de test, Réglages › Synchronisation › Synchronisation des fichiers, régler « Télécharger les fichiers » sur « au besoin », pour qu'un des fichiers reste absent du disque. Synchroniser.
    3. Ouvrir par un double-clic le PDF de « zc-sonde noms, fichier présent » et celui de « zc-sonde noms, casse seule », pour qu'ils soient téléchargés, puis fermer leurs onglets. Ne pas ouvrir celui de « zc-sonde noms, fichier absent ».
    4. `probe_filenames.py --ecrire` vérifie que les deux premiers fichiers sont sur le disque et le troisième absent, puis écrit les nouveaux noms (avec espaces et accents, par la casse seule, fichier absent).
    5. Synchroniser.
    6. `probe_filenames.py --verifier` contrôle le chemin dans la base, le nom sur le disque (casse comprise), qu'il ne reste pas l'ancien fichier et que Zotero n'a rien renvoyé au serveur. Répondre aux questions (ouverture des PDF, conflits, nom affiché). Ouvrir alors le PDF de « fichier absent » et relancer `--verifier`, qui contrôle le nom du fichier téléchargé.
    7. `probe_filenames.py --annuler` remet les anciens noms.
    8. Synchroniser, puis `probe_filenames.py --verifier` de nouveau, mêmes questions.
    9. `probe_filenames.py --nettoyer`, synchroniser, et remettre « Télécharger les fichiers » sur « à la synchronisation ».


## Parcours de la version 0.4, une fois par langue de bibliothèque (D238)

À faire avec l'accord de l'auteur et ses gestes dans Zotero, une fois la CI, l'installation propre, la reprise d'un dossier 0.3.2 (`tests/test_resume_032.py`) et les pilotes passés. Profil de test ouvert sauf pour la sauvegarde.

1. Mise à jour d'un dossier 0.3.2. Dans `~/zc-test` (écrit par la 0.3.2), `zc init --update ~/zc-test`. Vérifier que les anciens skills sont retirés (`.agents/skills/doublons/` absent, `duplicates/` présent), que `methode.md` est la version française à jour, puis `zc config show` (langue `fr`, noms inchangés) et `zc audit`.
2. Bibliothèque française. `clear.py` puis `populate.py` (voir plus haut), synchroniser, puis `zc init ~/zc-test-fr --zotero-dir ~/Zotero-test --library-language fr` avec la clé du compte de test. Dans `~/zc-test-fr/config.toml`, régler `[ecriture]` puis `essai = 1`. Puis, avec un agent ouvert dans `~/zc-test-fr` (« où en est ma bibliothèque ? », puis « nettoyons les doublons ») : `zc audit`, `zc duplicates find`, décisions, `zc duplicates plan`, `zc apply <plan> --trial`, fermer Zotero, `zc backup`, rouvrir, `zc apply <plan> --all`, synchroniser, `zc audit` (il doit d'abord prévenir que Zotero n'a pas tout reçu s'il est lancé avant la synchronisation), puis `zc undo <plan>` appliqué en entier et vérifié dans Zotero. Rapports, messages et `suivi/` en français, commandes en anglais.
3. Bibliothèque anglaise. `clear.py` puis `populate.py`, synchroniser, puis `zc init ~/zc-test-en --zotero-dir ~/Zotero-test --library-language en`, `essai = 1`, et le même parcours avec un agent à qui l'on parle en anglais. `config.toml` doit écrire en clair les noms anglais (`fonds = "Subjects"`, `etats = ["1 to read", …]`, `tags_exclus = ["_private"]`), le dossier reçoit `method.md`, et rapports, messages et commentaires de `suivi/` sont en anglais, les mots stockés restant français.
4. Après chaque parcours, `zc journal` (modes `trial` et `all` dans la bibliothèque anglaise) et une note des frictions, à reporter dans les décisions.
