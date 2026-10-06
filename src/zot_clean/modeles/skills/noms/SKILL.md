---
name: noms
description: Renommer les fichiers PDF et EPUB de la bibliothèque Zotero d'après leurs métadonnées avec zc (étape 8 du nettoyage), selon le modèle de noms réglé dans Zotero. À utiliser quand l'utilisateur parle de noms de fichiers, de PDF mal nommés ou de renommage, ou quand l'audit signale des noms en retard (point 9).
---

# Noms des fichiers

Zotero nomme le fichier principal de chaque fiche d'après son modèle (par défaut « Auteur - Année - Titre »), mais seulement quand la fiche change sur cet ordinateur. Ce que `zc` ou un autre poste écrit par l'API laisse donc des noms en retard. `zc noms planifier` prépare un plan qui change le nom enregistré dans Zotero, et chaque ordinateur renomme ses fichiers sur le disque à sa synchronisation suivante. Le contenu des fichiers ne change pas.

Seule la pièce jointe principale de chaque fiche est renommée, comme le fait Zotero. Les fichiers liés, les PDF secondaires et les noms écartés (nom déjà pris dans le dossier, refusé par Windows, trop long) restent tels quels et sont listés. Le modèle se règle dans Zotero, jamais dans `config.toml`. Si `zc` ne sait pas le calculer, il refuse et renvoie au bouton « Renommer les fichiers… » des réglages de Zotero.

## Déroulé

1. **Voir ce qui est en retard.** Lancer `zc audit` et lire le point 9 (et le point 5 pour les fichiers absents). Terminé quand l'utilisateur sait combien de fichiers seraient renommés.

2. **Planifier.** Lancer `zc noms planifier`. La commande cherche sur zotero.org les fichiers absents du disque (`--hors-ligne` pour s'en passer, ils ne sont alors pas renommés). Résumer le rapport du plan, à savoir le nombre de fichiers, quelques exemples d'ancien et de nouveau nom, les titres de pièce jointe qui changent aussi (un titre égal à l'ancien nom devient « PDF »), et la section « Laissés de côté » avec ses raisons. `zc` déduit la conjonction (« et » ou « and » entre deux auteurs) des noms existants, sinon de la langue de Zotero. Un nom non calculé faute de conjonction se règle par `conjonction` dans la section `[methode]` de `config.toml`, d'après la langue dans laquelle l'utilisateur voit Zotero. Terminé quand l'utilisateur a approuvé explicitement ce plan-là.

3. **Sauvegarder et essayer.** Si la dernière sauvegarde a plus de 24 heures, demander à l'utilisateur de fermer Zotero et lancer `zc sauvegarder`, puis de rouvrir Zotero. Lancer `zc appliquer <plan> --essai`, qui renomme les premiers fichiers de la liste (marqués « essai » dans le rapport). Terminé quand l'essai est appliqué sans conflit.

4. **Synchroniser et vérifier.** Le fichier n'est renommé sur le disque que par Zotero, à sa synchronisation. Demander à l'utilisateur de lancer la synchronisation de Zotero (flèche verte en haut à droite) et d'attendre qu'elle se termine. Puis lancer `zc voir <clés des fiches de l'essai>`. Chaque pièce jointe doit porter le nouveau nom, sans la mention « fichier absent du disque ». Terminé quand c'est le cas pour chaque fichier. Si un fichier reste absent après la synchronisation, ne pas continuer, lancer `zc annuler <plan>` et suivre l'annulation (résumer, essai, synchronisation, vérification).

5. **Appliquer le reste.** Lancer `zc appliquer <plan> --tout`. Une commande interrompue se relance telle quelle. Demander une dernière synchronisation de Zotero, et sur chaque autre ordinateur qui partage la bibliothèque. Terminé quand l'application complète est faite et synchronisée.

6. **Contrôler.** Lancer `zc audit`. Le point 9 doit montrer les seuls cas laissés de côté. S'il signale une pièce jointe qui pointe vers un fichier absent alors que son dossier en contient un autre (renommage local échoué), le dire à l'utilisateur. `zc noms planifier` peut se relancer à tout moment et ne prépare que ce qui reste. Terminé quand l'utilisateur a vu ce qui reste et sait ce qui se règle à la main.

## Fichiers absents et WebDAV

Le rapport dit comment Zotero synchronise les fichiers, d'après son profil.

- **Par zotero.org.** Un fichier absent du disque mais stocké sur zotero.org est renommé, Zotero le nommera au téléchargement. Un fichier introuvable partout n'est pas renommé (point 5 de l'audit).
- **Par WebDAV, ou synchronisation des fichiers désactivée.** Un fichier absent du disque n'est jamais renommé, il est seulement listé. Les fichiers présents sont renommés comme ailleurs, mais ce cas n'a pas encore été vérifié avec un serveur WebDAV. À l'étape 4, vérifier avec un soin particulier, sur cet ordinateur et, s'il y en a, sur un autre poste ou une tablette après sa synchronisation. En cas de doute, annuler et renommer plutôt par le bouton « Renommer les fichiers… » des réglages de Zotero.

Une pièce jointe présentée comme « (fiche confidentielle) » n'apparaît que par sa clé. Ne pas chercher son nom. Si elle est laissée de côté, demander à l'utilisateur de la regarder lui-même dans Zotero.
