---
name: metadonnees
description: Corriger les DOI et compléter les champs vides de la bibliothèque Zotero avec zc (étape 3 du nettoyage), et juger avec l'utilisateur les cas incertains. À utiliser quand l'utilisateur parle de métadonnées, de DOI, de champs manquants ou de fiches incomplètes, ou quand l'audit signale des métadonnées manquantes.
---

# Métadonnées

L'étape 3 se fait en trois sous-étapes, dans cet ordre, les identifiants (DOI et ISBN), les types de fiche, puis les compléments (champs vides). `zc` interroge Crossref et OpenAlex pour les articles, la BnF, le Sudoc et Open Library pour les livres, écrit dans le plan ce qui est certain, et range le reste dans `suivi/metadonnees.toml`. Ce fichier fait foi pour les décisions. L'agent aide l'utilisateur à juger les cas incertains.

## Déroulé

1. **Chercher les identifiants.** Lancer `zc metadonnees identifiants`. La première passe peut durer une demi-heure sur une grande bibliothèque, les suivantes quelques secondes. Si la commande signale une source mise de côté ou des recherches OpenAlex sautées, le dire à l'utilisateur. Terminé quand la commande a donné le nombre de cas à juger et, s'il y en a, le chemin d'un plan.

2. **Juger les cas.** Lire `suivi/metadonnees.toml`. Chaque cas y est précédé d'une ligne sur la fiche (clé, auteur, année, titre, type, revue ou ouvrage, DOI actuel), puis de ses propositions numérotées, chacune avec sa source, une note (titre, auteur, année, type, revue ou ouvrage, volume, pages, éditeur, similarité) et un avis, « concorde » ou ce qui diffère de la fiche (« titre 0.72, auteur »). `zc` a déjà trié les cas. `classe = "évident"` quand une seule proposition concorde en tout, son numéro étant dans `choix`, ou quand un DOI inconnu de doi.org n'a pas d'autre piste que son retrait (`doi_inconnu` à une seule proposition), et `classe = "douteux"` sinon.
   - Traiter les cas sans décision dans cet ordre : `doi_malforme`, `doi_inconnu` et `isbn_invalide`, puis `doi_discordant` et `isbn_discordant`, puis `doi_manquant` et `isbn_manquant`.
   - `zc` a déjà vérifié les évidents (le DOI proposé vient de Crossref ou d'OpenAlex, un DOI à retirer a été cherché sur doi.org). Les parcourir sans refaire ces vérifications, en relisant seulement la note et l'avis de chacun. Pour un douteux, lire l'avis de chaque proposition, puis `zc voir <clé>` et la résolution du DOI. Un évident qui ne résiste pas à la vérification passe dans les douteux, et un douteux dont l'avis s'explique (titre traduit, sous-titre propre à la fiche) peut devenir évident. Puis présenter deux groupes.
     - **Évidents.** Toutes les données concordent selon les critères ci-dessous (titre à la casse, la ponctuation ou un sous-titre près, premier auteur, année à un an près, même revue ou même ouvrage, même type) et l'identifiant se résout. Les présenter en un seul bloc, avec leur nombre, ce qui a été vérifié et une ligne par cas, que l'utilisateur peut parcourir. Une seule approbation suffit pour tout le bloc.
     - **Douteux.** Les autres. Les présenter par paquets de 10 au plus, regroupés par ce qui diffère (année, auteur, revue…), chacun avec une recommandation (le numéro de la proposition à retenir, ou refuser), une phrase de justification tirée des critères ci-dessous et ce qui a été vérifié.
   - Écrire les décisions par la commande, sans toucher au fichier. Bloc des évidents approuvé, `zc metadonnees accepter --evidents`, avec `--sauf <clés>` pour ceux que l'utilisateur a écartés. Douteux, `zc metadonnees accepter <clé>=<numéro> …` pour la proposition retenue et `zc metadonnees refuser <clé> …`. Quand une fiche a plusieurs cas (DOI et ISBN), viser chacun par son problème, `<clé>:<problème>=<numéro>` (`zc` donne les problèmes s'il en manque un). Un cas laissé en suspens n'a besoin de rien.
   - Sur demande explicite de l'utilisateur, refuser en une fois tous les cas restants d'un type.

   Terminé quand l'utilisateur a jugé les paquets qu'il voulait traiter maintenant. Les cas restants ne bloquent rien.

3. **Planifier.** Relancer `zc metadonnees identifiants`, qui reprend les cas acceptés dans son plan. Si la commande signale une erreur dans `suivi/metadonnees.toml`, corriger la ligne indiquée. Lire le rapport `.md` du plan et le résumer à l'utilisateur. Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

4. **Sauvegarder, essayer, appliquer.** Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero et lancer `zc sauvegarder`. Puis `zc appliquer <plan> --essai`, vérification des fiches de l'essai avec `zc voir`, dite à l'utilisateur, et `zc appliquer <plan> --tout`. Une commande interrompue se relance telle quelle.

