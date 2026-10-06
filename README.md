# zot-clean

*Mettre et garder de l'ordre dans sa bibliothèque Zotero.*

`zot-clean` s'adresse à celles et ceux que leur bibliothèque Zotero a dépassés (doublons, métadonnées incomplètes, collections en désordre, milliers de tags automatiques). Il aide à

1. **faire le ménage**, étape par étape, chaque modification étant simulée, essayée sur quelques fiches, puis journalisée pour pouvoir revenir en arrière ;
2. **garder l'ordre**, par un tri régulier des nouvelles références et un contrôle fait à chaque audit ;
3. **aller plus loin** (plus tard), avec des suggestions de textes qui manquent à un dossier et la production de notes.

Les tâches mécaniques passent par la commande `zc`. Les tâches de jugement (décider si deux fiches sont des doublons, concevoir un plan de classement, ranger une référence) se font avec un agent en ligne de commande, comme Claude Code ou Codex, qui s'appuie sur `zc` et sur les consignes livrées avec lui.

> **Version 0.3, en cours de mise au point.** Les huit étapes du nettoyage, le tri des nouvelles références et le contrôle régulier sont disponibles. L'outil n'a pas encore été essayé par d'autres que son auteur. Les choix de conception sont consignés dans [docs/decisions.md](https://github.com/deubelen/zot-clean/blob/main/docs/decisions.md).

## Ce qui est disponible

Les étapes se suivent de préférence dans l'ordre du tableau. Chacune peut s'interrompre et reprendre plus tard, l'avancement restant dans le dossier de travail.

| Étape | Commandes | Ce qu'elle fait |
|---|---|---|
| 0. Audit | `zc audit` | Douze contrôles en lecture seule, rapport daté dans `rapports/`. Dit aussi ce qui est apparu et ce qui est réglé depuis l'audit précédent. |
| 1. Méthode | `config.toml` | Relecture des conventions de la méthode par défaut (`methode.md`) (racines, états de lecture, préfixes), à adapter au besoin. Rien n'est modifié dans Zotero. |
| Sauvegarde | `zc sauvegarder` | Copie du dossier Zotero, Zotero fermé. Exigée avant toute modification de masse. |
| 2. Doublons | `zc doublons chercher`, `planifier` | Repère les doublons, que l'on juge avec l'agent, puis les fusionne à la manière de Zotero. |
| 2. PDF identiques | `zc pieces chercher`, `planifier` | Met à la corbeille les copies en trop d'un même PDF ou les rattache à la bonne fiche, sans jamais perdre une copie annotée. |
| 3. Métadonnées | `zc metadonnees identifiants`, `types`, `completer` | Corrige les DOI et les types de fiche, complète les champs vides par Crossref, OpenAlex, la BnF, le Sudoc et Open Library. Une valeur déjà présente n'est jamais remplacée. |
| 4. Plan du fonds | `zc fonds inventaire`, `valider` | Propose avec l'agent un plan de classement (disciplines, thèmes), à valider dans `plan.md`. Rien n'est modifié dans Zotero. |
| 5. Rangement | `zc fonds planifier`, `a-ranger` | Transforme les collections d'après le plan validé et répartit les fiches, en plusieurs passes. |
| 6. Tags | `zc tags inventaire`, `planifier` | Retire les tags automatiques et les mots-clés importés, ramène les variantes à une seule forme et les états de lecture à ceux de la méthode, tire des concepts des tags existants. |
| 7. Clés de citation | `zc cles planifier` | Avec Better BibTeX, départage les clés de citation en double et range dans le champ « Clé de citation » celles restées dans Extra. Une clé unique n'est jamais changée. |
| 8. Noms des fichiers | `zc noms planifier` | Renomme le fichier principal de chaque fiche d'après le modèle de noms réglé dans Zotero (par défaut « Auteur - Année - Titre »). Le nouveau nom passe par zotero.org, et chaque Zotero renomme le fichier à sa synchronisation suivante. |
| Gestion, tri | `zc inbox preparer`, `planifier` | Trie les nouvelles références (Inbox et hors fonds) en un seul plan, avec doublons, métadonnées, rangement dans un thème, tags d'après les règles de l'étape 6, clés de citation et noms de fichiers. |
| Gestion, contrôle | `zc audit`, `zc fonds suivre`, `zc fonds titres` | Dit ce qui a changé depuis l'audit précédent, reporte dans `plan.md` les thèmes créés, renommés ou déplacés dans Zotero, aide à découper un thème trop gros. |

