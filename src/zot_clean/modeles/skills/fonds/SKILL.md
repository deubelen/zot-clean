---
name: fonds
description: Proposer avec l'utilisateur le plan du fonds de sa bibliothèque Zotero (disciplines, thèmes, sous-thèmes) à partir des collections et des tags existants, le faire valider dans plan.md, décider du sort de chaque ancienne collection (étape 4 du nettoyage), puis ranger les fiches d'après ce plan (étape 5). À utiliser quand l'utilisateur parle de plan de classement, de réorganiser ou ranger ses collections, de disciplines ou de thèmes, ou quand l'audit signale une structure de collections à revoir.
---

# Plan du fonds

L'étape 4 ne modifie rien dans Zotero. Elle aboutit à deux fichiers validés. `plan.md` décrit le fonds (disciplines, thèmes, sous-thèmes, avec une définition pour chacun) et survivra au nettoyage. `suivi/fonds.toml` décrit la transition, c'est-à-dire le sort de chaque ancienne collection et les tags qui désignent un thème. L'étape 5, le rangement, créera les collections et y déplacera les références d'après ces deux fichiers. Ils font foi, et l'agent les présente toujours ensemble.

Les doublons (étape 2) doivent être traités avant le rangement. Si l'audit en signale encore beaucoup, le dire à l'utilisateur, sans bloquer l'étape 4.

## Déroulé

1. **Inventorier.** Lancer `zc fonds inventaire`. Lire le rapport `rapports/fonds-inventaire-<date>.md` (arbre des collections avec effectifs, références partagées, tags les plus portés et échantillon de titres, puis tags thématiques et tags qui reviennent ensemble), et `suivi/fonds.toml`. Terminé quand la commande a donné le nombre de collections sans sort. Si une collection a disparu depuis le dernier inventaire, le signaler à l'utilisateur.

