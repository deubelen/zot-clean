---
name: inbox
description: Sort the new references of the Zotero library with zc (ongoing management), that is find the duplicates, correct the metadata and file each reference in a theme of the subjects, in a single plan. Use when the user asks to sort the Inbox or to file their new references, or when the audit reports references in the Inbox.
---

# Inbox triage

The triage handles the references of the Inbox and those that have no place in the subjects, whether they are outside any collection or arrived directly in a project (for example a course). It takes up steps 2, 3, 5 and 6 of the cleanup, limited to these references, and ends in a single plan. The tags follow the rules already accepted in `suivi/tags.toml` (automatic tags removed, variants and statuses brought back to their form), without deciding anything new. A reference of a project stays there and receives its theme in addition.

The Inbox and the projects roots are the collections named in `config.toml` (`zc config show`). The filing decisions (`suivi/rangement.toml`) are written by `zc subjects accept` and `reject`, without touching the file.

## Procedure

1. **Prepare.** Run `zc inbox prepare`, then read the report `rapports/inbox-<date>.md`. It gives the groups of duplicates and the metadata cases to judge, then one line per reference (author, year, title, type, journal or work, current collections) with the neighbouring themes, that is those where other items by the same author or from the same journal are filed. « no neighbouring theme found » only means that nothing of the sort is filed in the subjects yet. Done when the report is read.

   The tracking files of steps 2 and 3 (`suivi/doublons.toml`, `suivi/metadonnees.toml`) are shared with the whole library and can hold groups and cases of items outside the triage. In the triage, write each decision by the keys that the report lists, never with `--certain` or `--obvious`, which decide every group or case of the file. Take from the skills `duplicates` and `metadata` only their judgment criteria and the way of presenting, the triage having its own plan.

2. **Duplicates.** Judge the groups that the report lists as the skill `duplicates` describes it, verifying with `zc show`. A reference of the Inbox is often a second entry of an item already filed. Keep then the old one (`zc duplicates accept --keep <key of the old one>`), which already has its themes. The decisions are written by `zc duplicates accept <key>` and `zc duplicates reject <key>`, a group being designated by one of its items, without touching the file.

3. **Metadata.** Judge the cases that the report lists as the skill `metadata` describes it, the obvious ones in a block and the doubtful ones in bundles, then write the decisions with `zc metadata accept <key>=<number> …` (`<key>` alone retains the proposal in `choix`) and `zc metadata reject <key> …`.

4. **File.** For each reference, choose a theme of `plan.md`, from its definition and its « Includes » and « Excludes » lines.
   - The neighboring themes of the report are hints, not answers. An author can write in several fields.
   - When the title is not enough, run `zc show <key>` (abstract, journal, start of the PDF).
   - Present the proposals to the user, in one block for those where the theme is obvious (clear definition, matching neighboring theme), in bundles of at most 10 for the others, each with the theme and its justification.
   - After their agreement, write the decisions with `zc subjects accept <key>=<path> …` (path of the theme without the subjects root), with their corrections. `zc` finds by itself what the reference leaves, the Inbox for a reference of the Inbox, nothing for a reference of a project, which stays there.
   - If no theme fits, propose the closest one, or a new theme with its place in the tree and its definition. If the user accepts a new theme, add it to `plan.md`, run `zc subjects validate`, then `zc subjects validate --save` after their agreement. In the meantime, the reference stays in the Inbox, without an accepted entry. Once the outline is saved, write its place with `zc subjects accept <key>=<path>`.
   - For a reference presented as « (confidential item) », ask the user where to file it.
   - A reference outside the Inbox that the user decides to leave outside the subjects (title too vague, reference kept only in its project) is noted with `zc subjects pending --leave-out <key>…`, after their agreement. It no longer comes back to the triage or in the audit as long as it stays in the same collections. A reference of the Inbox, for its part, is always filed.

   Done when the user has judged the references they wanted to handle now. The others stay in the Inbox.

   If the report points out « tags outside the families, no rule », present them to the user with the reference that carries them. According to their answer, add the rule with `zc tags add '<name>' --action delete|keep|concept|status|merge --user` (action `keep`, `concept`, `delete` or `merge`, with `--target '<target name>'` for a concept or a merge), as the skill `tags` describes it, without touching the file. Nothing is to be done if `suivi/tags.toml` does not exist yet.

   If the report points out a reference « without a citation key », Better BibTeX did not give it one on arrival. Offer the user to fill it in in Zotero (right-click, Better BibTeX › Fill). A duplicate key that touches a sorted reference is separated by the plan itself, the oldest item keeping the key (skill `citation-keys`).

5. **Plan.** Run `zc inbox plan`. Summarize the report of the plan, that is the merges, the fields added or corrected, the tags changed, the citation keys separated, the files renamed, the themes created, the place of each reference and those that stay in the Inbox. Done when the user has explicitly approved this plan.

6. **Apply.** A small triage plan, that is one touching fewer items than `petit_plan_de_gestion` (`[ecriture]` section of `zc config show`, 50 by default), is applied at once, without a trial or a recent backup. Once the plan is approved, run `zc apply <plan> --all`, check a few items with `zc show`, then tell the user what was done. A larger plan (as many items as the threshold or more) follows the usual sequence. If the last backup is older than the configured delay (`delai_heures`, 24 hours by default), ask the user to close Zotero and run `zc backup`, then `zc apply <plan> --trial`, check with `zc show`, tell the user, and `zc apply <plan> --all`. A plan that creates a new theme touches collections, which Zotero does not always pick up by itself. Ask the user then to start a synchronization by hand at the end (green arrow at the top right).
