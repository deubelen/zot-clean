# Banc d'essai du pilote (D237)

Le banc fait tourner le vrai `zc` sur une bibliothèque synthétique, sans compte Zotero, sans application Zotero et sans réseau. Un agent sans contexte y mène un nettoyage complet comme sur une vraie bibliothèque. Il tape `zc …` dans un dossier de travail, lit les rapports et les fichiers de `suivi/`, et demande à l'utilisateur les gestes que `zc` ne fait pas (fermer Zotero, synchroniser…). Celui qui joue l'utilisateur fait ces gestes avec `gestes/banc`.

## Ce que contient un banc

- `Zotero/` est le dossier de données (`zotero.sqlite` au schéma de Zotero 10, `storage/` avec de petits PDF lisibles).
- `profil-zotero/` est le profil de Zotero (langue de l'interface, Better BibTeX 9 actif, téléchargement des fichiers à la demande).
- `serveur.json` garde l'état du faux zotero.org (faux serveur des tests, `tests/fake_server.py`), et `sources.json` ce que savent les faux Crossref, OpenAlex, doi.org, BnF, Sudoc et Open Library (`tests/fake_sources.py`).
- `bin/zc` lance le vrai `zc` sur le banc, `gestes/banc` joue les gestes de l'utilisateur.
- `travail/` est le dossier de travail écrit par le vrai `zc init` (clé API factice déjà enregistrée, adresse de contact laissée vide).

La bibliothèque compte une centaine de fiches inventées (sciences humaines et sociales), en désordre pour que chaque étape ait à faire. On y trouve des doublons sûrs et douteux, des PDF identiques, des DOI absents, mal formés ou faux, des types erronés, des champs vides que les sources savent remplir, un arbre de collections numérotées avec un fourre-tout (« Divers » ou « Misc »), des tags automatiques et importés, des états venus d'autres habitudes, des clés de citation en double ou restées dans Extra, des PDF mal nommés, des fiches récentes hors de toute collection et une fiche confidentielle (`_privé` ou `_private`). Les racines de la méthode (Fonds, Projets, Inbox…) n'existent pas, le nettoyage les crée.

## Créer un banc

Depuis la racine de l'atelier, avec l'environnement de développement :

```sh
uv run python outils/pilote/banc.py create /Users/Shared/bancs/pilote-fr --library-language fr --seed 1
```

`--library-language` vaut `fr` ou `en`, `--seed` change les titres et la répartition des cas. La création prend moins d'une seconde. `bin/zc` appelle le Python qui a créé le banc, par son chemin, et se recrée avec le banc si cet environnement change.

Le banc se place hors du dossier personnel, ou ailleurs pourvu qu'aucun dossier parent ne contienne un `AGENTS.md` ou un `CLAUDE.md`. L'agent les lirait en plus de ceux du dossier de travail, et le dossier personnel de l'auteur en a un, écrit pour sa propre bibliothèque.

## Lancer un agent sur le banc

L'agent travaille dans `travail/`, avec `bin/` en tête du PATH, et ne voit pas `gestes/`.

```sh
cd /Users/Shared/bancs/pilote-fr/travail
PATH="/Users/Shared/bancs/pilote-fr/bin:$PATH" claude
```

On lui parle comme un utilisateur (« où en est ma bibliothèque ? », puis « nettoyons-la »). Il trouve seul `AGENTS.md` et les skills. Les quatre combinaisons du pilote croisent la langue de la bibliothèque (`--library-language`) et celle de la conversation.

## Gestes de l'utilisateur

`gestes/banc` se lance depuis n'importe quel dossier (`/Users/Shared/bancs/pilote-fr/gestes/banc sync`), il connaît son banc.

| Geste demandé par l'agent | Commande |
|---|---|
| Fermer Zotero (avant `zc backup`) | `gestes/banc zotero close` |
| Rouvrir Zotero (il synchronise en s'ouvrant) | `gestes/banc zotero open` |
| Synchroniser Zotero (flèche verte) | `gestes/banc sync` |
| Better BibTeX › Fill (clés manquantes) | `gestes/banc bbt-fill` |
| Changer un réglage de Zotero | `gestes/banc zotero pref <nom> <valeur>` |
| Modifier une fiche ou une collection à la main | `gestes/banc edit <clé> champ=valeur …` |
| Créer une collection (l'Inbox, par exemple) | `gestes/banc new-collection Inbox` |
| Enregistrer de nouvelles références avec le connecteur | `gestes/banc add-items -n 3` |
| Laisser Zotero synchroniser seul (ou plus) | `gestes/banc zotero autosync on` (ou `off`) |
| Voir où en est le banc | `gestes/banc status` |

Deux réglages servent aux skills. `extensions.zotero.automaticTags false` décoche l'ajout automatique des tags (étape 6), que `add-items` respecte. `extensions.zotero.sync.storage.downloadMode.personal on-sync` fait télécharger à la synchronisation suivante le fichier qui n'est que sur zotero.org.

La synchronisation réécrit la bibliothèque de `zotero.sqlite` d'après le faux serveur, en gardant les identifiants locaux, et renomme sur le disque les fichiers dont le nom a changé (étape 8). Elle demande Zotero ouvert.

## Limites

- Le faux serveur ne couvre que ce que `zc` utilise de l'API. Il refuse comme zotero.org un champ ou un rôle étranger au type de la fiche, mais ne contrôle ni la clé API ni les droits, et ne connaît pas les relations entre fiches au-delà de leur stockage.
- La synchronisation va seulement du serveur vers `zotero.sqlite`. Rien ne se modifie dans Zotero hors des gestes ci-dessus, et une modification locale non synchronisée n'existe pas.
- Par défaut, Zotero ne synchronise jamais seul, sauf à l'ouverture. C'est le cas le moins favorable, puisqu'une vraie installation reçoit vite les changements de fiches faits par l'API (les collections, pas toujours). `gestes/banc zotero autosync on` fait synchroniser le banc après chaque commande `zc`, Zotero ouvert, et `off` revient au défaut.
- Les sources de métadonnées sont déterministes et ne connaissent que les œuvres de la bibliothèque. Leur recherche retient les notices dont le titre recouvre la requête, sans le classement des vrais services.
- Better BibTeX n'agit que par `bbt-fill`, qui approche la formule `auth.lower + shorttitle(3,3) + year` sans la reproduire exactement.
- Zotero est « ouvert » ou « fermé » selon l'état du banc, et non d'après les processus de la machine. `zc backup` fait une vraie sauvegarde du dossier du banc (dans `Zotero-sauvegardes/`), sans toucher à Time Machine.
- Toute connexion réseau du processus `zc` est refusée et notée dans `reseau-bloque.log`, à la racine du banc.
