---
name: metadata
description: Correct the DOIs and complete the empty fields of the Zotero library with zc (step 3 of the cleanup), and judge uncertain cases with the user. Use when the user talks about metadata, DOIs, missing fields or incomplete items, or when the audit reports missing metadata.
---

# Metadata

Step 3 is done in three sub-steps, in this order, the identifiers (DOI and ISBN), the item types, then the completions (empty fields). `zc` queries Crossref and OpenAlex for articles, the BnF, the Sudoc and Open Library for books, writes into the plan what is certain, and puts the rest in `suivi/metadonnees.toml` (the metadata file). This file is authoritative for the decisions. The agent helps the user judge the uncertain cases.

In this file, the words stored are French in every library, for instance `classe = "évident"` or `"douteux"`, `choix`, `forcer`, and the names of the cases (`doi_malforme`, `type_doublon`…).

## Procedure

1. **Look for identifiers.** Run `zc metadata identifiers`. The first pass can take half an hour on a large library, the following ones a few seconds. If the command reports a source set aside or OpenAlex searches skipped, tell the user. Done when the command has given the number of cases to judge and, if there are any, the path of a plan.

2. **Judge the cases.** Read `suivi/metadonnees.toml`. Each case is preceded there by a line about the item (key, author, year, title, type, journal or work, current DOI), then by its numbered proposals, each with its source, a note (title, author, year, type, journal or work, volume, pages, publisher, similarity) and an opinion, « concorde » (matches) or what differs from the item (« titre 0.72, auteur »), written in French in every library since it is stored in the file. `zc` has already sorted the cases. `classe = "évident"` (obvious) when a single proposal matches in every respect, its number being in `choix`, or when a DOI unknown to doi.org has no other lead than its removal (`doi_inconnu` with a single proposal), and `classe = "douteux"` (doubtful) otherwise.
   - Handle the cases without a decision in this order: `doi_malforme`, `doi_inconnu` and `isbn_invalide`, then `doi_discordant` and `isbn_discordant`, then `doi_manquant` and `isbn_manquant`.
   - `zc` has already verified the obvious ones (the proposed DOI comes from Crossref or OpenAlex, a DOI to remove was looked up on doi.org). Go through them without redoing these checks, rereading only the note and the opinion of each. For a doubtful one, read the opinion of each proposal, then `zc show <key>` and the resolution of the DOI. An obvious case that does not survive the check moves to the doubtful ones, and a doubtful one whose opinion explains itself (translated title, subtitle specific to the item) can become obvious. Then present two groups.
     - **Obvious.** All the data match according to the criteria below (title up to case, punctuation or a subtitle, first author, year within one year, same journal or same work, same type) and the identifier resolves. Present them in a single block, with their number, what was checked and one line per case, which the user can go through. A single approval is enough for the whole block.
     - **Doubtful.** The others. Present them in bundles of at most 10, grouped by what differs (year, author, journal…), each with a recommendation (the number of the proposal to retain, or reject), a sentence of justification drawn from the criteria below and what was checked.
   - Write the decisions through the command, without touching the file. Block of obvious cases approved, `zc metadata accept --obvious`, with `--except <keys>` for those the user set aside. Doubtful ones, `zc metadata accept <key>=<number> …` for the proposal retained and `zc metadata reject <key> …`. When an item has several cases (DOI and ISBN), aim at each by its problem, `<key>:<problem>=<number>` (`zc` gives the problems if one is missing). A case left pending needs nothing.
   - On the user's explicit request, reject all the remaining cases of one kind at once.

   Done when the user has judged the bundles they wanted to handle now. The remaining cases block nothing.

3. **Plan.** Run `zc metadata identifiers` again, which takes the accepted cases into its plan. If the command reports an error in `suivi/metadonnees.toml`, correct the line indicated. Read the `.md` report of the plan and summarize it to the user. Done when the user has explicitly approved this plan.

4. **Back up, trial, apply.** If the last backup is more than 24 hours old, ask the user to close Zotero and run `zc backup`. Then `zc apply <plan> --trial`, check the items of the trial with `zc show`, tell the user, and `zc apply <plan> --all`. An interrupted command is run again as it is.

