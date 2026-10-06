---
name: inbox
description: Trier les nouvelles références de la bibliothèque Zotero avec zc (gestion courante), c'est-à-dire repérer les doublons, corriger les métadonnées et ranger chaque référence dans un thème du fonds, en un seul plan. À utiliser quand l'utilisateur demande de trier l'Inbox ou de ranger ses nouvelles références, ou quand l'audit signale des références dans l'Inbox.
---

# Tri de l'Inbox

Le tri traite les références de l'Inbox et celles qui n'ont aucune place dans le fonds, qu'elles soient hors de toute collection ou arrivées directement dans un projet (par exemple un cours). Il reprend les étapes 2, 3, 5 et 6 du nettoyage, limitées à ces références, et aboutit à un seul plan. Les tags suivent les règles déjà acceptées de `suivi/tags.toml` (tags automatiques retirés, variantes et états ramenés à leur forme), sans rien décider de nouveau. Une référence d'un projet y reste et reçoit en plus son thème.

## Déroulé

1. **Préparer.** Lancer `zc inbox preparer`, puis lire le rapport `rapports/inbox-<date>.md`. Il donne les groupes de doublons et les cas de métadonnées à juger, puis une ligne par référence (auteur, année, titre, type, revue ou ouvrage, collections actuelles, clé `depuis`) avec les thèmes voisins, c'est-à-dire ceux où sont rangées d'autres fiches du même auteur ou de la même revue. « Aucun thème voisin trouvé » veut seulement dire que rien de tel n'est encore rangé dans le fonds. Terminé quand le rapport est lu.

2. **Doublons.** Juger les groupes signalés dans `suivi/doublons.toml` comme le skill `doublons` le décrit, en vérifiant avec `zc voir`. Une référence de l'Inbox est souvent une seconde saisie d'une fiche déjà rangée. Garder alors l'ancienne (`zc doublons accepter --conserver <clé de l'ancienne>`), qui a déjà ses thèmes. Les décisions s'écrivent par `zc doublons accepter` et `zc doublons refuser`, sans toucher au fichier.

3. **Métadonnées.** Juger les cas listés dans `suivi/metadonnees.toml` comme le skill `metadonnees` le décrit, les évidents en un bloc et les douteux par paquets, puis écrire les décisions par `zc metadonnees accepter` et `zc metadonnees refuser`.

4. **Ranger.** Pour chaque référence, choisir un thème de `plan.md`, d'après sa définition et ses lignes « Inclut » et « Exclut ».
   - Les thèmes voisins du rapport sont des indices, pas des réponses. Un auteur peut écrire dans plusieurs domaines.
   - Quand le titre ne suffit pas, lancer `zc voir <clé>` (résumé, revue, début du PDF).
   - Écrire une entrée par référence dans `suivi/rangement.toml` (une table `[[fiche]]`, comme l'exemple de l'en-tête), avec `cle`, `action = "déplacer"`, `cible` = chemin du thème sans la racine du fonds, `depuis` = la clé donnée par le rapport, `source = "agent"`, `decision = ""` et une note d'une phrase. Pour une référence hors de toute collection ou d'un projet, `action = "ajouter"` sans `depuis`. Celle d'un projet y reste.
   - Présenter les propositions à l'utilisateur, en un bloc pour celles où le thème s'impose (définition claire, thème voisin concordant), par paquets de 10 au plus pour les autres, chacune avec le thème et sa justification. Après son accord, écrire `decision = "accepter"`.
   - Si aucun thème ne convient, proposer le plus proche, ou un nouveau thème avec sa place dans l'arbre et sa définition. Si l'utilisateur accepte un nouveau thème, l'ajouter à `plan.md`, lancer `zc fonds valider`, puis `zc fonds valider --enregistrer` après son accord. En attendant, la référence reste dans l'Inbox, sans entrée acceptée.
   - Pour une référence présentée comme « (fiche confidentielle) », demander à l'utilisateur où la ranger.
   - Une référence hors de l'Inbox que l'utilisateur décide de laisser hors du fonds (titre trop vague, référence gardée seulement dans son projet) se note par `zc fonds a-ranger --laisser <clé>…`, après son accord. Elle ne revient plus au tri ni dans l'audit tant qu'elle reste dans les mêmes collections. Une référence de l'Inbox, elle, se range toujours.

   Terminé quand l'utilisateur a jugé les références qu'il voulait traiter maintenant. Les autres restent dans l'Inbox.

   Si le rapport signale des « tags hors familles, sans règle », les présenter à l'utilisateur avec la référence qui les porte. Selon sa réponse, ajouter la règle par `zc tags ajouter '<nom>' --sort <sort> --utilisateur` (sort `garder`, `concept`, `supprimer` ou `fusionner`, avec `--cible '<nom visé>'` pour un concept ou une fusion), comme le décrit le skill `tags`, sans toucher au fichier. Rien n'est à faire si `suivi/tags.toml` n'existe pas encore.

   Si le rapport signale une référence « sans clé de citation », Better BibTeX ne la lui a pas donnée à l'arrivée. Proposer à l'utilisateur de la remplir dans Zotero (clic droit, Better BibTeX › Fill). Une clé en double qui touche une référence triée est départagée par le plan lui-même, la fiche la plus ancienne gardant la clé (skill `cles`).

5. **Planifier.** Lancer `zc inbox planifier`. Résumer le rapport du plan, à savoir les fusions, les champs ajoutés ou corrigés, les thèmes créés, la place de chaque référence et celles qui restent dans l'Inbox. Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

6. **Appliquer.** Un plan de tri qui touche moins de 50 fiches s'applique d'un coup, sans essai ni sauvegarde récente. Une fois le plan approuvé, lancer `zc appliquer <plan> --tout`, vérifier quelques fiches avec `zc voir`, puis dire à l'utilisateur ce qui a été fait. Au-delà de 50 fiches, `zc appliquer <plan> --essai`, vérification avec `zc voir`, puis `--tout`. Un plan qui crée un thème nouveau touche des collections, que Zotero ne récupère pas toujours seul. Demander alors à l'utilisateur de lancer à la fin une synchronisation à la main (flèche verte en haut à droite).
