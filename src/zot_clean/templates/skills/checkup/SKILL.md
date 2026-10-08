---
name: checkup
description: Regular checkup of the Zotero library with zc (ongoing management), that is read what has changed since the last audit, carry into plan.md the themes created, renamed, moved or deleted in Zotero, propose the splitting of themes that are too big and send each new problem to the command that corrects it. Use at the start of a work session, when the user asks where their library stands, or when the audit reports new points.
---

# Regular checkup

The checkup lives in `zc audit`. Each audit keeps a snapshot of its points, and its report opens on what has appeared and what has been settled since the audit of a previous day. The twelfth check, « Subjects outline » (« Plan du fonds » in a French library), compares `plan.md` with the collections of the subjects in Zotero. After the cleanup, Zotero is authoritative and `plan.md` follows it. The user can therefore create, rename, move or delete a theme directly in Zotero.

## Procedure

1. **Audit.** Run `zc audit`, then read in `rapports/audit-<date>.md` the section « Since the audit of … » (« Depuis l'audit du … ») and check 12. Summarize to the user in a few sentences what is new, what is settled, and propose an order of work starting with what matters most to them. Done when the user has chosen what they want to handle now.

2. **Themes changed in Zotero.** If check 12 reports a theme renamed, moved, created or deleted in Zotero, run `zc subjects track`, which shows the changes to carry into `plan.md` without writing anything.
   - Present them to the user, specifying that a deleted theme is removed from `plan.md` with its sub-themes and its definition, and that the filing decisions that targeted it are removed.
   - After their agreement, `zc subjects track --save`, which writes `plan.md`, corrects the paths of the tracking files and records the validation.
   - For each theme added, propose a definition (one sentence, with « Includes » and « Excludes » if the boundary with a neighbor is blurred), from its name, its place in the tree and the titles given by `zc subjects titles <path>`. After agreement, write it in `plan.md` (the fields are `Includes` and `Excludes` in an English library, `Inclut` and `Exclut` in a French one, both accepted), then `zc subjects validate --save`.

   Done when check 12 no longer reports a changed theme or a theme without a definition.

3. **References outside the subjects, and Inbox.** Handle them with the skill `inbox`. Done when the user has judged those they wanted to handle.

4. **New duplicates and metadata.** Run again the commands of steps 2 and 3 on the whole library (`zc duplicates find`, `zc metadata identifiers`, `types`, `complete`) and follow the skills `duplicates` and `metadata`. The cases already judged are retained there and the sources kept in cache, so only the new cases come back. Done when the new cases are judged or left pending by the user.

5. **Themes that are too big.** A theme that exceeds the threshold of `config.toml` (`seuil_sous_theme`) is reported as information. If the user wants to split it, run `zc subjects titles <path>` and read all the titles.
   - Propose a split only if it is clear, that is if two to five sub-themes emerge by themselves, each with a definition that makes it possible to file a new reference without hesitation. Otherwise, tell the user that the theme can stay as it is.
   - Present the sub-themes and their definition. After agreement, write them in `plan.md`, then `zc subjects validate` and `zc subjects validate --save`.
   - Propose the place of each reference, in one block for those that are obvious, in bundles of at most 10 for the others. Write the accepted decisions in `suivi/rangement.toml` (`action = "déplacer"`, `cible` = path of the sub-theme, `depuis` = key of the collection of the theme, given by the titles report, `source = "agent"`, `decision = "accepter"`). A reference that stays in the theme itself has no entry.
   - Run `zc subjects plan`, summarize the plan, and after agreement apply it as in step 5 of the cleanup (trial, check with `zc show`, then `--all`).

   Done when the user has decided for each theme reported, split or left as it is.

## Points of attention

- `zc subjects track` does not touch Zotero. It makes `plan.md` follow Zotero, never the reverse.
- A theme beyond the depth allowed (`profondeur_max`) is not carried into `plan.md`. Point it out to the user, who will move it up a level in Zotero or turn it into a concept.
- A theme of the outline « not in Zotero yet » is a theme that the user has just added to `plan.md`. `zc subjects plan` creates it.
- Confidential items stay hidden in the titles report. Ask the user where to file them.
