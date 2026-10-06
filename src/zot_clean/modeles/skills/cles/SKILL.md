---
name: cles
description: Mettre de l'ordre dans les clés de citation de la bibliothèque Zotero avec zc (étape 7 du nettoyage), c'est-à-dire départager les clés en double et ranger dans le champ de Zotero les lignes « Citation Key: » restées dans Extra, les clés manquantes étant remplies par Better BibTeX. À utiliser quand l'utilisateur parle de clés de citation, de Better BibTeX, de LaTeX ou de Markdown, ou quand l'audit signale des clés absentes, en double ou restées dans Extra.
---

# Clés de citation

Better BibTeX (BBT) calcule les clés et remplit seul celles qui manquent. `zc` ne fait que ce que BBT ne fait pas, à savoir départager les clés en double (la fiche la plus ancienne garde la clé, les autres reçoivent un suffixe a, b…) et ranger dans le champ « Clé de citation » de Zotero les lignes « Citation Key: » restées dans Extra. Une clé unique n'est jamais touchée, même si elle ne suit pas la formule de BBT. Sans BBT actif, seul le départage des doubles est fait.

## Déroulé

1. **Lire l'audit.** La section « Clés de citation » de `rapports/audit-<date>.md` donne l'état de BBT, les clés manquantes, en double et restées dans Extra, et les réglages à revoir. Si BBT refait les clés à chaque modification, demander à l'utilisateur de décocher « Regenerate citation key when item changes » dans Zotero › Réglages › Better BibTeX, sinon chaque fiche modifiée par `zc` changerait de clé. Terminé quand ce réglage est décoché ou absent.

2. **Clés manquantes.** Elles se remplissent dans Zotero, par BBT. D'ordinaire BBT donne sa clé à une fiche quelques secondes après son arrivée (« Automatically fill citation key after »). Pour les fiches restées sans clé, guider l'utilisateur. Sélectionner les fiches (toute la bibliothèque convient), puis clic droit, Better BibTeX › Fill, qui ne remplit que les clés vides. Ne jamais proposer « Refresh », qui recalcule aussi les clés existantes et casserait les textes qui les citent. Si le délai de remplissage est à 0, proposer de le remettre à 2 secondes. Terminé quand l'utilisateur a rempli les clés qu'il voulait.

3. **Planifier.** Lancer `zc cles planifier`. Un refus pour Zotero trop ancien ou Better BibTeX 7 s'explique à l'utilisateur tel quel, l'étape attend la mise à jour. Lire le rapport du plan et `suivi/cles.toml` s'il existe. Terminé quand le rapport est lu.

4. **Juger les cas de `suivi/cles.toml`.** Vérifier d'abord un cas douteux avec `zc voir <clés>`.
   - `[[double]]` : la règle s'applique sans décision. Si l'utilisateur sait qu'un texte cite une fiche précise sous cette clé, cette fiche la garde (`<fiche>=garder`). Pour laisser un double tel quel, `<fiche>=écarter`, avec la clé de l'une de ses fiches.
   - Un double « renvoyé à l'étape 2 » réunit des fiches qui sont peut-être des doublons. Les juger avec le skill `doublons`. La fusion règle la clé, et son rapport dit quelle clé disparaît.
   - `[[extra]]` : la ligne d'Extra diffère de la clé native. Demander à l'utilisateur laquelle ses textes utilisent, puis `<fiche>=natif` (garder la clé native), `<fiche>=extra` (prendre celle de la ligne) ou `<fiche>=écarter`.

   Présenter les cas en un bloc, avec une recommandation pour chacun. Après l'accord, écrire les décisions par la commande, sans toucher au fichier, en une seule ligne pour tous les cas, par exemple `zc cles decider ABCD1234=garder EFGH5678=natif --raison "<raison>"` (la raison vaut pour tous les cas de la commande, elle est facultative). Seuls les cas qui attendent changent, une décision déjà prise se change à la main dans le fichier. Relancer ensuite `zc cles planifier`. Terminé quand l'utilisateur a jugé les cas qu'il voulait traiter maintenant. Les autres restent hors du plan.

5. **Faire approuver.** Résumer le rapport, à savoir le nombre de clés en double et de fiches qui reçoivent un suffixe, les lignes d'Extra rangées et la section « Attention ». Rappeler qu'une fiche qui reçoit un suffixe change de clé, et qu'un texte qui la citait est à mettre à jour. Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

6. **Sauvegarder, essayer, appliquer.** Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero et lancer `zc sauvegarder`. Puis `zc appliquer <plan> --essai`, dont les groupes couvrent chaque sorte de changement (listés dans le rapport). Vérifier ces fiches avec `zc voir` (clé de citation et Extra), le dire à l'utilisateur, puis `zc appliquer <plan> --tout`. Une commande interrompue se relance telle quelle. Terminé quand l'application complète est faite.

7. **Contrôler.** Après la synchronisation de Zotero, relancer `zc cles planifier`, qui ne doit plus rien trouver à faire hors des cas écartés ou à juger, puis `zc audit`. Terminé quand la section « Clés de citation » ne signale plus que ce que l'utilisateur a choisi de laisser.

Une fiche qui reçoit un suffixe garde une clé tirée du titre de la fiche qui garde la clé. Quand les deux titres diffèrent, le rapport le signale (« clé tirée du titre d'une autre fiche »). Si l'utilisateur veut une clé tirée de son propre titre, lui proposer, une fois le plan appliqué et synchronisé, de régénérer la clé de cette fiche seule dans Zotero (clic droit sur la fiche, Better BibTeX › Refresh). C'est la seule exception à la règle de ne pas proposer « Refresh », puisque cette clé vient de changer et qu'aucun texte ne la cite encore.

Pour revenir sur un plan appliqué, lancer `zc annuler <plan>`, résumer le rapport d'annulation, puis suivre l'étape 6 avec le plan d'annulation.

Une fiche présentée comme « (fiche confidentielle) » n'apparaît que par sa clé de fiche, et la clé de citation qu'elle partage est masquée. Pour un avis à son sujet, demander à l'utilisateur de la regarder lui-même dans Zotero.
