---
name: tags
description: Mettre de l'ordre dans les tags de la bibliothèque Zotero avec zc (étape 6 du nettoyage), c'est-à-dire retirer les tags automatiques et les mots-clés importés, regrouper les variantes, ramener les états à ceux de la méthode et tirer des concepts des tags existants. À utiliser quand l'utilisateur parle de tags, de mots-clés, de concepts, ou quand l'audit signale des tags automatiques ou des variantes.
---

# Tags

L'étape 6 traite tout le jeu de tags en un inventaire et un plan. `zc tags inventaire` écrit `suivi/tags.toml`, qui décrit des règles par nom de tag, jamais par fiche, et garde les décisions d'une fois sur l'autre. Ce fichier fait foi. Il sert aussi plus tard au tri de l'Inbox, qui applique les mêmes règles aux nouvelles références. `zc tags planifier` ne planifie que ce qui reste à changer, on peut le relancer après chaque passe.

Mieux vaut avoir fait le plan du fonds (étapes 4 et 5) avant, puisque les concepts et les tags qui doublent un thème se jugent d'après les thèmes du fonds. Ce n'est pas exigé.

Les concepts suivent une même convention, que `zc` applique autant qu'il le peut dans ses propositions et que l'agent applique au nom qu'il propose. Un concept porte le préfixe des concepts (`#` par défaut), s'écrit en minuscules sauf nom propre ou sigle (« #mémoire », « #Kant », « #TDAH »), dans la langue de l'utilisateur (« #cognition incarnée » plutôt que « #embodiment » pour un utilisateur francophone, sauf terme établi dans sa discipline), avec des espaces entre les mots plutôt que des tirets ou des soulignés. `zc` ne traduit rien. C'est à l'agent de proposer le nom dans la bonne langue.

Certains tags sont protégés et ne reçoivent aucune proposition, à savoir les tags techniques (`_…`), les états et marques de la méthode, les tags colorés, ceux de `[tags] proteges` dans `config.toml`, et ceux sur lesquels repose une proposition de rangement en attente. Ils ne changent que par une entrée ajoutée à la demande explicite de l'utilisateur, `zc tags ajouter "<nom>" --sort <sort> --utilisateur`. Le tag du filtre de confidentialité (`_privé` par défaut) ne change jamais.

Les décisions s'écrivent par commande, sans toucher au fichier, avec `zc tags accepter`, `zc tags refuser` et, pour un tag qui n'a pas d'entrée, `zc tags ajouter`. Un tag se désigne par son nom exact, toujours entre guillemets simples (`'#attention'`, `'lettres/arts'`, `'★'`), ou doubles si le nom contient une apostrophe, puisqu'un nom qui commence par `#` serait pris par le terminal pour un commentaire. Les noms viennent en premier, les options ensuite. `zc` refuse un nom absent du fichier et ne change que ce qui attend une décision. Une décision déjà prise se change à la main dans le fichier.

## Déroulé

1. **Inventorier.** Lancer `zc tags inventaire`, puis lire le rapport `rapports/tags-inventaire-<date>.md` et `suivi/tags.toml`. Terminé quand la commande a donné le nombre de tags et de groupes à juger.

2. **Règle globale des tags automatiques.** Les tags automatiques sont les mots-clés des éditeurs, ajoutés par Zotero et rarement utiles. Présenter à l'utilisateur ce que la règle retire (nombre de noms et d'occurrences, les plus portés) et les exceptions proposées, à juger ensuite. Après son accord, lancer `zc tags accepter --regle-automatiques`. S'il préfère garder ces tags, `zc tags refuser --regle-automatiques`, et lui signaler qu'il peut aussi les masquer dans le sélecteur de tags de Zotero (« Afficher les tags automatiques »). S'il y a une section `[importes]`, faire de même pour les mots-clés importés (`--regle-importes`), après avoir montré deux ou trois fiches du rapport avec `zc voir <clé>` pour vérifier que ce sont bien des mots-clés d'éditeurs. Terminé quand les deux sections ont une décision.

