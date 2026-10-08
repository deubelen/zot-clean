# zot-clean

*Put and keep order in your Zotero library.*

[Version française du guide](https://github.com/deubelen/zot-clean/blob/main/src/zot_clean/templates/fr/guide.md)

`zot-clean` is for people whose Zotero library has outgrown them (duplicates, incomplete metadata, collections in disorder, thousands of automatic tags). It helps to

1. **clean up**, step by step, every change being simulated, tried on a few items, then journaled so that it can be undone;
2. **keep order**, by regularly sorting new references and by a checkup made at every audit.

Reading, summarizing and discovering papers are left to the Zotero extensions that already do them (see [Tools that go with it](#tools-that-go-with-it)).

The mechanical tasks go through the `zc` command. The tasks of judgment (deciding whether two items are duplicates, designing an outline of the classification, filing a reference) are done with a command-line agent, such as Claude Code or Codex, which relies on `zc` and on the instructions shipped with it.

> **Version 0.4, still being fine-tuned.** The eight cleanup steps, the sorting of new references and the regular checkup are available. The tool has not yet been tried by anyone but its author. The design choices are recorded in [docs/decisions.md](https://github.com/deubelen/zot-clean/blob/main/docs/decisions.md) (written in French).

## Two languages

Each library is declared French or English when its working folder is created with `zc init` (`--library-language fr` or `en`, asked for in a terminal when missing). This fixes the language of the conventions proposed (names of the root collections and of the tags, definitions), of the reports and of the messages of `zc`, and never that of the bibliographic data, which stay as they are in Zotero. The choice does not change afterwards, and `zc config show` displays it. The commands and options are in English whatever the language of the library, and the agent speaks the language of the user. The step-by-step guide and the default method are available in both languages, and `zc init` copies the version of the library into the working folder. Version 0.3.2 had French command names. `zc` now refuses them and gives the new name.

## What is available

The steps are best followed in the order of the table. Each can be interrupted and resumed later, the progress staying in the working folder.

| Step | Commands | What it does |
|---|---|---|
| 0. Audit | `zc audit` | Twelve read-only checks, dated report in `rapports/`. Also says what has appeared and what has been settled since the previous audit. |
| 1. Method | `config.toml` | Rereading of the conventions of the default method (`method.md`) (roots, reading statuses, prefixes), to be adapted if needed. Nothing is changed in Zotero. |
| Backup | `zc backup` | Copy of the Zotero folder, with Zotero closed. Required before any bulk change. |
| 2. Duplicates | `zc duplicates find`, `plan` | Spots duplicates, which are judged with the agent, then merges them the way Zotero does. If the kept item carries a suffixed citation key ("dupont2002a") and a merged item the base key ("dupont2002"), the kept item takes the latter. |
| 2. Identical PDFs | `zc attachments find`, `plan` | Puts the extra copies of one PDF in the trash or attaches them to the right item, never losing an annotated copy. |
| 3. Metadata | `zc metadata identifiers`, `types`, `complete` | Fixes DOIs and item types, fills empty fields from Crossref, OpenAlex, the BnF, the Sudoc and Open Library. Filling in (`complete`) never replaces a value that is already there. The corrections do change some, each one announced in the report of the plan. A malformed DOI is put back in shape, and a DOI that exists nowhere is replaced when the right one is found with certainty. A change of type empties the fields that the new type does not accept, after copying their value into Extra. |
| 4. Outline of the subjects | `zc subjects inventory`, `validate` | Proposes with the agent an outline of the classification (disciplines, themes), to be validated in `plan.md`. Nothing is changed in Zotero. |
| 5. Filing | `zc subjects plan`, `pending` | Transforms the collections according to the validated outline and distributes the items, in several passes. |
| 6. Tags | `zc tags inventory`, `plan` | Removes automatic tags and imported keywords, brings variants back to a single form and the reading statuses to those of the method, draws concepts from the existing tags. |
| 7. Citation keys | `zc citation-keys plan` | With Better BibTeX, separates duplicate citation keys and puts into the "Citation Key" field those that stayed in Extra. A unique key is never changed. |
| 8. File names | `zc filenames plan` | Renames the main file of each item after the file-name template set in Zotero (by default "Author - Year - Title"). The new name goes through zotero.org, and each computer renames its files at its next sync. |
| Management, sorting | `zc inbox prepare`, `plan` | Sorts the new references (Inbox and outside the subjects) in a single plan, with duplicates, metadata, filing in a theme, tags according to the rules of step 6, citation keys and file names. |
| Management, checkup | `zc audit`, `zc subjects track`, `zc subjects titles` | Says what has changed since the previous audit, carries over into `plan.md` the themes created, renamed or moved in Zotero, helps to split a theme that is too big. |

There are also `zc show`, which shows an item in full to judge a case, `zc config show`, which displays the configuration, as well as `zc apply`, `zc undo` and `zc journal`, described below. `zc --help` gives the list of commands, and `--help` after any command or subcommand (for example `zc duplicates find --help`) the detail of its options.

## How the tool changes the library

No command changes the library directly. Each step first prepares a **plan**, with a readable report that says item by item what is going to change. Then

- `zc apply <plan> --trial` applies only the first groups, to check the result in Zotero;
- `zc apply <plan> --all` applies the rest, and only if the trial has taken place and a backup less than 24 hours old exists;
- every change is written in a journal, and `zc undo` prepares the plan that reverses it.

Writes go through the Zotero web API, never through the local database, so as not to damage syncing. These safeguards are in the code and do not depend on the prudence of the agent.

## Installation

The step-by-step guide, `guide.md`, which `zc init` copies into the working folder along with `method.md`, details each step, from opening a terminal to the first cleanup, on macOS as on Windows. You need

- Zotero 7 or a later version, installed on the computer;
- a zotero.org account with syncing turned on, since `zc` writes to the library through the Zotero server;
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs `zot-clean` and, if needed, the Python it asks for (3.11 or later);
- for the steps of judgment, a command-line agent, such as [Claude Code](https://claude.com/claude-code) or [Codex](https://openai.com/codex/).

Step 7 (citation keys) also needs Zotero 8 and the [Better BibTeX](https://retorque.re/zotero-better-bibtex/) extension 8, or later versions. The other steps do without them.

The installation is done from GitHub.

```
uv tool install git+https://github.com/deubelen/zot-clean
```

To update the tool, run `uv tool install --reinstall git+https://github.com/deubelen/zot-clean` (`uv tool upgrade zot-clean` does not see a new version of a tool installed from a Git repository), then `zc init --update` in the working folder. This second command replaces the agent's instructions, the guide and the method with those of the new version, without touching the configuration or the decisions already made.

## First steps

```
zc init ~/Zotero-work        # creates the working folder, asks for the language and the Zotero API key
cd ~/Zotero-work
zc audit                     # state of the library, report in rapports/
```

`zc init` explains how to create the API key on zotero.org. It is better to type it yourself in the terminal, without going through the agent. The audit changes nothing. It reads a temporary copy of the Zotero database, erased after use. The working folder keeps the French names of its folders and files (`rapports/` for the reports, `plans/`, `journal/`, `suivi/` for the follow-up), whatever the language of the library.

The default method (`method.md`) explains the proposed organization (Inbox, projects, subjects by disciplines and themes, archives) and how to adapt it in `config.toml`. An English library gets the roots `Inbox`, `Projects`, `Subjects` and `Archives`, the reading statuses `1 to read`, `2 reading` and `3 read`, and the private tag `_private`.

For what follows, open Claude Code, Codex or another agent in the working folder and ask it where the library stands. It finds its instructions there (`AGENTS.md`) and a guide for each step (`.agents/skills/`). It runs the audit, summarizes it and proposes an order of work. It asks for your agreement before each application.

## Tools that go with it

`zot-clean` does not read your PDFs for you, summarize them or suggest readings. Several Zotero extensions do that inside Zotero, among them [Beaver](https://forums.zotero.org/discussion/126573/) (questions about the library answered with the passages cited, reading assistant, search beyond the library), [llm-for-zotero](https://github.com/yilewang/llm-for-zotero) (summaries, comparisons and explanations in the reader, free and open source) and [Scite](https://scite.ai) (how an article is cited elsewhere, in support or in contrast). They give better answers on a library that has been cleaned. Some of them can also add tags or file items, one at a time after your approval. For the whole library, the steps of `zot-clean` remain safer, with their plan, trial and journal. Like the agent, these extensions send what they read to their provider, and they do not know the items kept out of sight in `config.toml`.

## Privacy

The `zc` commands work locally. They leave the computer only to write to Zotero through its API and to query the metadata sources (Crossref, OpenAlex, BnF, Sudoc, Open Library), by identifier or by title.

When an agent helps you, the titles, abstracts and notes it reads are sent to its provider (Anthropic, OpenAI…). To keep some items out of sight, declare in `config.toml` tags (for example `_private`) or collections to exclude. These items are still processed (their duplicates are merged, their DOI checked), but the audit, the follow-up files and the reports designate them only by their key, followed by "(confidential item)". They are never looked up by their title at the metadata services. To decide about them, the agent asks you to look at them yourself in Zotero.

Only the personal library is cleaned. Group libraries are not modified.

## Licence

MIT, see the `LICENSE` file.