5. **Types.** Lancer `zc metadonnees types`. Les changements sûrs vont au plan, les autres dans `suivi/metadonnees.toml` avec la sous-étape `types`. Les juger comme à l'étape 2, avec les critères ci-dessous. Relancer la commande pour obtenir le plan, puis même suite qu'à l'étape 4. `zc` ne propose un type qu'aux fiches qui ont un DOI connu des sources, aux fiches « Document » qui ressemblent à un livre connu et aux doublons à fusionner de types différents. Le rapport liste les fiches « Document » restées sans proposition. Leur type, comme celui de toute fiche mal typée sans DOI, se change à la main dans Zotero (menu « Type de document » de la fiche), geste à demander à l'utilisateur.

6. **Compléter.** Lancer `zc metadonnees completer`. Résumer le rapport, à savoir les champs remplis et leur nombre, les fiches sautées parce que leur DOI ou leur ISBN reste à juger, et les principales « valeurs différentes », laissées telles quelles. Si l'utilisateur veut imposer une valeur de la source, ou vider un champ faux, ajouter à la fin de `suivi/metadonnees.toml` un cas `forcer` complet, sur le modèle donné en tête du fichier, puis relancer. Le rapport compte alors à part les « valeurs imposées ». Ensuite, même suite qu'à l'étape 4 avec ce plan.

7. **Contrôler.** Lancer `zc audit` et dire à l'utilisateur ce qui reste (cas en attente, fiches sans auteur ou sans date, qui se corrigent à la main dans Zotero ou avec l'utilisateur).

Pour revenir sur un plan appliqué, lancer `zc annuler <plan>`, résumer le rapport d'annulation, puis suivre l'étape 4 avec le plan d'annulation.

## Critères de jugement

Accepter un candidat quand il désigne la même publication que la fiche, c'est-à-dire un titre identique à un sous-titre, une ponctuation ou une casse près, même premier auteur, même revue ou même ouvrage quand les deux sont connus, année égale à un an près.

Refuser un candidat qui désigne une autre publication, même proche :
- compte rendu du livre ou de l'article, erratum, réponse ou commentaire ;
- autre chapitre du même ouvrage ;
- autre édition, traduction, version abrégée ;
- type différent (livre pour un chapitre, article pour une communication).

Selon le problème :
- `doi_discordant`. Si la fiche est un chapitre et le DOI celui du livre, retenir le candidat du chapitre s'il y en a un, sinon retirer le DOI (proposition 1). Si la fiche et la source décrivent bien la même publication (titre traduit, titre abrégé dans Zotero), garder le DOI (proposition 2).
- `doi_inconnu` ou `doi_malforme`. Préférer un candidat dont le DOI ne diffère de l'actuel que d'un ou deux caractères, signe d'une faute de frappe. Sinon retirer le DOI. Un candidat dont la revue diffère de celle de la fiche reste douteux, même si le reste concorde. Le montrer à l'utilisateur avec les deux revues, l'une des deux étant fausse.
- `isbn_discordant`. L'ISBN est valide mais la notice trouvée porte un autre titre. Comparer avec `zc voir`. Si c'est bien le livre (titre traduit, titre de collection), garder l'ISBN (proposition 2). Sinon le retirer (proposition 1) ou retenir un candidat trouvé par titre, avec les critères de `isbn_manquant`.
- `doi_manquant`. Accepter seulement si les critères ci-dessus sont tous réunis.
- `isbn_manquant`. Plusieurs éditions sont souvent proposées. Retenir celle dont l'année et l'éditeur correspondent à ceux de la fiche. Si la fiche n'a ni l'un ni l'autre, demander à l'utilisateur quelle édition il possède ou cite, puisque les pages citées en dépendent.
- `isbn_invalide`. La proposition 1 garde les ISBN valides du champ (ou le retire s'il n'y en a aucun). Préférer un candidat dont l'ISBN ne diffère que d'un chiffre.
- `livre_possible`. Une fiche « Document » semble être un livre. Accepter seulement si titre, auteur et année concordent. Un document de travail, un rapport ou un polycopié reste un document.
- `type_different`. Accepter quand la source décrit bien la fiche sous un autre type (article qui est en réalité un chapitre, communication publiée dans des actes). Refuser quand la fiche est le compte rendu d'un livre que la source décrit comme un livre, ou un chapitre que la source confond avec le livre entier. Les valeurs sans équivalent dans le nouveau type sont recopiées dans le champ extra, rien n'est perdu.
- `type_doublon`. Deux fiches jugées doublons à l'étape 2 n'ont pas le même type, et la fusion attend qu'elles l'aient. Chaque fiche du groupe reçoit un cas, qui propose le type de l'autre. Choisir le bon type avec `zc voir` (revue ou actes, éditeur, PDF), accepter le cas de la fiche dont le type est faux et refuser l'autre. Accepter les deux échangerait les types, `zc` le refuse. Une fois le plan appliqué, relancer `zc doublons planifier`.

En cas de doute, lancer `zc voir <clé>`, qui donne tous les champs de la fiche et le début du texte de son PDF (titre, auteurs, revue, année imprimés sur la première page). S'il ne suffit pas, laisser le cas sans décision et dire à l'utilisateur ce qui a été vérifié et ce qui empêche de trancher. Il pourra regarder la fiche dans Zotero.
