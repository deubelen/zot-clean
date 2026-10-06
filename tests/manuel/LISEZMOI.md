# Tests manuels sur le compte Zotero de test

Ces tests écrivent pour de vrai, sur un compte Zotero réservé aux essais (D45). Ils ne tournent pas dans l'intégration continue, pour ne pas y exposer de clé. Aucune écriture sur un compte réel pendant le développement.

## Mise en place, une seule fois

1. Créer un compte sur zotero.org réservé aux essais, et noter son identifiant (page « Security » des réglages, « Your user ID for use in API calls »).
2. Créer un second profil Zotero. Zotero fermé, le lancer avec le gestionnaire de profils (`/Applications/Zotero.app/Contents/MacOS/zotero -P` sous macOS, `zotero.exe -P` sous Windows). Dans ce profil, choisir `~/Zotero-test` comme dossier de données (Réglages › Avancé › Fichiers et dossiers), se connecter au compte de test et laisser la synchronisation des fichiers sur « Zotero ».
3. Créer le dossier de travail de test, avec la clé du compte de test :
   `zc init ~/zc-test --dossier-zotero ~/Zotero-test`
4. Dans `~/zc-test/config.toml`, régler l'essai sur un seul groupe, pour que les petits plans de test passent bien par l'essai puis par l'application complète :
   `[ecriture]` puis `essai = 1`

## Remplir le compte

Bibliothèque de test vide, depuis la racine du dépôt :

    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manuel/peupler.py --dossier ~/zc-test

Le script refuse d'écrire si la clé du `.env` n'est pas celle de ce compte. Synchroniser ensuite le profil de test dans Zotero.

Pour repartir de zéro, `tests/manuel/vider.py` (mêmes arguments) supprime d'abord toutes les fiches, corbeille comprise, les collections, les recherches enregistrées et les couleurs des tags du compte de test.

## Parcours à vérifier

Dans `~/zc-test`, profil de test ouvert sauf pour la sauvegarde :

