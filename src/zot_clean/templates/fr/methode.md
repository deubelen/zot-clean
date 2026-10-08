# La méthode par défaut

`zot-clean` propose une façon d'organiser une bibliothèque Zotero. Elle vient de la pratique, celle d'une bibliothèque réorganisée puis tenue en ordre au fil des mois. Elle n'est pas imposée, puisque chaque convention se renomme ou se désactive dans `config.toml`. Cette page dit ce que propose la méthode, pourquoi, et comment la changer. Les noms proposés ici (`Fonds`, `Projets`, `1 à lire`…) sont ceux d'une bibliothèque déclarée française. Une bibliothèque déclarée anglaise reçoit leurs équivalents anglais. La langue se fixe à `zc init` (`--library-language`) et se lit avec `zc config show`.

L'idée générale tient en une phrase. **Chaque référence a une place stable dans un fonds classé par disciplines et par thèmes, et tout le reste (projets en cours, archives, lectures) n'en est qu'une vue.**

## Quatre collections racines

À la racine de la bibliothèque, quatre collections seulement.

| Racine | Rôle |
|---|---|
| `Inbox` | Les références qui viennent d'arriver, en attente de tri. |
| `Projets` | Une sous-collection par projet en cours (un cours, un article, un livre), éventuellement regroupées par type. |
| `Fonds` | Le classement permanent, par discipline puis par thème. |
| `Archives` | Les projets terminés. |

**Pourquoi.** Une bibliothèque se désorganise quand le classement de fond et le travail en cours se mélangent. On crée une collection pour un article, puis une autre pour un cours, et au bout de quelques années personne ne sait plus où chercher. Séparer ce qui dure (le fonds) de ce qui passe (les projets) règle la question. Les racines n'ont pas de numéros (`00 Inbox`, `40 Fonds`…), qui alourdissent les noms pour un gain mince.

**Changer.** Dans `config.toml`, section `[methode]`, les réglages `inbox`, `projets`, `fonds` et `archives`. On peut avoir plusieurs racines de projets, par exemple `projets = ["Cours", "Articles"]`, ou se passer d'une racine en lui donnant un nom vide (`archives = ""`).

## Toute référence a sa place dans le fonds

Une fiche Zotero peut appartenir à plusieurs collections sans être copiée. La méthode s'en sert. Chaque référence est rangée dans un thème du fonds, et peut en plus figurer dans un ou plusieurs projets.

**Pourquoi.** Une référence qui ne vit que dans un projet se perd quand le projet se termine. Si elle est aussi dans le fonds, archiver le projet ne fait rien perdre, et la référence se retrouve par son thème des années plus tard. Une fiche absente du fonds signale donc un oubli, que le rangement repère et vous propose de placer.

## Un fonds à deux niveaux, parfois trois

