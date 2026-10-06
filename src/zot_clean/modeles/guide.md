# Guide pas à pas

Ce guide accompagne une première séance avec `zot-clean`, de l'installation au premier nettoyage. Il ne suppose aucune connaissance technique, seulement de savoir copier une ligne dans un terminal et appuyer sur Entrée. Comptez une demi-heure pour l'installation et le premier audit.

Si un mot vous arrête, le [lexique](#lexique) en fin de page l'explique.

## Avant de commencer

Il vous faut

- **Zotero 7** ou une version plus récente, installé sur votre ordinateur (l'étape 7, sur les clés de citation, demande Zotero 8 et l'extension Better BibTeX 8 ou plus récents) ;
- **un compte zotero.org avec la synchronisation activée** (Zotero › Réglages › Synchronisation). `zot-clean` écrit dans votre bibliothèque en passant par le serveur de Zotero, et votre ordinateur reçoit ensuite les changements par la synchronisation, comme s'ils venaient d'un autre de vos appareils ;
- **un agent en ligne de commande**, comme [Claude Code](https://claude.com/claude-code) ou [Codex](https://openai.com/codex/), pour les étapes qui demandent du jugement (décider si deux fiches sont des doublons, concevoir un plan de classement). L'audit et l'installation s'en passent ;
- de la place sur le disque pour une sauvegarde de votre dossier Zotero.

Deux précautions valent pour toute la suite.

- **Les étapes de nettoyage ne touchent jamais votre bibliothèque sans votre accord.** Chacune prépare d'abord un plan, avec un rapport qui dit fiche par fiche ce qui changera. Vous le lisez, vous essayez sur quelques fiches, vous vérifiez dans Zotero, et seulement ensuite vous appliquez le reste. Tout ce qui est appliqué peut être annulé.
- **Ce que l'agent lit part chez son fournisseur** (Anthropic pour Claude, OpenAI pour Codex). Si certaines références sont confidentielles, déclarez-les avant de travailler avec l'agent (voir [Tenir des fiches à l'écart](#tenir-des-fiches-à-lécart)).

## 1. Ouvrir un terminal

Le terminal est une fenêtre où l'on tape des commandes.

- **macOS.** Ouvrir l'application *Terminal* (dans Applications › Utilitaires, ou en tapant « Terminal » dans Spotlight).
- **Windows.** Ouvrir *PowerShell* (menu Démarrer, taper « PowerShell »).

Dans ce guide, une commande se présente dans un cadre gris. Copiez-la, collez-la dans le terminal, puis appuyez sur Entrée. Ce qui suit un `#` est un commentaire, il n'a pas besoin d'être tapé.

## 2. Installer uv

`uv` est un petit outil qui installe `zot-clean` et le Python dont il a besoin, sans rien modifier d'autre sur votre ordinateur.

Sous macOS ou Linux, copier dans le terminal :

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Sous Windows, dans PowerShell :

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Fermez ensuite le terminal et rouvrez-en un, pour qu'il trouve la commande `uv`. Pour vérifier, tapez `uv --version`. Une ligne du genre `uv 0.8.…` doit s'afficher.

## 3. Installer zot-clean

```
uv tool install git+https://github.com/deubelen/zot-clean
```

Vérifiez avec `zc --help`, qui doit afficher la liste des commandes.

Si le terminal répond `zc: command not found` (macOS) ou que le nom `zc` n'est pas reconnu (Windows), le dossier où uv installe ses outils n'est pas encore connu du terminal. Lancez

```
uv tool update-shell
```

puis fermez le terminal, rouvrez-en un et réessayez `zc --help`.

## 4. Créer la clé API de Zotero

`zot-clean` a besoin d'une clé pour écrire dans votre bibliothèque. C'est une sorte de mot de passe propre à cet usage, que vous pouvez révoquer à tout moment sans toucher à votre mot de passe Zotero.

1. Ouvrir [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new) et se connecter.
2. Donner un nom à la clé, par exemple « zot-clean ».
3. Cocher **Allow library access**, **Allow notes access** et **Allow write access**.
4. Enregistrer (*Save Key*). Zotero affiche la clé, une suite d'une vingtaine de lettres et de chiffres. Laissez la page ouverte, vous allez la copier à l'étape suivante.

Saisissez cette clé vous-même dans le terminal, sans la confier à l'agent. Elle donne le droit de modifier toute votre bibliothèque.

## 5. Créer le dossier de travail

`zot-clean` range tout ce qu'il produit (configuration, rapports, plans, journal des modifications) dans un dossier de travail, distinct du dossier de Zotero. Choisissez un dossier hors d'iCloud, de OneDrive ou de Dropbox, par exemple `Zotero-travail` dans votre dossier personnel.

```
zc init ~/Zotero-travail
```

La commande

1. cherche votre base Zotero (dans `~/Zotero` par défaut, sinon elle vous demande où elle se trouve, ce qu'indique Zotero › Réglages › Avancé › Fichiers et dossiers) ;
2. vous demande la clé API, qui ne s'affiche pas pendant que vous la collez (c'est normal), et vérifie ses droits ;
3. propose une clé OpenAlex, facultative, qui aide à trouver les DOI manquants (Entrée pour passer) ;
4. demande une adresse électronique de contact pour les services de métadonnées (facultative, Entrée pour passer) ;
5. écrit la configuration (`config.toml`), les consignes de l'agent (`AGENTS.md`) et les dossiers de travail.

Entrez ensuite dans le dossier :

```
cd ~/Zotero-travail
```

Toutes les commandes `zc` se lancent depuis ce dossier.

## 6. Premier audit

```
zc audit
```

L'audit ne modifie rien. Il lit une copie temporaire de votre base Zotero et écrit un rapport daté dans `rapports/` (par exemple `rapports/audit-2026-10-01.md`). Le terminal en affiche le résumé, douze contrôles notés « OK », « Info » ou « À voir » :

1. chiffres d'ensemble ;
2. références rangées dans aucune collection ;
3. doublons probables ;
4. métadonnées manquantes (auteur, année, DOI, ISBN) ;
5. fichiers absents du disque, en distinguant ceux qui sont encore sur zotero.org et peuvent être récupérés ;
6. PDF identiques rattachés à plusieurs fiches ;
7. tags automatiques et tags quasi identiques ;
8. clés de citation ;
9. noms des fichiers ;
10. structure des collections ;
11. synchronisation ;
12. plan du fonds, comparé aux collections du fonds dans Zotero (sauté tant que le fonds n'est pas en place).

Le rapport complet donne, pour chaque point, la liste des fiches concernées et ce que le nettoyage pourra y faire.

Pour le point 5, l'audit demande à zotero.org, avec votre clé API, quels fichiers absents y sont encore stockés. C'est le seul moment où il se connecte, et il ne fait que lire. Sans connexion, ou avec l'option `--hors-ligne`, il donne seulement le nombre de fichiers absents.

Si le point 11 signale des **éléments à clé invalide**, arrêtez-vous là. Ils bloquent la synchronisation de Zotero, et aucun nettoyage n'est possible avant leur réparation. Ouvrez une [issue](https://github.com/deubelen/zot-clean/issues) pour demander de l'aide.

## 7. Travailler avec l'agent

Ouvrez l'agent dans le dossier de travail, depuis le terminal :

```
cd ~/Zotero-travail
claude        # pour Claude Code, ou bien
codex         # pour Codex
```

L'agent trouve ses consignes dans `AGENTS.md` et un guide pour chaque étape dans `.agents/skills/`. Parlez-lui normalement, en français. Pour commencer :

> Où en est ma bibliothèque ?

Il lance l'audit, le résume en commençant par ce qui compte le plus, et propose un ordre de travail. Vous restez maître de chaque décision. L'agent vous présente ses propositions par paquets, avec une recommandation, et attend votre accord avant toute modification.

Pour Claude Code, une précaution. Si un fichier `CLAUDE.md` se trouve dans le dossier de travail ou dans un dossier au-dessus, Claude Code le lit à la place de `AGENTS.md`. `zc init` vous prévient dans ce cas et indique comment y remédier.

## 8. Le nettoyage, étape par étape

L'ordre conseillé est le suivant. Chaque étape peut s'interrompre et reprendre plus tard, l'avancement est gardé dans `suivi/`.

| Étape | Ce qu'elle fait | Ce que vous faites |
|---|---|---|
| 2. Doublons | Repère les fiches en double et les fusionne comme le fait Zotero (notes, pièces jointes et collections réunies). Traite aussi les PDF présents en plusieurs copies. | Vous confirmez les groupes sûrs en bloc et tranchez les cas douteux (deux éditions d'un même livre, une traduction et son original…). |
| 3. Métadonnées | Corrige les DOI, change le type des fiches mal typées, complète les champs vides par Crossref, OpenAlex, la BnF, le Sudoc et Open Library. Une valeur déjà présente n'est jamais remplacée. | Vous jugez les cas incertains, par exemple un DOI qui semble désigner une autre publication. |
| 4. Plan du fonds | Propose, à partir de vos collections et de vos tags, un plan de classement par disciplines et thèmes, écrit dans `plan.md`. Rien n'est modifié dans Zotero. | Vous discutez le plan avec l'agent jusqu'à le valider, puis décidez du sort de chaque ancienne collection. |
| 5. Rangement | Transforme vos collections d'après le plan validé, en gardant celles qui deviennent des thèmes, puis répartit les fiches, en plusieurs passes. | Vous approuvez les répartitions proposées par paquets. |
| 6. Tags | Range vos tags d'après la méthode (états, concepts, marques), retire les mots-clés d'éditeurs ajoutés automatiquement, réunit les variantes d'un même tag et donne leur couleur aux tags de la méthode, chacun sur une touche du clavier. |
| 7. Clés de citation | Avec Better BibTeX, départage les clés en double (la fiche la plus ancienne garde la sienne, les autres reçoivent un suffixe a, b…) et range dans le champ « Clé de citation » les clés restées dans Extra. Une clé unique n'est jamais changée. Sans Better BibTeX, seul le départage des doubles est fait. | Vous remplissez les clés manquantes dans Zotero (clic droit, Better BibTeX › Fill) et tranchez les rares cas où Extra et le champ donnent deux clés différentes. |
| 8. Noms des fichiers | Renomme le fichier principal de chaque fiche d'après le modèle de noms réglé dans Zotero (par défaut « Auteur - Année - Titre »). Le nouveau nom passe par zotero.org, et chaque ordinateur renomme ses fichiers à sa synchronisation suivante. | Après l'essai, vous lancez la synchronisation de Zotero et ouvrez les fichiers renommés pour vérifier qu'ils s'ouvrent sous leur nouveau nom. |

L'étape 1 consiste à relire `config.toml` si la méthode par défaut ne vous convient pas (voir [la méthode](methode.md)).

### Le déroulé d'une étape

Toutes les étapes qui modifient Zotero suivent le même déroulé. L'agent le conduit, mais il est bon de le connaître.

1. **Repérer et juger.** Une commande (`zc doublons chercher`, par exemple) écrit les cas dans un fichier de `suivi/`. L'agent vous les présente et y note vos décisions.
2. **Sauvegarder.** Fermez Zotero, puis l'agent lance `zc sauvegarder`. Rouvrez Zotero ensuite. Une sauvegarde de moins de 24 heures est exigée avant toute modification de masse. Sous macOS, elle copie tout le dossier Zotero en quelques secondes, sans occuper de place supplémentaire tant que rien ne change. Sous Windows et Linux, elle copie la base seule (fiches, notes, collections), ce qui suffit puisque `zot-clean` ne touche jamais au contenu des fichiers PDF (l'étape 8 en change seulement le nom, que `zc annuler` sait remettre).
3. **Planifier.** Une commande (`zc doublons planifier`) prépare le plan et son rapport dans `plans/`. L'agent vous le résume. Vous pouvez le lire vous-même, c'est un fichier texte.
4. **Essayer.** Avec votre accord, l'agent lance `zc appliquer <plan> --essai`, qui n'applique que les cinq premiers groupes. Laissez Zotero se synchroniser (flèche verte en haut à droite si rien ne bouge), puis vérifiez ces fiches dans Zotero.
5. **Appliquer.** Si l'essai vous convient, l'agent lance `zc appliquer <plan> --tout`. Si la commande s'interrompt (coupure de réseau, par exemple), il suffit de la relancer, elle reprend où elle s'était arrêtée.
6. **Contrôler.** L'agent relance l'audit et vous dit ce qui reste.

### Revenir en arrière

Chaque application est inscrite dans `journal/`. Pour défaire une étape :

```
zc journal                   # liste des modifications faites
zc annuler plans/<le plan>   # prépare le plan d'annulation
```

L'annulation est elle-même un plan, à essayer puis appliquer comme les autres. Une seule limite : Zotero vide sa corbeille après 30 jours (réglage par défaut). Une fusion dont la fiche absorbée a quitté la corbeille ne peut plus être annulée par `zc annuler`. La sauvegarde reste alors le dernier recours.

## 9. Ensuite, trier les nouvelles références

Une fois le fonds en place, les nouvelles références arrivent dans l'Inbox (ou directement dans un projet, si c'est la collection sélectionnée quand vous enregistrez avec le connecteur de Zotero). Pour les trier, dites à l'agent « trie l'Inbox », à la fréquence qui vous convient.

L'agent lance `zc inbox preparer`, qui cherche pour ces seules références les doublons, les corrections de métadonnées et les thèmes où sont rangées d'autres fiches du même auteur ou de la même revue. Il vous propose un thème pour chacune, d'après les définitions de `plan.md`. Quand aucun ne convient, il propose le plus proche ou un nouveau thème, et la référence reste dans l'Inbox tant que vous n'avez pas tranché. Une référence d'un projet y reste et reçoit en plus son thème. Une fois l'étape 6 faite, les tags des nouvelles références suivent les règles que vous avez acceptées (tags automatiques retirés, variantes ramenées à leur forme), et un tag manuel nouveau vous est seulement signalé.

`zc inbox planifier` réunit tout en un seul plan, que l'agent vous résume. Un plan de tri qui touche moins de 50 fiches s'applique d'un coup, sans essai ni sauvegarde récente, puisque le journal et `zc annuler` suffisent pour revenir en arrière. Vous vérifiez le résultat après. Au-delà, le déroulé habituel s'applique (essai, sauvegarde, application).

## 10. Le contrôle régulier

Chaque audit garde la trace de ce qu'il a relevé. Le suivant s'ouvre donc sur ce qui est apparu et ce qui est réglé depuis (nouveaux doublons, métadonnées manquantes, fichiers absents, références hors du fonds). Un douzième contrôle compare `plan.md` aux collections du fonds. Comme l'agent lance l'audit au début de chaque séance, le contrôle se fait sans y penser.

Après le nettoyage, c'est Zotero qui fait foi. Vous pouvez créer, renommer, déplacer ou supprimer un thème directement dans Zotero. Le contrôle le remarque, et `zc fonds suivre` reporte le changement dans `plan.md` et dans les fichiers de suivi, après votre accord. L'agent vous propose ensuite une définition pour chaque thème nouveau. Un thème qui dépasse le seuil réglé dans `config.toml` (`seuil_sous_theme`) est signalé. Si vous voulez le découper, l'agent lit tous ses titres (`zc fonds titres`) et propose des sous-thèmes, seulement si un découpage net s'en dégage.

Une routine possible consiste à trier l'Inbox chaque semaine et à demander à l'agent où en est la bibliothèque une fois par mois.

## Tenir des fiches à l'écart

Si certaines références ne doivent pas être lues par l'agent (dossiers personnels, travaux sous embargo), ouvrez `config.toml` avec un éditeur de texte et complétez la section `[confidentialite]` :

```toml
[confidentialite]
tags_exclus = ["_privé"]
collections_exclues = ["Fonds/Personnel"]
```

Une fiche qui porte l'un de ces tags (majuscules ou non), ou qui est rangée dans l'une de ces collections ou leurs sous-collections, n'apparaît plus que par sa clé, avec ses pièces jointes, ses notes et ses annotations, suivie de « (fiche confidentielle) », dans tout ce que `zc` écrit (audit, suivi, rapports). Elle n'est jamais cherchée par son titre chez les services de métadonnées. Elle reste traitée, ses doublons sont fusionnés et son DOI vérifié. Quand une décision la concerne, l'agent vous demande de la regarder vous-même dans Zotero. Le tag peut aussi être posé sur une seule pièce jointe ou une seule note. Les plans (`plans/*.json`) et le journal (`journal/`) gardent en revanche les valeurs complètes, dont `zc` a besoin pour appliquer et annuler, et l'agent a pour consigne de ne jamais les ouvrir.

## Fichiers et sauvegardes

Zotero peut synchroniser vos PDF par zotero.org, par un serveur WebDAV, ou pas du tout. `zc` le lit dans les réglages de Zotero et en tient compte au point 5 de l'audit. Avec WebDAV, un fichier absent du disque revient en général quand vous ouvrez la pièce jointe dans Zotero, qui le retélécharge depuis le serveur. Quel que soit votre choix, réglez Zotero pour qu'il télécharge les fichiers « au moment de la synchronisation » sur l'ordinateur où vous lancez `zc`. `zc` compare et renomme les fichiers présents sur le disque, et une copie complète est aussi la meilleure des sauvegardes.

`zc sauvegarder` range ses copies dans `Zotero-sauvegardes`, à côté du dossier Zotero, et n'en garde que deux. Ces copies doublent le dossier Zotero, que votre logiciel de sauvegarde garde déjà. Sur un Mac, `zc` les écarte de Time Machine. Partout, il dépose dans ce dossier un fichier `CACHEDIR.TAG`, que Borg (option `exclude_caches`), restic et tar (option `--exclude-caches`) savent reconnaître. Avec un autre logiciel, excluez ce dossier à la main.

Sauvegardez en revanche votre dossier de travail. Ses journaux permettent d'annuler une modification, et `plan.md` comme `suivi/` gardent vos décisions de classement.

## Mettre à jour zot-clean

```
uv tool upgrade zot-clean
cd ~/Zotero-travail
zc init --maj
```

La seconde commande remplace les consignes de l'agent et les guides des étapes par ceux de la nouvelle version. Elle ne touche ni à `config.toml`, ni à `.env`, ni à vos décisions, rapports et journaux.

## Quand zc refuse

`zc` refuse plutôt que de prendre un risque, et dit toujours pourquoi. Les refus les plus courants sont les suivants.

| Message | Que faire |
|---|---|
| Zotero est ouvert | Fermer Zotero, relancer `zc sauvegarder`, puis rouvrir Zotero. |
| Aucune sauvegarde de moins de 24 heures | Fermer Zotero et lancer `zc sauvegarder`. |
| Aucun essai de ce plan n'a réussi | Lancer d'abord `zc appliquer <plan> --essai` et vérifier le résultat dans Zotero. |
| Éléments pas encore synchronisés | Laisser Zotero ouvert et lancer sa synchronisation (flèche verte), puis relancer la commande. Quand c'est seulement Zotero qui n'a pas encore reçu les derniers changements du serveur, `zc` n'attend pas, il les lit sur zotero.org. Synchroniser quand même avant de vérifier quoi que ce soit dans Zotero. |
| Clé refusée par Zotero | Créer une nouvelle clé sur zotero.org (étape 4), puis relancer `zc init ~/Zotero-travail`. Il revérifie la clé enregistrée et, si Zotero la refuse, demande la nouvelle sans rien changer d'autre. |
| Élément(s) à clé invalide | Ne rien forcer. Ouvrir une [issue](https://github.com/deubelen/zot-clean/issues). |

Pour tout autre problème, ou une question, ouvrez une [issue](https://github.com/deubelen/zot-clean/issues) en joignant le message affiché, sans votre clé API ni les titres de vos références si elles sont confidentielles.

## Lexique

- **Agent.** Programme conversationnel qui travaille dans un dossier de votre ordinateur et peut lancer des commandes, avec votre accord (Claude Code, Codex).
- **API, clé API.** Porte d'entrée du serveur de Zotero pour les programmes. La clé est le laissez-passer qui permet à `zot-clean` de modifier votre bibliothèque.
- **Clé (d'une fiche).** Identifiant de huit caractères que Zotero donne à chaque fiche, par exemple `ABCD2345`.
- **Dossier de travail.** Dossier créé par `zc init`, où `zot-clean` garde sa configuration, ses rapports, ses plans et son journal.
- **Fonds.** Partie de la bibliothèque qui classe toutes les références par discipline et par thème. Voir [la méthode](methode.md).
- **Plan.** Liste des modifications qu'une étape propose, préparée sans rien toucher, accompagnée d'un rapport lisible.
- **Synchronisation.** Échange entre le Zotero de votre ordinateur et le serveur zotero.org. `zot-clean` écrit sur le serveur, et votre Zotero reçoit les changements en se synchronisant.
- **Terminal.** Fenêtre où l'on tape des commandes (Terminal sous macOS, PowerShell sous Windows).
