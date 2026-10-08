---
name: subjects
description: Propose with the user the outline of the subjects of their Zotero library (disciplines, themes, sub-themes) from the existing collections and tags, have it validated in plan.md, decide the fate of each old collection (step 4 of the cleanup), then file the items according to this outline (step 5). Use when the user talks about a classification plan, about reorganizing or filing their collections, about disciplines or themes, or when the audit reports a collection structure to review.
---

# Outline of the subjects

The subjects root is the root collection that holds the disciplines and themes. Its name comes from `config.toml` (`[methode]`, key `fonds`), `Fonds` in a French library and `Subjects` in an English one. Read it with `zc config show` and use the configured name. The projects roots, the archives root and the Inbox are configured the same way.

Step 4 changes nothing in Zotero. It ends in two validated files. `plan.md` describes the subjects (disciplines, themes, sub-themes, with a definition for each) and will outlive the cleanup. `suivi/fonds.toml` (the subjects tracking file) describes the transition, that is the fate of each old collection and the tags that designate a theme. Step 5, filing, will create the collections and move the references into them according to these two files. They are authoritative, and the agent always presents them together.

The words stored in `suivi/fonds.toml` are French in every library (`sort`, `cible`, `thème`, `répartir`…), and are given as such below with a gloss. The filing decisions (`suivi/rangement.toml`) are written by `zc subjects accept` and `reject`.

Duplicates (step 2) must be dealt with before filing. If the audit still reports many, tell the user, without blocking step 4.

## Procedure

1. **Take inventory.** Run `zc subjects inventory`. Read the report `rapports/fonds-inventaire-<date>.md` (tree of collections with counts, shared references, most-carried tags and a sample of titles, then thematic tags and tags that come back together), and `suivi/fonds.toml`. Done when the command has given the number of collections without a fate. If a collection has disappeared since the last inventory, tell the user.

2. **Propose the tree.** Propose the whole tree at once, without definitions, with for each discipline and each theme the number of references expected and the old collections or tags it comes from. Start from what exists (collections, tags that come back together, the tree under the subjects root if there is one) and follow the criteria below. Point out the old collections proposed to be distributed, those that seem to be projects and those proposed to be dissolved. For a collection of the subjects that exceeds `seuil_sous_theme`, the inventory gives all the titles. Propose sub-themes only if the division is clear, and say so when it is not. Let the user rename, merge, split, move. Done when the user approves the tree.

3. **Write the outline, discipline by discipline.** For each discipline, write in `plan.md` the definition of the discipline and of each of its themes, with the « Includes » and « Excludes » lines where the boundary with a neighboring theme invites hesitation. In `plan.md` the fields are named `Includes` and `Excludes` in an English library, `Inclut` and `Exclut` in a French one, and `zc` accepts both. A definition is any text under a heading (`Définition` is not a keyword). Fill in `suivi/fonds.toml` with the fate of the old collections that belong to it. Show the user the discipline and the corresponding fates, correct according to their remarks, then go on to the next. Done when each discipline has been seen and each old collection has a fate.

4. **Link tags.** Propose, in the `tags` table of `suivi/fonds.toml`, the thematic tags that clearly designate a theme of the outline (« visual perception » to `Psychology/Perception`). They will serve as a hint to file in step 5 the references without a collection or to distribute. An ambiguous or cross-cutting tag stays out of the table. The fate of the tags themselves is settled in step 6. Done when the user has approved the table.

5. **Check.** Run `zc subjects validate`. Correct each error (duplicate name under the same parent, one level too many, name of a root, path that leads nowhere, collection without a fate) in the file indicated, then run again. The warnings (theme without a definition, collection to distribute without a candidate) are presented to the user, who decides whether to remedy them. Done when the command no longer reports an error.

6. **Validate.** Present the user with the final outline (tree and expected counts) and the summary of the fates (how many collections become a theme, are distributed, go to the projects or to the archives, are dissolved or stay outside the outline). After their explicit agreement, run `zc subjects validate --save`. Done when the command confirms the validation.

After the validation, touching up a definition requires nothing. Changing the structure (one theme more or less, a fate, a target, a linked tag) cancels the validation, `zc subjects validate` then shows what has changed, and it must be validated again before filing.

## Step 5, filing

Filing applies the validated outline. It transforms the classification in place, that is the collections keep their key and are renamed or moved, only the missing collections are created, and the collections that are merged or dissolved go to Zotero's trash. It is done in several passes. `zc subjects plan` each time compares the real state of the library with the target state and plans only the difference, so it can be run again without fear.