5. **Types.** Run `zc metadata types`. The safe changes go to the plan, the others into `suivi/metadonnees.toml` with the sub-step `types`. Judge them as in step 2, with the criteria below. Run the command again to get the plan, then the same sequence as in step 4. `zc` only proposes a type for items that have a DOI known to the sources, for « Document » items (the Zotero type « Document ») that look like a known book and for duplicates to merge that have different types. The report lists the « Document » items left without a proposal. Their type, like that of any wrongly typed item without a DOI, is changed by hand in Zotero (« Item Type » menu of the item), an action to ask of the user.

6. **Complete.** Run `zc metadata complete`. Summarize the report, that is the fields filled in and their number, the items skipped because their DOI or ISBN is still to be judged, and the main « different values », left as they are. If the user wants to impose a value from the source, or empty a wrong field, add at the end of `suivi/metadonnees.toml` a complete `forcer` case, on the model given at the top of the file, then run again. The report then counts the « imposed values » separately. Then the same sequence as in step 4 with this plan.

7. **Check.** Run `zc audit` and tell the user what remains (cases pending, items without an author or without a date, which are corrected by hand in Zotero or with the user).

To go back on an applied plan, run `zc undo <plan>`, summarize the undo report, then follow step 4 with the undo plan.

## Judgment criteria

Accept a candidate when it designates the same publication as the item, that is a title identical up to a subtitle, punctuation or case, the same first author, the same journal or the same work when both are known, a year equal within one year.

Reject a candidate that designates another publication, even a close one:
- review of the book or of the article, erratum, reply or comment;
- another chapter of the same work;
- another edition, translation, abridged version;
- different type (book for a chapter, article for a conference paper).

According to the problem:
- `doi_discordant`. If the item is a chapter and the DOI is that of the book, retain the candidate of the chapter if there is one, otherwise remove the DOI (proposal 1). If the item and the source do describe the same publication (translated title, title abridged in Zotero), keep the DOI (proposal 2).
- `doi_inconnu` or `doi_malforme`. Prefer a candidate whose DOI differs from the current one by only one or two characters, a sign of a typing mistake. Otherwise remove the DOI. A candidate whose journal differs from that of the item remains doubtful, even if the rest matches. Show it to the user with the two journals, one of the two being wrong.
- `isbn_discordant`. The ISBN is valid but the record found carries another title. Compare with `zc show`. If it is indeed the book (translated title, series title), keep the ISBN (proposal 2). Otherwise remove it (proposal 1) or retain a candidate found by title, with the criteria of `isbn_manquant`.
- `doi_manquant`. Accept only if all the criteria above are met.
- `isbn_manquant`. Several editions are often proposed. Retain the one whose year and publisher match those of the item. If the item has neither, ask the user which edition they own or cite, since the pages cited depend on it.
  When the note says the ISBN of the item was removed earlier by a judged case, remind the user of that decision before proposing to accept. The refused `isbn_retire` case of the item keeps the ISBNs ruled out then, which `zc` no longer proposes. It needs no decision.
- `isbn_invalide`. Proposal 1 keeps the valid ISBNs of the field (or removes it if there are none). The books found by title follow, the closest to the current ISBN first, and the note says when one differs by only one or two characters, a sign of a typing mistake. Prefer it if it matches the item. A book found with certainty has already replaced the invalid ISBN in the plan.
- `livre_possible`. A « Document » item seems to be a book. Accept only if title, author and year match. A working paper, a report or a handout remains a document.
- `type_different`. Accept when the source does describe the item under another type (article that is really a chapter, conference paper published in proceedings). Reject when the item is the review of a book that the source describes as a book, or a chapter that the source mistakes for the whole book. Values with no equivalent in the new type are copied into the Extra field, nothing is lost.
- `type_doublon`. Two items judged duplicates in step 2 do not have the same type, and the merge waits for them to have it. Each item of the group receives a case, which proposes the type of the other. Choose the right type with `zc show` (journal or proceedings, publisher, PDF), accept the case of the item whose type is wrong and reject the other. Accepting both would swap the types, `zc` refuses it. Once the plan is applied, run `zc duplicates plan` again.

When in doubt, run `zc show <key>`, which gives all the fields of the item and the start of the text of its PDF (title, authors, journal, year printed on the first page). If it is not enough, leave the case without a decision and tell the user what was checked and what prevents deciding. They can look at the item in Zotero.
