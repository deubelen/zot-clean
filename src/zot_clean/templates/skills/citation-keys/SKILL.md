---
name: citation-keys
description: Put the citation keys of the Zotero library in order with zc (step 7 of the cleanup), that is separate the duplicate keys and tidy into Zotero's field the « Citation Key: » lines left in Extra, the missing keys being filled in by Better BibTeX. Use when the user talks about citation keys, Better BibTeX, LaTeX or Markdown, or when the audit reports missing, duplicate or Extra-resident keys.
---

# Citation keys

Better BibTeX (BBT) computes the keys and fills in by itself those that are missing. `zc` does only what BBT does not, that is separate the duplicate keys (the oldest item keeps the key, the others receive a suffix a, b…) and tidy into Zotero's « Citation Key » field the « Citation Key: » lines left in Extra. A unique key is never touched, even if it does not follow BBT's formula. Without an active BBT, only the separation of duplicates is done.

The words stored in `suivi/cles.toml` (the citation keys file) are French in every library (`[[double]]`, `[[extra]]`, `cles`…). On the command line, the decisions are written in English (`keep`, `skip`, `native`, `extra`) and `zc` stores the French word.

## Procedure

1. **Read the audit.** The « Citation keys » section (« Clés de citation » in a French library) of `rapports/audit-<date>.md` gives the state of BBT, the missing keys, the duplicate keys and those left in Extra. It lists a Better BibTeX setting only when one must change, read in the Zotero profile, so the user is asked nothing when the section lists none. If it says that BBT regenerates the key of an item on every change, ask the user to untick « Regenerate citation key when item changes » in Zotero › Settings › Better BibTeX, otherwise each item modified by `zc` would change its key. Done when the section lists no setting to change.

2. **Missing keys.** They are filled in in Zotero, by BBT. Usually BBT gives its key to an item a few seconds after it arrives (« Automatically fill citation key after »). For the items left without a key, guide the user. Select the items (the whole library will do), then right-click, Better BibTeX › Fill, which fills in only the empty keys. Never propose « Refresh », which also recomputes the existing keys and would break the texts that cite them. If the fill delay is 0, propose putting it back to 2 seconds. Done when the user has filled in the keys they wanted.

3. **Plan.** Run `zc citation-keys plan`. A refusal because Zotero is too old or because of Better BibTeX 7 is explained to the user as it is, the step waits for the update. Read the report of the plan and `suivi/cles.toml` if it exists. Done when the report is read.

4. **Judge the cases of `suivi/cles.toml`.** Verify a doubtful case first with `zc show <keys>`.
   - `[[double]]`. The rule applies without a decision. If the user knows that a text cites a given item under this key, that item keeps it (`<item>=keep`). To leave a duplicate as it is, `<item>=skip`, with the key of one of its items.
   - A duplicate « sent back to step 2 » brings together items that are perhaps duplicates. Judge them with the skill `duplicates`. The merge settles the key, and its report says which key disappears.
   - `[[extra]]`. The Extra line differs from the native key. Ask the user which one their texts use, then `<item>=native` (keep the native key), `<item>=extra` (take that of the line) or `<item>=skip`.

   Present the cases in one block, with a recommendation for each. After agreement, write the decisions through the command, without touching the file, in a single line for all the cases, for example `zc citation-keys decide ABCD1234=keep EFGH5678=native --reason "<reason>"` (the reason holds for all the cases of the command, it is optional). Only the cases that wait change, a decision already made is changed by hand in the file. Then run `zc citation-keys plan` again. Done when the user has judged the cases they wanted to handle now. The others stay out of the plan.

5. **Have it approved.** Summarize the report, that is the number of duplicate keys and of items that receive a suffix, the Extra lines tidied and the « Warning » section (« Attention » in a French library). Remind the user that an item that receives a suffix changes its key, and that a text that cited it is to be updated. Done when the user has explicitly approved this plan.

6. **Back up, trial, apply.** If the last backup is older than the configured delay (`delai_heures` in `zc config show`, 24 hours by default), ask the user to close Zotero and run `zc backup`. Then `zc apply <plan> --trial`, whose groups cover each kind of change (listed in the report). Check these items with `zc show` (citation key and Extra), tell the user, then `zc apply <plan> --all`. An interrupted command is run again as it is. Done when the full application is made.

7. **Check.** After Zotero's synchronization, run `zc citation-keys plan` again, which should find nothing more to do apart from the cases set aside or to judge, then `zc audit`. Done when the « Citation keys » section reports only what the user chose to leave.

An item that receives a suffix keeps a key drawn from the title of the item that keeps the key. When the two titles differ, the report points it out (« key taken from the title of another item »). If the user wants a key drawn from its own title, offer them, once the plan is applied and synchronized, to regenerate the key of that item alone in Zotero (right-click the item, Better BibTeX › Refresh). This is the only exception to the rule of not proposing « Refresh », since this key has just changed and no text cites it yet.

To go back on an applied plan, run `zc undo <plan>`, summarize the undo report, then follow step 6 with the undo plan.

An item presented as « (confidential item) » appears only by its item key, and the citation key it shares is hidden. For an opinion about it, ask the user to look at it themselves in Zotero.