1. **Check.** Run `zc subjects validate`. The outline must be validated in its current state, otherwise `plan` refuses. If the structure has changed, show the changes to the user and, after their agreement, `zc subjects validate --save`.

2. **The user's instructions.** When the user asks to move or delete specific items (« the references of such an author go into such a theme », « these textbooks to the trash »), write it with `zc subjects accept <key>=<path> … --user` (`--trash` with the keys alone for the trash). To find the keys, rely on the reports (`zc subjects pending`, inventory).

3. **First pass, the structure.** Run `zc subjects plan`. Read the `.md` report and summarize it to the user, that is the collections created, renamed, moved, merged, moved to the trash, the number of items filed, the « To look at » points (« À regarder » in a French library) and the number of items that will have no place in the subjects. Done when the user has approved this plan.

4. **Back up, trial, apply.** If the last backup is older than the configured delay (`delai_heures` in `zc config show`, 24 hours by default), ask the user to close Zotero and run `zc backup`. Then `zc apply <plan> --trial`, which applies the first groups, that is the first complete collections in the order of the tree. Check them yourself with `zc show` on a few filed items (collections of each), tell the user, then `zc apply <plan> --all`. An interrupted command is run again as it is.
   - Zotero does not always pick up by itself the collections created, renamed, moved or moved to the trash through the API, even when open, although it receives item changes quickly. `zc` does not need it, it reads on zotero.org what Zotero has not received yet. At the end of the step, ask the user to start a synchronization by hand once (green arrow at the top right), so that they find their collections up to date in Zotero.

