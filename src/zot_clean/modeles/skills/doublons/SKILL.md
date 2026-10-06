---
name: doublons
description: Repérer, juger et fusionner les doublons de la bibliothèque Zotero avec zc (étape 2 du nettoyage). À utiliser quand l'utilisateur parle de doublons, de fiches en double ou de fusion, ou quand l'audit signale des doublons probables.
---

# Doublons

Les doublons se traitent en deux temps. `zc` repère les groupes et exécute la fusion, l'agent aide l'utilisateur à juger chaque groupe. Toutes les décisions vivent dans `suivi/doublons.toml`, qui fait foi. Rien ne fusionne sans y être décidé. Elles s'y écrivent par `zc doublons accepter` et `zc doublons refuser`, sans toucher au fichier.

## Déroulé

1. **Faire venir les fichiers.** `zc` compare les PDF sur le disque, pour reconnaître deux fiches qui portent le même PDF et pour mettre à la corbeille une copie identique lors d'une fusion. Un fichier que Zotero n'a pas encore téléchargé n'est pas comparé, la copie identique est alors gardée en double. Si l'audit (point 6, « Non contrôlé ») ou une commande signale des PDF absents du disque, demander à l'utilisateur, dans Zotero, Réglages › Synchronisation, de régler « Télécharger les fichiers » sur « au moment de la synchronisation », de synchroniser puis d'attendre la fin du téléchargement. C'est valable aussi quand les fichiers sont synchronisés par WebDAV. Si Zotero ne synchronise pas les fichiers, rien ne viendra, les fichiers absents relèvent du point 5 de l'audit. Grouper ce geste avec la sauvegarde (point 5 ci-dessous), qui demande aussi l'utilisateur. Terminé quand plus aucune commande ne signale de PDF absent, ou que l'utilisateur a choisi de continuer sans.

2. **Repérer.** Lancer `zc doublons chercher`. Terminé quand la commande a mis à jour `suivi/doublons.toml` et donné le nombre de groupes sûrs, à juger et déjà décidés. Relancer la commande après le téléchargement des fichiers, puisque les fiches qui partagent un PDF n'apparaissent qu'à ce moment.

3. **Juger.** Lire `suivi/doublons.toml`. Chaque groupe y est précédé d'une ligne par fiche (clé, premier auteur, année, titre, type, pièces jointes).
   - Groupes `sûr` sans décision. Les présenter ensemble, en quelques lignes. Si l'utilisateur les accepte en bloc, lancer `zc doublons accepter --surs`, avec `--sauf <clé> …` (une fiche de chaque groupe) pour ceux qu'il écarte.
   - Groupes `à juger`. Avant de recommander quoi que ce soit, lancer `zc voir <clés du groupe>`, qui donne les champs complets des fiches et le début du texte de leurs PDF, lu en local. Comparer le titre et les auteurs imprimés sur la première page des PDF à ceux des fiches. Présenter ensuite les groupes par paquets de 10, chacun avec une recommandation (`fusionner` ou `distinct`) tirée des critères ci-dessous, une phrase de justification et ce qui a été vérifié. Ne demander à l'utilisateur de regarder les fiches dans Zotero que si le doute subsiste après cette vérification (PDF absent, scanné ou muet, fiches confidentielles), en disant pourquoi.
   - Un groupe peut réunir des fiches aux titres différents qui portent le même PDF. Ce sont souvent des doublons dont l'un a été mal saisi, mais parfois une fiche porte le PDF d'une autre (voir « PDF identiques »). Le texte du PDF tranche. Pour une fusion, choisir avec l'utilisateur la fiche à garder (`--conserver`) et, si besoin, le bon titre (`forcer`).
   - Écrire les décisions par la commande, une fois les réponses données. Un groupe se désigne par la clé de l'une de ses fiches. `zc doublons accepter <clé> …` fusionne, `zc doublons accepter --conserver <clé> …` fusionne en gardant ces fiches-là (une par groupe), `zc doublons refuser <clé> … --raison "<raison>"` juge les groupes distincts (une commande par raison). Seul `forcer` (valeur imposée à la fiche gardée, par exemple `{ "date" = "1938" }`) s'écrit encore à la main dans le fichier, sur un groupe déjà accepté. Une décision déjà prise ne change pas par commande. Pour revenir dessus, la modifier dans le fichier.
   - Deux fiches que `zc` n'a pas réunies, alors qu'elles décrivent la même publication, s'ajoutent à la main à la fin du fichier, comme le montre son en-tête (`[[groupe]]`, `cles`, `decision = "fusionner"`). Le groupe est gardé tant que ses fiches existent.

   Terminé quand chaque groupe a une décision, ou que l'utilisateur a choisi d'en laisser certains pour plus tard.

4. **Planifier.** Lancer `zc doublons planifier`. Lire le rapport `.md` indiqué et le résumer à l'utilisateur, à savoir le nombre de groupes, les groupes écartés et pourquoi, et les « valeurs différentes » où la fiche conservée l'emporte. Si le rapport commence par un avertissement sur des PDF absents du disque, revenir à l'étape 1 avant d'appliquer, sinon des copies identiques resteront en double. Rappeler que Zotero vide sa corbeille après 30 jours, et qu'une fusion n'est plus annulable ensuite. Si l'utilisateur veut changer quelque chose, changer la décision (dans `suivi/doublons.toml` pour une décision déjà prise) et replanifier. Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