2. **Proposer l'arbre.** Proposer l'arbre entier d'un coup, sans définitions, avec pour chaque discipline et chaque thème le nombre de références prévu et les anciennes collections ou tags d'où il vient. Partir de ce qui existe (collections, tags qui reviennent ensemble, arbre de `Fonds` s'il y en a un) et suivre les critères ci-dessous. Signaler les anciennes collections qu'on propose de répartir, celles qui semblent être des projets et celles qu'on propose de dissoudre. Pour une collection du fonds qui dépasse `seuil_sous_theme`, l'inventaire donne tous les titres. Proposer des sous-thèmes seulement si la division est nette, et le dire quand elle ne l'est pas. Laisser l'utilisateur renommer, fusionner, scinder, déplacer. Terminé quand l'utilisateur approuve l'arbre.

3. **Écrire le plan, discipline par discipline.** Pour chaque discipline, rédiger dans `plan.md` la définition de la discipline et de chacun de ses thèmes, avec les lignes « Inclut » et « Exclut » là où la frontière avec un thème voisin prête à hésitation. Remplir dans `suivi/fonds.toml` le sort des anciennes collections qui s'y rattachent. Montrer à l'utilisateur la discipline et les sorts correspondants, corriger selon ses remarques, puis passer à la suivante. Terminé quand chaque discipline a été vue et chaque ancienne collection a un sort.

4. **Relier des tags.** Proposer, dans la table `tags` de `suivi/fonds.toml`, les tags thématiques qui désignent clairement un thème du plan (« perception visuelle » vers `Psychologie/Perception`). Ils serviront d'indice pour ranger à l'étape 5 les références sans collection ou à répartir. Un tag ambigu ou transversal reste hors de la table. Le sort des tags eux-mêmes se règle à l'étape 6. Terminé quand l'utilisateur a approuvé la table.

5. **Contrôler.** Lancer `zc fonds valider`. Corriger chaque erreur (nom en double sous un même parent, niveau de trop, nom d'une racine, chemin qui ne mène à rien, collection sans sort) dans le fichier indiqué, puis relancer. Les avertissements (thème sans définition, collection à répartir sans candidat) se présentent à l'utilisateur, qui décide d'y remédier ou non. Terminé quand la commande ne signale plus d'erreur.

6. **Valider.** Présenter à l'utilisateur le plan final (arbre et effectifs prévus) et le résumé des sorts (combien de collections deviennent un thème, sont réparties, vont aux projets ou aux archives, sont dissoutes ou restent hors plan). Après son accord explicite, lancer `zc fonds valider --enregistrer`. Terminé quand la commande confirme la validation.

Après la validation, retoucher une définition ne demande rien. Changer la structure (un thème de plus ou de moins, un sort, une cible, un tag relié) annule la validation, `zc fonds valider` montre alors ce qui a changé, et il faut revalider avant le rangement.

## Étape 5, rangement

Le rangement applique le plan validé. Il transforme le classement sur place, c'est-à-dire que les collections gardent leur clé et sont renommées ou déplacées, que seules les collections manquantes sont créées, et que les collections fusionnées ou dissoutes vont à la corbeille de Zotero. Il se fait en plusieurs passes. `zc fonds planifier` compare chaque fois l'état réel de la bibliothèque à l'état visé et ne planifie que la différence, on peut donc le relancer sans crainte.

1. **Contrôler.** Lancer `zc fonds valider`. Le plan doit être validé dans son état actuel, sinon `planifier` refuse. Si la structure a changé, montrer les changements à l'utilisateur et, après son accord, `zc fonds valider --enregistrer`.

2. **Consignes de l'utilisateur.** Quand l'utilisateur demande de déplacer ou supprimer des fiches précises (« les références de tel auteur vont dans tel thème », « ces manuels à la corbeille »), l'écrire dans `suivi/rangement.toml`, avec `source = "consigne"` et `decision = "accepter"`. Si le fichier n'existe pas encore, `zc fonds a-ranger` le crée. Son en-tête rappelle les champs et donne une entrée d'exemple à recopier. Pour trouver les clés, s'appuyer sur les rapports (`zc fonds a-ranger`, inventaire).

3. **Première passe, la structure.** Lancer `zc fonds planifier`. Lire le rapport `.md` et le résumer à l'utilisateur, à savoir les collections créées, renommées, déplacées, fusionnées, mises à la corbeille, le nombre de fiches rangées, les points « À regarder » et le nombre de fiches qui n'auront aucune place dans le fonds. Terminé quand l'utilisateur a approuvé ce plan-là.

4. **Sauvegarder, essayer, appliquer.** Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero et lancer `zc sauvegarder`. Puis `zc appliquer <plan> --essai`, qui applique les premiers groupes, c'est-à-dire les premières collections complètes dans l'ordre de l'arbre. Les vérifier soi-même avec `zc voir` sur quelques fiches rangées (collections de chacune), le dire à l'utilisateur, puis `zc appliquer <plan> --tout`. Une commande interrompue se relance telle quelle.
   - Zotero ne récupère pas toujours seul les collections créées, renommées, déplacées ou mises à la corbeille par l'API, même ouvert, alors qu'il reçoit vite les changements de fiches. `zc` n'en a pas besoin, il lit sur zotero.org ce que Zotero n'a pas encore reçu. À la fin de l'étape, demander à l'utilisateur de lancer une fois la synchronisation à la main (flèche verte en haut à droite), pour qu'il retrouve ses collections à jour dans Zotero.

5. **Répartir et placer, par paquets.** Lancer `zc fonds a-ranger`, qui écrit dans `rapports/fonds-a-ranger-<date>.md` les fiches des collections à répartir et les fiches sans place dans le fonds, par paquets de 50, avec les définitions des cibles candidates. Les tags reliés à un thème y ont déjà produit des propositions (`source = "tag"`).
   - Pour chaque paquet, proposer une cible aux seules fiches dont la place est nette, d'après les définitions (Inclut, Exclut). Une fiche qui convient au thème où elle est déjà y reste, sans entrée.
   - Écrire les propositions dans `suivi/rangement.toml`, une table `[[fiche]]` par fiche, comme l'exemple de l'en-tête, avec `cle`, `action = "déplacer"`, `cible` (chemin du plan), `depuis` (la clé indiquée pour le paquet), `source = "agent"`, `decision = ""`, `note`.
   - Le paquet « sans place dans le fonds » n'a pas de clé `depuis`, qui reste alors vide. Pour une fiche hors de toute collection, « déplacer » et « ajouter » reviennent au même. Une fiche rangée dans un projet ou aux archives reçoit « ajouter », pour y rester.
   - Une fiche n'apparaît que dans un seul paquet et ne reçoit qu'une entrée, sauf une seconde entrée « ajouter » pour une seconde place voulue.
   - Présenter le paquet à l'utilisateur, en quelques lignes par cible. S'il l'approuve, passer ses entrées à `decision = "accepter"`. S'il en corrige, écrire ses choix, `"refuser"` pour une proposition écartée.
   - Pour une fiche douteuse, `zc fonds a-ranger --resume <clé>` donne son résumé. Ne le demander qu'au cas par cas.
   - Une fiche qui a sa place dans deux thèmes reçoit `action = "ajouter"` pour le second.

   - Quand tous les paquets d'une collection sont jugés et appliqués, lancer `zc fonds a-ranger --examinees <clé>`. Les fiches laissées en place ne sont plus présentées, seules celles qui y arrivent ensuite le seront. Une collection à répartir qui n'est pas un chemin du plan (un ancien fourre-tout) va alors à la corbeille à la passe suivante de `zc fonds planifier`. Les fiches laissées y gardent leurs autres collections, et celles qui n'en ont aucune dans le fonds reviennent parmi les fiches sans place. Le dire à l'utilisateur en présentant ce plan-là.

   - Une fiche sans place dans le fonds que l'utilisateur, après l'avoir vue, préfère laisser hors du fonds (titre trop vague pour la ranger, fiche gardée seulement dans un projet ou aux archives), se note par `zc fonds a-ranger --laisser <clé>…`. Elle ne revient plus dans `zc fonds a-ranger`, `zc inbox preparer` ni le contrôle 12 de l'audit, qui la comptent seulement, tant qu'elle reste dans les mêmes collections. Ne l'utiliser qu'après l'accord de l'utilisateur, jamais pour une fiche simplement pas encore jugée. Si la fiche a une entrée en attente ou acceptée dans `suivi/rangement.toml`, passer d'abord cette entrée à `"refuser"`. Pour qu'elle soit de nouveau présentée, retirer son entrée de `suivi/rangement-laissees.json`.

   Terminé quand l'utilisateur a jugé les paquets qu'il voulait traiter dans la séance. Les autres fiches restent simplement où elles sont.

6. **Passes suivantes.** Zotero peut rester ouvert pendant toute la séance. Relancer `zc fonds planifier`, qui ne porte plus que sur les décisions nouvellement acceptées, puis même suite qu'au point 4. Recommencer 5 et 6 au rythme de l'utilisateur.

7. **Racines.** Quand l'utilisateur le demande, relire avec lui la table `[racines]` de `suivi/fonds.toml` (nouveaux noms des racines, sans numéros), puis `zc fonds planifier --racines`. Les renommages sont les derniers groupes du plan. Après l'application complète, mettre à jour les noms dans `config.toml` (`[methode]`) et le titre de la section du fonds dans `plan.md` (`# Fonds`). `zc` refuse de continuer tant que ce n'est pas fait, en le disant. Lancer ensuite `zc fonds valider`, qui reporte les nouveaux noms dans `suivi/fonds.toml`, résumer les changements à l'utilisateur (seuls les noms des racines doivent changer), puis `--enregistrer`.

8. **Contrôler.** Lancer `zc audit` et dire à l'utilisateur ce qui reste. L'étape est finie quand `zc fonds planifier` n'a plus rien à faire et que `suivi/rangement.toml` n'a plus de proposition en attente. `plan.md` suit ensuite Zotero, un thème ajouté dans Zotero s'y ajoute avec sa définition.

Pour revenir sur une passe, lancer `zc annuler <plan>`, résumer le rapport d'annulation, puis l'appliquer comme au point 4. Une collection créée par la passe va alors à la corbeille.

## Forme des fichiers

`plan.md` se trouve à la racine du dossier de travail. La hiérarchie vit sous le titre `# Fonds` (le nom de la racine du fonds dans `config.toml`), avec `##` pour une discipline, `###` pour un thème et `####` pour un sous-thème. Chaque titre donne le nom exact de la future collection. Les autres sections de premier niveau sont libres, et `# Concepts` sera remplie à l'étape 6.

```markdown
# Fonds

## Psychologie

Étude de l'esprit et du comportement humains, par l'expérience et l'observation.

### Perception

Vision, audition, attention et leurs illusions.
Inclut : psychophysique, perception des couleurs.
Exclut : neurophysiologie de la rétine (Biologie/Neurosciences).

## Philosophie

…

# Concepts
```

Dans `suivi/fonds.toml`, les chemins du plan s'écrivent sans la racine (`Psychologie/Perception`). L'en-tête du fichier rappelle les sorts possibles.
- `thème`, avec `cible`. L'ancienne collection devient ce thème, sous le même nom ou un autre. Plusieurs anciennes collections peuvent avoir la même cible, elles sont alors fusionnées.
- `répartir`, avec `candidats`. Collection fourre-tout, dont les références iront une à une dans les thèmes candidats à l'étape 5. Une fois examinée (`zc fonds a-ranger --examinees`), elle va à la corbeille, sauf si elle est déjà à un chemin du plan. `candidats` ne sert qu'à ce sort, il est ignoré pour les autres.
- `projet`, avec `cible`. Collection liée à un cours, un article, un livre en cours. `cible` commence par le nom d'une racine de projets déclarée dans `config.toml` (`projets`, par exemple `["Cours", "Articles"]`), suivi du nom du projet (`Articles/Revue de littérature`). Elle peut rester vide s'il n'y a qu'une racine de projets. Les références d'un projet reçoivent aussi une place dans le fonds (toute référence a sa place dans le fonds).
- `archives`, avec `cible` facultative. Classement ou projet terminé, gardé pour mémoire.
- `dissoudre`. Collection sans intérêt propre, mise à la corbeille, dont les références gardent leurs autres collections.
- `hors plan`. Collection laissée telle quelle.

Les collections déjà sous une racine de projets ou sous `Archives` ont un sort prérempli. Ne les revoir que si l'utilisateur le demande. Celles de `Fonds` sont des propositions de thèmes, à garder, renommer ou fusionner. Une collection exclue par le filtre de confidentialité est préremplie « hors plan » et absente de l'inventaire. Ne pas chercher à en savoir plus, l'utilisateur peut changer son sort lui-même.

## Critères d'un bon plan

- Des disciplines qui sont celles de l'utilisateur, telles qu'il les pratique et les enseigne, plutôt qu'une classification de bibliothèque plaquée (Dewey, CDU). Entre 3 et 12 disciplines environ.
- Un thème se justifie par le nombre de références qu'il recevra. En dessous de 5 références prévues, le fusionner avec un voisin, sauf si l'utilisateur prévoit de le développer.
- Deux niveaux par défaut (discipline, thème). Un sous-thème seulement quand un thème dépasse le seuil de `seuil_sous_theme` dans `config.toml` (40 références par défaut), et quand la division est nette.
- Des noms courts, en français sauf usage établi dans le domaine (« machine learning »), sans numéros ni préfixes de tri. Au singulier quand il sonne naturellement (« Mémoire », « Perception »), au pluriel sinon (« Méthodes qualitatives », « Relations internationales »). Proposer ces renommages avec le reste de la discipline, et ne les faire qu'avec l'accord de l'utilisateur.
- Aucun thème qui double un projet. Un cours ou un article en préparation est un projet, et ses références appartiennent en plus à des thèmes durables.
- Une définition qui permet de ranger une nouvelle référence sans hésiter. Elle dit ce que le thème couvre, et « Inclut » ou « Exclut » tranchent les cas limites entre voisins.
- Une ancienne collection fourre-tout (« Divers », « À trier », « Lectures ») se répartit plutôt qu'elle ne devient un thème.

Quand une proposition repose sur une supposition (un tag interprété, une collection dont l'échantillon est hétérogène), le dire à l'utilisateur et lui poser la question plutôt que trancher.