1. `zc audit` signale doublons, métadonnées manquantes, tags automatiques, PDF identiques, fiche sans collection.
2. `zc doublons chercher` propose trois groupes sûrs (même DOI à deux et à trois fiches, même titre), trois à juger (éditions de Robin, traduction de Vygotski, article et communication de Heylen) et laisse les deux chapitres tranquilles.
3. Juger les groupes (`zc doublons refuser` pour Robin et Vygotski, distincts, `zc doublons accepter` pour Heylen), accepter les groupes sûrs avec `zc doublons accepter --surs`, puis `zc doublons planifier`. Le groupe Heylen doit être écarté (types différents).
4. `zc appliquer <plan> --tout` doit être refusé (pas d'essai), `--essai` doit appliquer un groupe, puis `--tout` doit être refusé faute de sauvegarde. Vérifier dans Zotero la fusion (PDF identique à la corbeille, PDF annoté et note rattachés, collections réunies).
5. Fermer Zotero, `zc sauvegarder`, rouvrir, `zc appliquer <plan> --tout`.
6. Modifier à la main dans Zotero le titre d'une fiche conservée, puis `zc annuler <plan>` et appliquer le plan d'annulation. Le titre retouché doit rester, le reste revenir, les fiches absorbées sortir de la corbeille.
7. `zc journal` montre les opérations et l'annulation.
8. Changement de type. Les DOI des fiches de test sont fictifs, créer donc à la main dans le profil de test un article de revue « Self-organization in communicating groups », auteur Heylighen, 2013, DOI `10.1007/978-3-642-32817-6_10` (un vrai chapitre chez Crossref), revue « Revue de test », numéro 4. Synchroniser, puis `zc metadonnees types` et appliquer. Vérifier que l'API accepte de vider dans la même requête les champs que le nouveau type n'admet pas, puis que l'annulation rend l'article intact. Le faux serveur ne le garantit pas.
9. Collections (D114). Depuis la racine du dépôt, `ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/sonde_collections.py --dossier ~/zc-test`. Les huit vérifications doivent réussir (création avec clés fournies, enfant sous son parent, renommage et déplacement, version périmée refusée, corbeille, lecture groupée corbeille comprise, retour de corbeille, fiche rangée). La sonde supprime ensuite tout ce qu'elle a créé.
10. Plan du fonds et rangement (D95 à D122). Dans `~/zc-test`, `zc fonds inventaire`, puis écrire un `plan.md` avec `# Fonds`, `## Psychologie`, `### Perception` (sous-thème à créer) et `## Philosophie`. Dans `suivi/fonds.toml`, donner les sorts (Psychologie et Philosophie « thème », `Vieux classement` « archives », `À trier` « répartir » entre Psychologie et Philosophie) et une racine à renommer (`"Inbox" = "Boîte"`). `zc fonds valider --enregistrer`. Dans `suivi/rangement.toml`, accepter trois décisions (l'article « Acquisition of categorical color perception » de Psychologie vers `Psychologie/Perception`, la fiche « Une fiche rangée partout » hors de `À trier` vers Philosophie, l'autre fiche Özgen ajoutée à Perception). `zc fonds a-ranger` doit présenter `À trier` et les fiches sans place. `zc fonds planifier --racines` doit donner six groupes (Archives créée, Perception créée avec ses deux fiches, `Vieux classement` archivée, la fiche qui quitte `À trier`, `À trier` à la corbeille, `Inbox` renommée). Essai, sauvegarde, `--tout`, vérification, puis `zc annuler <plan>` appliqué en entier : tout revient, les collections créées vont à la corbeille. Les supprimer ensuite de la corbeille.

Les trois sondes suivantes se font en plusieurs phases, parce qu'elles vérifient ce que Zotero de bureau fait après synchronisation. Chacune se lance depuis la racine du dépôt, toujours avec `ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/<sonde>.py --dossier ~/zc-test` suivi de la phase, et garde son état dans `~/zc-test/sondes/<nom>.json` d'une phase à l'autre. Une phase qui trouve la copie locale en retard sur le serveur, ou des changements pas encore envoyés, s'arrête et demande de synchroniser. Chaque vérification affiche « réussi » ou « échoué » avec ce qui a été observé, puis des questions sur ce qui ne se voit que dans Zotero, dont il faut noter les réponses. Pour certains points (purge des tags orphelins, double laissé par BBT), « échoué » signifie seulement que l'hypothèse écrite ne tient pas, c'est un constat à reporter dans les décisions. `--nettoyer` supprime tout ce que la sonde a créé, même après une phase interrompue.

11. Tags (D156). Profil de test ouvert.
    1. `sonde_tags.py --preparer` crée quatre fiches « zc-sonde tags… », un PDF, une annotation et la couleur du tag « zc-sonde coloré ».
    2. Synchroniser dans Zotero. Regarder que « zc-sonde coloré » apparaît en couleur dans le sélecteur de tags.
    3. `sonde_tags.py --ecrire` réécrit les listes de tags (tag automatique gardé avec `"type": 1`, un autre sans type, tags de l'annotation, retrait des seules fiches du tag coloré et d'un tag qui devient orphelin).
    4. Synchroniser.
    5. `sonde_tags.py --verifier`, puis répondre aux questions (sélecteur de tags, icônes des tags de la fiche « automatique », tag de l'annotation dans le lecteur, conflits).
    6. `sonde_tags.py --nettoyer`, synchroniser, et supprimer à la main les tags « zc-sonde » restés dans le sélecteur.
12. Clés de citation (D146). Better BibTeX doit être installé et actif dans le profil de test (Outils › Extensions, version 8 ou plus), avec ses réglages par défaut. Noter avant de l'installer si le dossier `~/Zotero-test` contient déjà un dossier `better-bibtex/`.
    1. `sonde_cles.py --preparer` crée six fiches « zc-sonde clés… », dont deux avec une clé et une avec `tex.ids: zcSondeAncienne` dans Extra.
    2. Synchroniser, attendre une dizaine de secondes que BBT remplisse les clés manquantes, synchroniser encore pour les envoyer.
    3. `sonde_cles.py --ecrire` vérifie les clés reçues et remplies, puis écrit une clé, en vide une et donne la même clé à deux fiches. Elle s'arrête si BBT n'a rempli aucune clé.
    4. Synchroniser, attendre une dizaine de secondes, synchroniser encore.
    5. `sonde_cles.py --verifier`, puis répondre aux questions. Pour l'export, clic droit sur « zc-sonde clés, alias dans Extra », « Exporter la fiche… », formats « Better BibLaTeX » puis « Better BibTeX », et regarder dans le `.bib` si l'entrée porte `ids = {zcSondeAncienne}`. Synchroniser une fois de plus et relancer `--verifier` pour voir si BBT change l'une des deux clés en double après coup.
    6. `sonde_cles.py --nettoyer`, puis synchroniser.
13. Noms des fichiers (D147). Profil de test ouvert.
    1. `sonde_noms.py --preparer` crée trois fiches « zc-sonde noms… » avec un PDF chacune.
    2. Dans le profil de test, Réglages › Synchronisation › Synchronisation des fichiers, régler « Télécharger les fichiers » sur « au besoin », pour qu'un des fichiers reste absent du disque. Synchroniser.
    3. Ouvrir par un double-clic le PDF de « zc-sonde noms, fichier présent » et celui de « zc-sonde noms, casse seule », pour qu'ils soient téléchargés, puis fermer leurs onglets. Ne pas ouvrir celui de « zc-sonde noms, fichier absent ».
    4. `sonde_noms.py --ecrire` vérifie que les deux premiers fichiers sont sur le disque et le troisième absent, puis écrit les nouveaux noms (avec espaces et accents, par la casse seule, fichier absent).
    5. Synchroniser.
    6. `sonde_noms.py --verifier` contrôle le chemin dans la base, le nom sur le disque (casse comprise), qu'il ne reste pas l'ancien fichier et que Zotero n'a rien renvoyé au serveur. Répondre aux questions (ouverture des PDF, conflits, nom affiché). Ouvrir alors le PDF de « fichier absent » et relancer `--verifier`, qui contrôle le nom du fichier téléchargé.
    7. `sonde_noms.py --annuler` remet les anciens noms.
    8. Synchroniser, puis `sonde_noms.py --verifier` de nouveau, mêmes questions.
    9. `sonde_noms.py --nettoyer`, synchroniser, et remettre « Télécharger les fichiers » sur « à la synchronisation ».

