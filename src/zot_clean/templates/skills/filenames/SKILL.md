---
name: filenames
description: Rename the PDF and EPUB files of the Zotero library after their metadata with zc (step 8 of the cleanup), according to the file name template set in Zotero. Use when the user talks about file names, badly named PDFs or renaming, or when the audit reports names that are behind (point 9).
---

# File names

Zotero names the main file of each item after its template (by default « Author - Year - Title »), but only when the item changes on this computer. What `zc` or another computer writes through the API therefore leaves names behind. `zc filenames plan` prepares a plan that changes the name recorded in Zotero, and each computer renames its files on the disk at its next synchronization. The content of the files does not change.

Only the main attachment of each item is renamed, as Zotero does. Linked files, secondary PDFs and names set aside (name already taken in the folder, refused by Windows, too long) stay as they are and are listed. The template is set in Zotero, never in `config.toml`. If `zc` cannot compute it, it refuses and refers to the « Rename Files… » button in Zotero's settings (the exact label follows the language of Zotero).

## Procedure

1. **See what is behind.** Run `zc audit` and read point 9 (and point 5 for the missing files). Done when the user knows how many files would be renamed.

2. **Plan.** Run `zc filenames plan`. The command looks on zotero.org for the files missing from the disk (`--offline` to go without, they are then not renamed). Summarize the report of the plan, that is the number of files, a few examples of old and new names, the attachment titles that change too (a title equal to the old name becomes « PDF »), and the section « Left aside » (« Laissés de côté » in a French library) with its reasons. `zc` deduces the conjunction (« and » or « et » between two authors) from the existing names, otherwise from the language of Zotero. A name not computed for lack of a conjunction is settled by `conjonction` in the `[methode]` section of `config.toml`, according to the language in which the user sees Zotero. Done when the user has explicitly approved this plan.

3. **Back up and trial.** If the last backup is more than 24 hours old, ask the user to close Zotero and run `zc backup`, then to reopen Zotero. Run `zc apply <plan> --trial`, which renames the first files of the list (marked « trial » in the report). Done when the trial is applied without a conflict.

4. **Synchronize and check.** The file is renamed on the disk only by Zotero, at its synchronization. Ask the user to start Zotero's synchronization (green arrow at the top right) and to wait for it to finish. Then run `zc show <keys of the items of the trial>`. Each attachment must carry the new name, without the mention « file missing from the disk ». Done when this is the case for each file. If a file stays missing after the synchronization, do not go on, run `zc undo <plan>` and follow the undo (summarize, trial, synchronization, check).

5. **Apply the rest.** Run `zc apply <plan> --all`. An interrupted command is run again as it is. Ask for a last synchronization of Zotero, and on every other computer that shares the library. Done when the full application is made and synchronized.

6. **Check.** Run `zc audit`. Point 9 should show only the cases left aside. If it reports an attachment that points to a missing file while its folder holds another (failed local renaming), tell the user. `zc filenames plan` can be run again at any time and prepares only what remains. Done when the user has seen what remains and knows what is settled by hand.

## Missing files and WebDAV

The report says how Zotero synchronizes the files, from its profile.

- **Through zotero.org.** A file missing from the disk but stored on zotero.org is renamed, Zotero will name it when it downloads it. A file that cannot be found anywhere is not renamed (point 5 of the audit).
- **Through WebDAV, or with file synchronization turned off.** A file missing from the disk is never renamed, it is only listed. The files present are renamed as elsewhere, but this case has not yet been verified with a WebDAV server. At step 4, verify with particular care, on this computer and, if there is one, on another computer or a tablet after its synchronization. In case of doubt, undo and rename instead with the « Rename Files… » button in Zotero's settings.

An attachment presented as « (confidential item) » appears only by its key. Do not look for its name. If it is left aside, ask the user to look at it themselves in Zotero.
