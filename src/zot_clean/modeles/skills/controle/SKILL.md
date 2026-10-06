---
name: controle
description: Contrôle régulier de la bibliothèque Zotero avec zc (gestion courante), c'est-à-dire lire ce qui a changé depuis le dernier audit, reporter dans plan.md les thèmes créés, renommés, déplacés ou supprimés dans Zotero, proposer le découpage des thèmes trop gros et renvoyer chaque problème nouveau à la commande qui le corrige. À utiliser au début d'une séance de travail, quand l'utilisateur demande où en est sa bibliothèque, ou quand l'audit signale des points nouveaux.
---

# Contrôle régulier

Le contrôle vit dans `zc audit`. Chaque audit garde un instantané de ses points, et son rapport s'ouvre sur ce qui est apparu et ce qui est réglé depuis l'audit d'un jour précédent. Le douzième contrôle, « Plan du fonds », compare `plan.md` aux collections du fonds dans Zotero. Après le nettoyage, Zotero fait foi et `plan.md` le suit. L'utilisateur peut donc créer, renommer, déplacer ou supprimer un thème directement dans Zotero.

## Déroulé

1. **Auditer.** Lancer `zc audit`, puis lire dans `rapports/audit-<date>.md` la section « Depuis l'audit du … » et le contrôle 12. Résumer à l'utilisateur en quelques phrases ce qui est nouveau, ce qui est réglé, et proposer un ordre de travail en commençant par ce qui compte le plus pour lui. Terminé quand l'utilisateur a choisi ce qu'il veut traiter maintenant.

2. **Thèmes changés dans Zotero.** Si le contrôle 12 signale un thème renommé, déplacé, créé ou supprimé dans Zotero, lancer `zc fonds suivre`, qui montre les changements à reporter dans `plan.md` sans rien écrire.
   - Les présenter à l'utilisateur, en précisant qu'un thème supprimé est retiré de `plan.md` avec ses sous-thèmes et sa définition, et que les décisions de rangement qui le visaient sont retirées.
   - Après son accord, `zc fonds suivre --enregistrer`, qui écrit `plan.md`, corrige les chemins des fichiers de suivi et enregistre la validation.
   - Pour chaque thème ajouté, proposer une définition (une phrase, avec « Inclut » et « Exclut » si la frontière avec un voisin est floue), à partir de son nom, de sa place dans l'arbre et des titres donnés par `zc fonds titres <chemin>`. Après accord, l'écrire dans `plan.md`, puis `zc fonds valider --enregistrer`.

   Terminé quand le contrôle 12 ne signale plus de thème changé ni de thème sans définition.

3. **Références hors du fonds, et Inbox.** Les traiter avec le skill `inbox`. Terminé quand l'utilisateur a jugé celles qu'il voulait traiter.

4. **Doublons et métadonnées nouveaux.** Relancer les commandes des étapes 2 et 3 sur toute la bibliothèque (`zc doublons chercher`, `zc metadonnees identifiants`, `types`, `completer`) et suivre les skills `doublons` et `metadonnees`. Les cas déjà jugés y sont retenus et les sources gardées en cache, si bien que seuls les cas nouveaux reviennent. Terminé quand les cas nouveaux sont jugés ou laissés en attente par l'utilisateur.

5. **Thèmes trop gros.** Un thème qui dépasse le seuil de `config.toml` (`seuil_sous_theme`) est signalé comme une information. Si l'utilisateur veut le découper, lancer `zc fonds titres <chemin>` et lire tous les titres.
   - Ne proposer un découpage que s'il est net, c'est-à-dire si deux à cinq sous-thèmes se dégagent d'eux-mêmes, avec chacun une définition qui permet de ranger une nouvelle référence sans hésiter. Sinon, dire à l'utilisateur que le thème peut rester tel quel.
   - Présenter les sous-thèmes et leur définition. Après accord, les écrire dans `plan.md`, puis `zc fonds valider` et `zc fonds valider --enregistrer`.
   - Proposer la place de chaque référence, en un bloc pour celles qui s'imposent, par paquets de 10 au plus pour les autres. Écrire les décisions acceptées dans `suivi/rangement.toml` (`action = "déplacer"`, `cible` = chemin du sous-thème, `depuis` = clé de la collection du thème, donnée par le rapport des titres, `source = "agent"`, `decision = "accepter"`). Une référence qui reste dans le thème lui-même n'a pas d'entrée.
   - Lancer `zc fonds planifier`, résumer le plan, et après accord l'appliquer comme à l'étape 5 du nettoyage (essai, vérification avec `zc voir`, puis `--tout`).

   Terminé quand l'utilisateur a décidé pour chaque thème signalé, découpé ou laissé tel quel.

## Points d'attention

- `zc fonds suivre` ne touche pas à Zotero. Il fait suivre `plan.md` à Zotero, jamais l'inverse.
- Un thème au-delà de la profondeur permise (`profondeur_max`) n'est pas reporté dans `plan.md`. Le signaler à l'utilisateur, qui le remontera d'un niveau dans Zotero ou le transformera en concept.
- Un thème du plan « pas encore dans Zotero » est un thème que l'utilisateur vient d'ajouter à `plan.md`. `zc fonds planifier` le crée.
- Les fiches confidentielles restent masquées dans le rapport des titres. Demander à l'utilisateur où les ranger.
