---
name: duplicates
description: Find, judge and merge the duplicates of the Zotero library with zc (step 2 of the cleanup). Use when the user talks about duplicates, doubled items or merging, or when the audit reports probable duplicates.
---

# Duplicates

Duplicates are handled in two stages. `zc` finds the groups and carries out the merge, the agent helps the user judge each group. All the decisions live in `suivi/doublons.toml` (the duplicates file), which is authoritative. Nothing is merged without being decided there. The decisions are written there by `zc duplicates accept` and `zc duplicates reject`, without touching the file.

In this file, the words stored are French in every library. A group is graded `sûr` (certain) or `à juger` (to judge), and its decision is `fusionner` (merge), `distinct` or empty (to judge).

## Procedure

1. **Bring the files in.** `zc` compares the PDFs on the disk, to recognize two items that carry the same PDF and to move an identical copy to the trash during a merge. A file that Zotero has not downloaded yet is not compared, and the identical copy is then kept twice. If the audit (point 6, « Not checked ») or a command reports PDFs missing from the disk, ask the user, in Zotero, Settings › Sync, to set « Download files » to « at sync time », to synchronize and to wait for the download to finish (the exact labels follow the language of Zotero). This holds when the files are synchronized by WebDAV too. If Zotero does not synchronize the files, nothing will come, and the missing files fall under point 5 of the audit. Group this action with the backup (point 5 below), which also asks something of the user. Done when no command reports a missing PDF any more, or when the user has chosen to go on without.

2. **Find.** Run `zc duplicates find`. Done when the command has updated `suivi/doublons.toml` and given the number of certain groups, groups to judge and groups already decided. Run the command again after the files are downloaded, since the items that share a PDF only appear then.

3. **Judge.** Read `suivi/doublons.toml`. Each group is preceded there by one line per item (key, first author, year, title, type, attachments).
   - Groups graded `sûr` without a decision, that is of the same type, with the same DOI and matching titles, or the same title, the same authors and the same year. Present them together, in a few lines. If the user accepts them as a block, run `zc duplicates accept --certain`, with `--except <key> …` (one item of each group) for those they set aside. A certain group without a decision does not enter the plan.
   - Groups graded `à juger`. Before recommending anything, run `zc show <keys of the group>`, which gives the full fields of the items and the start of the text of their PDFs, read locally. Compare the title and the authors printed on the first page of the PDFs with those of the items. Then present the groups in bundles of 10, each with a recommendation (merge or distinct) drawn from the criteria below, a sentence of justification and what was checked. Ask the user to look at the items in Zotero only if doubt remains after this check (PDF missing, scanned or mute, confidential items), saying why.
   - A group can bring together items with different titles that carry the same PDF. They are often duplicates of which one was entered wrongly, but sometimes an item carries the PDF of another (see « Identical PDFs »). The text of the PDF decides. For a merge, choose with the user the item to keep (`--keep`) and, if needed, the right title (`forcer`).
   - Write the decisions through the command, once the answers are given. A group is designated by the key of one of its items. `zc duplicates accept <key> …` merges, `zc duplicates accept --keep <key> …` merges while keeping those items (one per group), `zc duplicates reject <key> … --reason "<reason>"` judges the groups distinct (one command per reason). Only `forcer` (a value imposed on the kept item, for example `{ "date" = "1938" }`) is still written by hand in the file, on a group that is already accepted. A decision already made does not change through a command. To go back on it, edit it in the file.
   - When only some items of a proposed group are duplicates (for example three items that share a wrong DOI, two of which are the same article), run `zc duplicates accept <key> --except <key>`, the first key being that of an item to merge and the keys after `--except` those of the items to take out. The group is merged without them, and each item taken out is recorded as not a duplicate of the others, so that the next search does not propose it with them again. Do not edit `cles` by hand for this.
   - Two items that `zc` has not brought together, although they describe the same publication, are added by hand at the end of the file, as its header shows (`[[groupe]]`, `cles`, `decision = "fusionner"`). The group is kept as long as its items exist.

   Done when each group has a decision, or when the user has chosen to leave some for later.