5. **Sauvegarder.** Une fois le plan approuvé, si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero, puis lancer `zc sauvegarder`. Terminé quand la commande affiche le dossier de la sauvegarde. L'utilisateur peut ensuite rouvrir Zotero.

6. **Essai.** Lancer `zc appliquer <plan> --essai`, puis vérifier soi-même les fiches conservées avec `zc voir` (champs, pièces jointes et notes rattachées, collections) et que les fiches absorbées ne sont plus lues. Dire à l'utilisateur ce qui a été vérifié. Terminé quand l'essai est vérifié.

7. **Appliquer.** Lancer `zc appliquer <plan> --tout`. Si la commande s'interrompt, la relancer telle quelle, elle reprend où elle s'était arrêtée. Présenter les groupes en conflit (fiches modifiées depuis le plan). Ceux que `zc` dit « laissés intacts » n'ont pas été touchés, et une nouvelle recherche les reproposera. Ceux qu'il dit « arrêtés après une partie des écritures » sont à moitié fusionnés. Les vérifier avec `zc voir`, puis, avec l'accord de l'utilisateur, soit régler le conflit et relancer la même commande, qui finit le groupe, soit défaire ce qui a été écrit avec `zc annuler <journal>`.

8. **Contrôler.** Lancer `zc doublons chercher` puis `zc audit`, et dire à l'utilisateur ce qui reste.

Pour revenir sur une fusion, lancer `zc annuler <plan>`, résumer le rapport d'annulation, puis suivre les étapes 6 et 7 avec le plan d'annulation.

## PDF identiques

Un même PDF peut être rattaché à plusieurs fiches, ou deux fois à la même (audit, point 6). Les fiches différentes qui le partagent sont aussi proposées par `zc doublons chercher`, à juger. Comme pour les doublons, seuls les fichiers présents sur le disque sont comparés (étape 1).

1. Lancer `zc pieces chercher`, qui écrit `suivi/pieces.toml`, un groupe par PDF présent en plusieurs copies. Le commentaire de chaque copie donne la fiche qui la porte et ses annotations ou notes. Si la commande signale des PDF partagés absents de `suivi/doublons.toml`, relancer `zc doublons chercher`.
2. Pour savoir à quelle fiche le PDF appartient, lancer `zc voir <clés des copies>`, qui montre chaque fiche porteuse et le début du texte du PDF, lu en local. Ne pas ouvrir le PDF d'un groupe marqué « (fiche confidentielle) » par un autre moyen, c'est l'utilisateur qui le regarde dans Zotero.
3. Si les fiches sont des doublons, les fusionner d'abord (déroulé ci-dessus). La fusion met la copie identique à la corbeille, et le groupe disparaît de `suivi/pieces.toml` à la recherche suivante. Pour les autres, proposer :
   - de mettre à la corbeille les copies en trop ou sur la mauvaise fiche. Jamais une copie annotée ou portant une note, que `zc` refuse. Si elle est sur la mauvaise fiche, la rattacher à la bonne, et mettre l'autre copie à la corbeille.
   - de garder les copies quand elles sont voulues, par exemple un chapitre et le livre entier, ou un commentaire et l'article cible.
4. Faire approuver, puis écrire les décisions par la commande, chaque copie désignée par sa clé de pièce jointe (celle que donne le fichier, non celle de la fiche). `zc pieces accepter --corbeille <copie> … --rattacher <copie>=<fiche> …` pour les groupes à traiter, `zc pieces refuser <copie> … --raison "<raison>"` pour ceux à garder (une copie de chaque groupe suffit). Puis `zc pieces planifier`, résumer le rapport, essai et application comme pour les doublons.

## Critères de jugement

Fusionner quand les fiches décrivent la même publication dans la même édition, même si elles diffèrent par la casse, la ponctuation, un sous-titre tronqué, un DOI ou un ISBN présent d'un seul côté, ou la forme du nom de l'auteur (« Merleau-Ponty, M. » et « Merleau-Ponty, Maurice »), à année et éditeur identiques.

Garder distinct (`distinct`) quand les fiches désignent des textes différents, ou des états différents d'un texte que l'utilisateur peut vouloir citer séparément :
- éditions différentes (années ou éditeurs différents, édition revue, réédition avec nouvelle préface) ;
- traduction et original, ou deux traductions ;
- tomes ou parties différents d'un même ouvrage ;
- prépublication et version publiée, sauf si l'utilisateur ne veut garder que la version publiée ;
- compte rendu d'un livre et livre lui-même.

Deux fiches au même ISBN mais d'années ou d'éditeurs différents restent distinctes. L'ISBN de l'une est sans doute mal saisi (un livre de 1938 n'a pas d'ISBN), ce que l'étape 3 relèvera.

Un groupe de types différents (article et communication, livre et rapport) est écarté par `zc doublons planifier`. Si les fiches décrivent bien la même publication, l'accepter quand même (`zc doublons accepter`), puis donner aux deux fiches le même type. `zc metadonnees types` (étape 3) le propose pour chaque fiche du groupe (cas `type_doublon`), et l'on accepte seulement le cas de la fiche dont le type est faux. L'utilisateur peut aussi changer le type lui-même dans Zotero, menu « Type de document » de la fiche. Une fois les types égaux, relancer `zc doublons planifier`. Si les fiches ne décrivent pas la même publication, juger le groupe distinct (`zc doublons refuser`).

En cas de doute, présenter les deux lectures et laisser l'utilisateur trancher.