Le fonds a deux niveaux, la discipline (Philosophie, Sociologie…) puis le thème (Philosophie de l'esprit, Éthique…). Un troisième niveau, le sous-thème, n'est proposé que lorsqu'un thème dépasse 40 références.

**Pourquoi.** Créer des sous-thèmes à l'avance produit des collections de trois fiches, où l'on hésite à chaque rangement. Le fonds se creuse plutôt là où il grossit. L'audit signale une profondeur de plus de trois niveaux.

La liste des disciplines et des thèmes n'est pas fournie. Elle se construit pendant le nettoyage (étape 4), à partir de vos collections et de vos tags existants. L'agent vous propose un plan, vous le discutez, et une fois validé il est écrit dans `plan.md`, avec une définition pour chaque thème (champs `Inclut` et `Exclut`). Ces définitions servent ensuite à ranger les nouvelles références sans hésiter.

**Changer.** `seuil_sous_theme` (40 par défaut) et `profondeur_max` (3).

## `plan.md` suit Zotero

Pendant le nettoyage, `plan.md` est le plan validé qui guide le rangement. Ensuite, c'est Zotero qui fait foi. Vous pouvez créer un thème directement dans Zotero, `plan.md` ne sert qu'à garder les définitions et les consignes de rangement. Le contrôle régulier, fait à chaque audit, signale les thèmes sans définition et les définitions sans thème.

**Pourquoi.** Si un fichier commandait Zotero, chaque geste fait dans Zotero (créer un thème au vol, déplacer une collection) deviendrait une erreur à corriger. L'outil doit suivre vos habitudes, pas l'inverse.

## Peu de tags, en familles

La méthode n'utilise que quelques familles de tags.

| Famille | Exemples | Usage |
|---|---|---|
| États de lecture | `1 à lire`, `2 en cours`, `3 lu` | Où vous en êtes avec un texte. Les chiffres les gardent dans l'ordre. |
| Marques | `★ essentiel`, `papier` | Les textes de référence, les exemplaires imprimés. |
| Concepts | `#norme`, `#émotion` | Des notions qui traversent les thèmes du fonds. |
| Techniques | `_privé`, `_à vérifier` | Des marques de travail, que l'on peut filtrer. |

Les tags automatiques, c'est-à-dire les mots-clés ajoutés par les éditeurs et les bases de données, sont supprimés au nettoyage (étape 6).

**Pourquoi.** Les tags automatiques se comptent vite par milliers, en plusieurs langues et sous plusieurs formes, et rendent le sélecteur de tags inutilisable. Le classement par thème se fait par les collections. Les tags servent à ce que les collections ne savent pas faire, c'est-à-dire l'état d'une lecture et les notions transversales.

**Changer.** `etats`, `autres_tags`, `prefixe_concept` (`#`) et `prefixe_technique` (`_`).

## Clés de citation

Si l'extension [Better BibTeX](https://retorque.re/zotero-better-bibtex/) est installée, chaque référence reçoit une clé de citation fixe, du type `durandMoraleAntique1938` (auteur, premiers mots du titre, année), gardée dans le champ « Clé de citation » de Zotero. Elle sert à citer depuis Markdown ou LaTeX. Sans Better BibTeX, ce contrôle est désactivé par `zc init`.

**Pourquoi.** Une clé recalculée à chaque export change quand on corrige une fiche, et casse les citations déjà écrites. Une clé fixée dans Zotero ne bouge plus.

**Changer.** `cles_citation = false` pour se passer de ce contrôle.

## Noms des fichiers

Les PDF sont nommés `Auteur - Année - Titre`, par le renommage automatique de Zotero (Réglages › Général › Personnaliser les noms de fichiers).

**Pourquoi.** Un PDF nommé `1-s2.0-S0010027708.pdf` ne dit rien hors de Zotero. Un nom lisible permet de retrouver un fichier depuis l'explorateur ou une tablette.

**Changer.** Le modèle se règle dans Zotero (Réglages › Général › Personnaliser les noms de fichiers), et l'audit le lit dans la bibliothèque. `Auteur - Année - Titre` est le modèle par défaut de Zotero, qui écrit `Auteur - Titre` pour une référence sans date, `A et B` pour deux auteurs et `A et al.` au-delà. La conjonction (« et », « and ») suit la langue de Zotero. `zot-clean` la déduit des noms existants, et `conjonction` dans `config.toml` la fixe si besoin.

## Ce qui ne fait pas partie de la méthode

`zot-clean` ne nettoie que votre bibliothèque personnelle. Les bibliothèques de groupe ne sont jamais modifiées, puisqu'elles contiennent les fiches d'autres personnes.

Il ne modifie jamais le contenu des fichiers PDF. L'étape 8 en change seulement le nom, d'après le modèle réglé dans Zotero, et `zc undo` sait le remettre. Seules les fiches, les notes, les pièces jointes (en tant qu'éléments de Zotero) et les collections changent, toujours par l'API de Zotero. Une fiche ou une pièce jointe mise à la corbeille y reste trente jours, comme si vous l'aviez supprimée dans Zotero.