4. **Plan.** Run `zc duplicates plan`. Read the `.md` report indicated and summarize it to the user, that is the number of groups, the groups set aside and why, the « different values » where the kept item wins, and the related items (« Related », « Connexe » in a French library) whose link passes to the kept item. If the report begins with a warning about PDFs missing from the disk, go back to step 1 before applying, otherwise identical copies will remain in duplicate. Remind the user that Zotero empties its trash after 30 days, and that a merge can no longer be undone afterwards. If the user wants to change something, change the decision (in `suivi/doublons.toml` for a decision already made) and plan again. Done when the user has explicitly approved this plan.

5. **Back up.** Once the plan is approved, if the last backup is more than 24 hours old, ask the user to close Zotero, then run `zc backup`. Done when the command displays the backup folder. The user can then reopen Zotero.

6. **Trial.** Run `zc apply <plan> --trial`, then check the kept items yourself with `zc show` (fields, attachments and notes attached, collections) and that the absorbed items are no longer read. Tell the user what was checked. Done when the trial is checked.

7. **Apply.** Run `zc apply <plan> --all`. If the command is interrupted, run it again as it is, it resumes where it stopped. Present the groups in conflict (items modified since the plan). Those that `zc` says are « left intact » have not been touched, and a new search will propose them again. Those that it says were « Stopped after part of the writes, to check » are half merged. Check them with `zc show`, then, with the user's agreement, either settle the conflict and run the same command again, which finishes the group, or undo what was written with `zc undo <journal>`.

8. **Check.** Run `zc duplicates find` then `zc audit`, and tell the user what remains.

To go back on a merge, run `zc undo <plan>`, summarize the undo report, then follow steps 6 and 7 with the undo plan.

## Identical PDFs

The same PDF can be attached to several items, or twice to the same one (audit, point 6). The different items that share it are also proposed by `zc duplicates find`, to judge. As for duplicates, only the files present on the disk are compared (step 1).

1. Run `zc attachments find`, which writes `suivi/pieces.toml` (the attachments file), one group per PDF present in several copies. The comment of each copy gives the item that carries it and its annotations or notes. If the command reports shared PDFs that are absent from `suivi/doublons.toml`, run `zc duplicates find` again.
2. To know which item the PDF belongs to, run `zc show <keys of the copies>`, which shows each carrying item and the start of the text of the PDF, read locally. Do not open the PDF of a group marked « (confidential item) » by any other means, the user looks at it in Zotero.
3. If the items are duplicates, merge them first (procedure above). The merge moves the identical copy to the trash, and the group disappears from `suivi/pieces.toml` at the next search. For the others, propose:
   - to move to the trash the extra copies or the copies on the wrong item. Never a copy that is annotated or carries a note, which `zc` refuses. If it is on the wrong item, attach it to the right one, and move the other copy to the trash.
   - to keep the copies when they are wanted, for example a chapter and the whole book, or a comment and the target article.
4. Have it approved, then write the decisions through the command, each copy designated by its attachment key (the one the file gives, not that of the item). `zc attachments accept --trash <copy> … --move <copy>=<item> …` for the groups to handle, `zc attachments reject <copy> … --reason "<reason>"` for those to keep (one copy of each group is enough). Then `zc attachments plan`, summarize the report, trial and application as for duplicates.

## Judgment criteria

Merge when the items describe the same publication in the same edition, even if they differ by case, punctuation, a truncated subtitle, a DOI or an ISBN present on one side only, or the form of the author's name (« Merleau-Ponty, M. » and « Merleau-Ponty, Maurice »), with the same year and publisher.

Keep distinct when the items designate different texts, or different states of a text that the user may want to cite separately:
- different editions (different years or publishers, revised edition, reissue with a new preface);
- translation and original, or two translations;
- different volumes or parts of the same work;
- preprint and published version, unless the user wants to keep only the published version;
- review of a book and the book itself.

Two items with the same ISBN but different years or publishers remain distinct. The ISBN of one is probably entered wrongly (a book of 1938 has no ISBN), which step 3 will pick up.

A group of different types (article and conference paper, book and report) is set aside by `zc duplicates plan`. If the items do describe the same publication, accept it anyway (`zc duplicates accept`), then give the two items the same type. `zc metadata types` (step 3) proposes it for each item of the group (case `type_doublon`), and only the case of the item whose type is wrong is accepted. The user can also change the type themselves in Zotero, through the « Item Type » menu of the item. Once the types are equal, run `zc duplicates plan` again. If the items do not describe the same publication, judge the group distinct (`zc duplicates reject`).

When in doubt, present both readings and let the user decide.