3. **Variantes.** Les groupes `[[variantes]]` réunissent des noms de même forme, ramenés à `cible`, posée en tag manuel.
   - Les groupes `classe = "évident"` ne diffèrent que par la casse, les accents, les espaces, les tirets ou le préfixe. Vérifier que la cible proposée suit la convention des concepts (minuscules sauf nom propre, langue de l'utilisateur), puis les présenter en un seul bloc, avec leur nombre et une ligne par groupe. Une seule approbation suffit.
   - Les groupes douteux (pluriel, autre différence) se présentent par paquets de 10 au plus, chacun avec une recommandation. Un pluriel peut changer le sens (« lettre » et « lettres », au sens de la littérature), recommander alors de refuser.
   - Proposer aussi, de soi-même, les traductions évidentes (« memory » et « mémoire »). Après l'accord, les écrire comme une fusion, `zc tags ajouter 'memory' --sort fusionner --cible 'mémoire'`, ou `zc tags accepter 'memory' --sort fusionner --cible 'mémoire'` si le tag a déjà une entrée `[[tag]]`.
   - Après l'accord, `zc tags accepter --variantes '<nom>' …` et `zc tags refuser --variantes '<nom>' …`, chaque groupe désigné par sa cible ou l'un de ses noms. Si l'utilisateur change la cible, `zc tags accepter --variantes '<nom>' --cible '<cible>'`, un groupe par commande.

   Terminé quand l'utilisateur a jugé les groupes qu'il voulait traiter maintenant.

4. **Tags à juger.** Chaque `[[tag]]` porte un sort proposé, son effectif (fiches), sa dispersion (thèmes du fonds où se trouvent ses fiches), ses thèmes et, en commentaire, trois titres. Pour un cas peu clair, lancer `zc voir --tag <nom>`, qui montre les fiches qui le portent avec leurs collections.
   - **États et marques** (`sort = "état"`). Tags venus d'autres habitudes (« to read », « important »), rapprochés de ceux de la méthode. Les présenter en un bloc. Une fiche qui recevrait deux états garde le plus avancé.
   - **Portés par une seule fiche** (`classe = "évident"`, `sort = "supprimer"`). Les présenter en un seul bloc avec la liste complète, que l'utilisateur peut parcourir.
   - **Concepts** (`sort = "concept"`). Tags répartis sur plusieurs thèmes, qui traversent le fonds. Proposer pour chacun un nom (`cible`) qui suit la convention des concepts, en le traduisant au besoin (le nom proposé par `zc` reprend celui du tag, mis en minuscules), et une définition d'une ou deux phrases. Après l'accord, ajouter la définition à la section `# Concepts` de `plan.md`, sous un titre `## #nom`.
   - **Tags qui doublent un thème** (`theme` renseigné, `sort = "supprimer"`). Ils répètent une collection. Quand d'autres noms de même forme existent (« Émotions » pour « émotion »), `zc` les réunit dans le champ `variantes` de l'entrée au lieu d'en faire un groupe `[[variantes]]`. Accepter l'entrée les supprime avec le tag. Si l'utilisateur préfère garder le tag, l'accepter avec `--sort garder`, et les variantes y sont alors ramenées. Les fiches qui les portent sans être dans le thème ont été proposées dans `suivi/rangement.toml`. Les faire juger d'abord (skill `fonds`, étape 5), le tag reste en place tant qu'elles attendent.
   - **Autres tags**, par paquets de 20, avec effectif, dispersion et titres, chacun avec un sort recommandé parmi `supprimer`, `garder`, `concept`, `fusionner` (renommé en `cible`). Garder est un sort légitime, la méthode n'interdit pas un tag hors de ses familles.
   - Un tag cité par une recherche enregistrée (`recherches`) n'est retiré ou renommé que par une décision explicite. Le rappeler à l'utilisateur au moment de juger.
   - Un tag automatique dont l'entrée attend une décision échappe à la règle globale. S'il est refusé, la règle le retire.

   Après l'accord, `zc tags accepter '<nom>' …` et `zc tags refuser '<nom>' …`. Pour un autre sort ou une autre cible que ceux proposés, `zc tags accepter '<nom>' --sort <sort> --cible '<cible>'`, une commande par sort et cible, et l'entrée passe en source « agent ». Une fois approuvés les deux blocs d'évidents (groupes de l'étape 3, tags portés par une seule fiche), `zc tags accepter --evidents --sauf '<nom>' …` les accepte d'un coup, sauf ceux que l'utilisateur a écartés. Avant cela, nommer les groupes et les tags. Terminé quand l'utilisateur a jugé les paquets qu'il voulait traiter maintenant. Les entrées restantes ne bloquent rien.

5. **Planifier.** Lancer `zc tags planifier`. Résumer le rapport du plan, à savoir le nombre d'éléments, les couleurs proposées (section « Couleurs » : les tags de la méthode en tête du sélecteur, chacun sur la touche de son rang, et les tags déjà colorés qui changent de touche), les sortes de changement, les tags retirés et renommés, les recherches enregistrées à mettre à jour, et la section « À regarder ». Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

6. **Sauvegarder, essayer, appliquer.** Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero et lancer `zc sauvegarder`. Puis `zc appliquer <plan> --essai`. Les éléments de l'essai, listés dans le rapport avec leurs tags d'avant et d'après, couvrent chaque sorte de changement. Les vérifier avec `zc voir` (tags et leur type), le dire à l'utilisateur, puis `zc appliquer <plan> --tout`. Une commande interrompue se relance telle quelle. Terminé quand l'application complète est faite.

7. **Après.** Si le rapport du plan cite des recherches enregistrées, rappeler à l'utilisateur de les mettre à jour dans Zotero. Proposer de décocher, dans les réglages de Zotero (Général) et dans ceux du connecteur du navigateur, « Ajouter automatiquement des tags à partir des mots-clés et des vedettes-matières », pour que les tags automatiques ne reviennent pas. Lancer `zc audit` et relancer `zc tags inventaire` pour voir ce qui reste. Une nouvelle passe se fait de la même façon, à partir de l'étape 3.

Pour renommer ou fusionner un tag coloré, l'utilisateur passe par « Renommer le tag… » dans le sélecteur de tags de Zotero, qui reporte la couleur. `zc` ne colore que les tags de la méthode, dont `zc tags planifier` propose les couleurs (section « Couleurs » du plan). Les autres tags colorés gardent la leur, même quand ils changent de touche.

Pour revenir sur un plan appliqué, lancer `zc annuler <plan>`, résumer le rapport d'annulation, puis suivre l'étape 6 avec le plan d'annulation.

Un tag présenté comme « tag confidentiel … » n'est porté que par des fiches exclues par le filtre. Ne pas chercher à savoir lequel. Seules les règles globales s'y appliquent. Si l'utilisateur veut en changer un, il le dit, et l'entrée s'ajoute avec cet identifiant comme nom, `zc tags ajouter 'tag confidentiel <identifiant>' --sort <sort> --utilisateur`.