S'y ajoutent `zc voir`, qui montre une fiche en entier pour juger un cas, ainsi que `zc appliquer`, `zc annuler` et `zc journal`, décrites plus bas. `zc --help` et `zc <commande> --help` donnent le détail des options.

## Comment l'outil modifie la bibliothèque

Aucune commande ne modifie la bibliothèque directement. Chaque étape prépare d'abord un **plan**, accompagné d'un rapport lisible qui dit fiche par fiche ce qui va changer. Ensuite

- `zc appliquer <plan> --essai` applique les premiers groupes seulement, pour vérifier le résultat dans Zotero ;
- `zc appliquer <plan> --tout` applique le reste, et seulement si l'essai a eu lieu et qu'une sauvegarde de moins de 24 heures existe ;
- chaque modification est inscrite dans un journal, et `zc annuler` prépare le plan qui la défait.

Les écritures passent par l'API web de Zotero, jamais par la base locale, pour ne pas abîmer la synchronisation. Ces garde-fous sont dans le code et ne dépendent pas de la prudence de l'agent.

## Installation

Le guide pas à pas, `guide.md`, que `zc init` copie dans le dossier de travail avec `methode.md`, détaille chaque étape, de l'ouverture d'un terminal au premier nettoyage, sous macOS comme sous Windows. Il faut

- Zotero 7 ou une version plus récente, installé sur l'ordinateur ;
- un compte zotero.org avec la synchronisation activée, puisque `zc` écrit dans la bibliothèque par le serveur de Zotero ;
- [uv](https://docs.astral.sh/uv/getting-started/installation/), qui installe `zot-clean` et, au besoin, le Python qu'il demande (3.11 ou plus récent) ;
- pour les étapes de jugement, un agent en ligne de commande, comme [Claude Code](https://claude.com/claude-code) ou [Codex](https://openai.com/codex/).

L'étape 7 (clés de citation) demande en plus Zotero 8 et l'extension [Better BibTeX](https://retorque.re/zotero-better-bibtex/) 8, ou des versions plus récentes. Les autres étapes s'en passent.

L'installation se fait depuis GitHub.

```
uv tool install git+https://github.com/deubelen/zot-clean
```

Pour mettre l'outil à jour, lancer `uv tool upgrade zot-clean`, puis `zc init --maj` dans le dossier de travail. Cette seconde commande remplace les consignes de l'agent, le guide et la méthode par ceux de la nouvelle version, sans toucher à la configuration ni aux décisions déjà prises.

## Premiers pas

```
zc init ~/Zotero-travail     # crée le dossier de travail, demande la clé API de Zotero
cd ~/Zotero-travail
zc audit                     # état de la bibliothèque, rapport dans rapports/
```

`zc init` explique comment créer la clé API sur zotero.org. Mieux vaut la saisir soi-même dans le terminal, sans passer par l'agent. L'audit ne modifie rien. Il lit une copie temporaire de la base de Zotero, effacée après usage.

La méthode par défaut (`methode.md`) explique l'organisation proposée (Inbox, projets, fonds par disciplines et thèmes, archives) et comment l'adapter dans `config.toml`.

Pour la suite, ouvrir Claude Code, Codex ou un autre agent dans le dossier de travail et lui demander où en est la bibliothèque. Il y trouve ses consignes (`AGENTS.md`) et un guide pour chaque étape (`.agents/skills/`). Il lance l'audit, le résume et propose un ordre de travail. Il demande votre accord avant chaque application.

## Confidentialité

Les commandes `zc` travaillent en local. Elles ne sortent de l'ordinateur que pour écrire dans Zotero par son API et pour interroger les sources de métadonnées (Crossref, OpenAlex, BnF, Sudoc, Open Library), par identifiant ou par titre.

Quand un agent vous aide, les titres, résumés et notes qu'il lit sont transmis à son fournisseur (Anthropic, OpenAI…). Pour tenir certaines fiches à l'écart, déclarer dans `config.toml` des tags (par exemple `_privé`) ou des collections à exclure. Ces fiches restent traitées (leurs doublons sont fusionnés, leur DOI vérifié), mais l'audit, les fichiers de suivi et les rapports ne les désignent que par leur clé, suivie de « (fiche confidentielle) ». Elles ne sont jamais cherchées par leur titre chez les services de métadonnées. Pour décider à leur sujet, l'agent vous demande de les regarder vous-même dans Zotero.

Seule la bibliothèque personnelle est nettoyée. Les bibliothèques de groupe ne sont pas modifiées.

## Licence

MIT, voir le fichier `LICENSE`.