5. **Distribute and place, in bundles.** Run `zc subjects pending`, which writes in `rapports/fonds-a-ranger-<date>.md` the items of the collections to distribute and the items without a place in the subjects, in bundles of 50, with the definitions of the candidate targets. The tags linked to a theme have already produced proposals there (`source = "tag"`).
   - For each bundle, propose a target only for the items whose place is clear, according to the definitions (Includes, Excludes). An item that fits the theme where it already is stays there, without an entry.
   - Present the bundle to the user, in a few lines per target. An item appears in only one bundle, that of its first collection to distribute, its other collections being given on its line.
   - Once they approve, write the decisions with `zc subjects accept <key>=<path> …` (path in the outline, without the subjects root, in quotes when it has spaces, as in `'ABCD2345=Psychology/Visual perception'`), with their corrections, without touching the file. `zc` finds by itself the collection the item leaves (the bundle's collection, nothing for an item of a project or the archives, which stays there) and refuses an unknown key or path. A new decision for an item replaces its earlier one.
   - The proposals drawn from the tags (marked « tag » in the report) are already in the file. Accept them with `zc subjects accept <key>`, reject those set aside with `zc subjects reject <key>`.
   - For a doubtful item, `zc subjects pending --abstract <key>` gives its abstract. Ask for it only case by case.
   - An item that has its place in two themes receives its second place with `--add` (`zc subjects accept <key>=<path> --add`). For an item already filed in several themes, `zc` cannot tell which one it leaves and refuses. Give it with `--from <key of the collection left>`, after asking the user.

   - When all the bundles of a collection are judged and their decisions written, run `zc subjects pending --reviewed <key>` (key given in the heading of its bundles) before `zc subjects plan`. The items left in place are no longer presented, only those that arrive there afterwards will be. A collection to distribute that is not a path of the outline (an old catch-all) then goes to the trash in the same plan as its last moves, which the user approves with it. The items left in it keep their other collections, and those that have none in the subjects come back among the items without a place. Tell the user when presenting that plan. Marked after the application, such a collection may already be in the trash, emptied by the pass, and `zc` then says there is nothing left to mark.

   - An item without a place in the subjects that the user, having seen it, prefers to leave outside the subjects (title too vague to file it, item kept only in a project or in the archives), is noted with `zc subjects pending --leave-out <key>…`. It no longer comes back in `zc subjects pending`, `zc inbox prepare` or check 12 of the audit, which only count it, as long as it stays in the same collections. Use it only after the user's agreement, never for an item that is simply not yet judged. If the item has a pending or accepted decision, first reject it with `zc subjects reject <key>`. For it to be presented again, remove its entry from `suivi/rangement-laissees.json`.

   Done when the user has judged the bundles they wanted to handle in the session. The other items simply stay where they are.

6. **Following passes.** Zotero can stay open throughout the session. Run `zc subjects plan` again, which now concerns only the newly accepted decisions, then the same sequence as in point 4. Repeat 5 and 6 at the user's pace.

7. **Roots.** When the user asks, review with them the `[racines]` (roots) table of `suivi/fonds.toml` (new names of the roots, without numbers), then `zc subjects plan --roots`. The renamings are the last groups of the plan. After the full application, update the names in `config.toml` (`[methode]`) and the title of the subjects section in `plan.md` (`# Fonds`, or `# Subjects`, that is the name of the subjects root). `zc` refuses to go on until this is done, and says so. Then run `zc subjects validate`, which carries the new names into `suivi/fonds.toml`, summarize the changes to the user (only the names of the roots should change), then `--save`.

8. **Check.** Run `zc audit` and tell the user what remains. The step is finished when `zc subjects plan` has nothing left to do and `suivi/rangement.toml` has no pending proposal. `plan.md` then follows Zotero, a theme added in Zotero is added to it with its definition.

To go back on a pass, run `zc undo <plan>`, summarize the undo report, then apply it as in point 4. A collection created by the pass then goes to the trash.

## Form of the files

`plan.md` is at the root of the working folder. The hierarchy lives under the title `# Fonds` in a French library or `# Subjects` in an English one (the name of the subjects root in `config.toml`), with `##` for a discipline, `###` for a theme and `####` for a sub-theme. Each title gives the exact name of the future collection. The other top-level sections are free, and `# Concepts` will be filled in at step 6.

```markdown
# Subjects

## Psychology

Study of the human mind and behavior, through experiment and observation.

### Perception

Vision, hearing, attention and their illusions.
Includes: psychophysics, color perception.
Excludes: neurophysiology of the retina (Biology/Neuroscience).

## Philosophy

…

# Concepts
```

(In a French library the example reads `# Fonds`, `## Psychologie`, `### Perception`, with `Inclut :` and `Exclut :`.)

In `suivi/fonds.toml`, the paths of the outline are written without the root (`Psychology/Perception`). The header of the file recalls the possible fates.
- `thème` (theme), with `cible` (target). The old collection becomes this theme, under the same name or another. Several old collections can have the same target, they are then merged.
- `répartir` (distribute), with `candidats` (candidates). Catch-all collection, whose references will go one by one into the candidate themes in step 5. Once reviewed (`zc subjects pending --reviewed`), or as soon as every item in it has been filed elsewhere, it goes to the trash at the next `zc subjects plan`, unless it is already at a path of the outline. Tell the user when presenting that plan. `candidats` serves only this fate, it is ignored for the others.
- `projet` (project), with `cible`. Collection tied to a course, an article, a book in progress. `cible` begins with the name of a projects root declared in `config.toml` (`projets`, for example `["Courses", "Articles"]`), followed by the name of the project (`Articles/Literature review`). It can stay empty if there is only one projects root. The references of a project also receive a place in the subjects (every reference has its place in the subjects).
- `archives`, with an optional `cible`. Classification or project that is finished, kept for the record.
- `dissoudre` (dissolve). Collection of no interest of its own, moved to the trash, whose references keep their other collections.
- `hors plan` (outside the outline). Collection left as it is.

The collections already under a projects root or under the archives root have a prefilled fate. Review them only if the user asks. Those under the subjects root are proposals of themes, to keep, rename or merge. A collection excluded by the privacy filter is prefilled « hors plan » and absent from the inventory. Do not try to find out more, the user can change its fate themselves.

## Criteria for a good outline

- Disciplines that are the user's own, as they practice and teach them, rather than an imposed library classification (Dewey, UDC). Between 3 and 12 disciplines or so.
- A theme is justified by the number of references it will receive. Below 5 expected references, merge it with a neighbor, unless the user plans to develop it.
- Two levels by default (discipline, theme). A sub-theme only when a theme exceeds the threshold `seuil_sous_theme` in `config.toml` (40 references by default), and when the division is clear.
- Short names, in the language of the library unless a term is established in the field (« machine learning »), without numbers or sort prefixes. In the singular when it sounds natural (« Memory », « Perception »), in the plural otherwise (« Qualitative methods », « International relations »). Propose these renamings with the rest of the discipline, and make them only with the user's agreement.
- No theme that duplicates a project. A course or an article in preparation is a project, and its references belong in addition to lasting themes.
- A definition that makes it possible to file a new reference without hesitation. It says what the theme covers, and « Includes » or « Excludes » settle the borderline cases between neighbors.
- An old catch-all collection (« Miscellaneous », « To sort », « Readings ») is distributed rather than becoming a theme.

When a proposal rests on an assumption (a tag interpreted, a collection whose sample is heterogeneous), tell the user and ask them the question rather than decide.
