# Step-by-step guide

This guide goes with a first session of `zot-clean`, from the installation to the first cleanup. It assumes no technical knowledge, only that you can copy a line into a terminal and press Enter. Allow half an hour for the installation and the first audit.

If a word stops you, the [glossary](#glossary) at the end of the page explains it.

## Before you start

You need

- **Zotero 7** or a later version, installed on your computer (step 7, on citation keys, needs Zotero 8 and the Better BibTeX extension 8 or later);
- **a zotero.org account with syncing turned on** (Zotero › Settings › Sync). `zot-clean` writes to your library through the Zotero server, and your computer then receives the changes by syncing, as if they came from another one of your devices;
- **a command-line agent**, such as [Claude Code](https://claude.com/claude-code) or [Codex](https://openai.com/codex/), for the steps that call for judgment (deciding whether two items are duplicates, designing an outline of the subjects). The audit and the installation do without one;
- room on the disk for a backup of your Zotero folder.

Two precautions apply to everything that follows.

- **The cleanup steps never touch your library without your agreement.** Each one first prepares a plan, with a report that says item by item what will change. You read it, you try it on a few items, you check in Zotero, and only then do you apply the rest. Everything that is applied can be undone.
- **What the agent reads goes to its provider** (Anthropic for Claude, OpenAI for Codex). If some references are confidential, declare them before working with the agent (see [Keeping items out of sight](#keeping-items-out-of-sight)).

## 1. Open a terminal

The terminal is a window where you type commands.

- **macOS.** Open the *Terminal* application (in Applications › Utilities, or by typing "Terminal" in Spotlight).
- **Windows.** Open *PowerShell* (Start menu, type "PowerShell").

In this guide, a command appears in a gray box. Copy it, paste it into the terminal, then press Enter. Whatever follows a `#` is a comment, you do not need to type it.

## 2. Install uv

`uv` is a small tool that installs `zot-clean` and the Python it needs, without changing anything else on your computer.

On macOS or Linux, copy into the terminal:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, in PowerShell:

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then close the terminal and open a new one, so that it finds the `uv` command. To check, type `uv --version`. A line like `uv 0.8.…` should appear.

## 3. Install zot-clean

```
uv tool install git+https://github.com/deubelen/zot-clean
```

Check with `zc --help`, which should show the list of commands.

If the terminal answers `zc: command not found` (macOS) or does not recognize the name `zc` (Windows), the folder where uv installs its tools is not yet known to the terminal. Run

```
uv tool update-shell
```

then close the terminal, open a new one and try `zc --help` again.

## 4. Create the Zotero API key

`zot-clean` needs a key to write to your library. It is a kind of password specific to this use, which you can revoke at any time without touching your Zotero password.

1. Open [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new) and sign in with the account that Zotero syncs on this computer (its name appears in Zotero › Settings › Sync). If you have two accounts, for example a personal one and an institutional one, a key created on the other one will be refused, since `zot-clean` would then change a different library from the one on your computer.
2. Give the key a name, for example "zot-clean".
3. Tick **Allow library access**, **Allow notes access** and **Allow write access**.
4. Save (*Save Key*). Zotero shows the key, a string of about twenty letters and digits. Leave the page open, you will copy the key in the next step.

Type this key yourself into the terminal, without handing it to the agent. It gives the right to change your whole library.

## 5. Create the working folder

`zot-clean` keeps everything it produces (configuration, reports, plans, journal of the changes) in a working folder, separate from the Zotero folder. Choose a folder outside iCloud, OneDrive or Dropbox, for example `Zotero-work` in your home folder.

```
zc init ~/Zotero-work
```

The command

1. asks for the language of the library, French or English (`--library-language fr` or `en` to give it in advance), which fixes the language of the proposed conventions (names of the root collections and of the tags), of the reports and of the messages of `zc`. It never touches the data of your references, and it does not change afterwards;
2. looks for your Zotero database (in `~/Zotero` by default, otherwise it asks where it is, which Zotero › Settings › Advanced › Files and Folders tells you);
3. asks for the API key, which is not displayed while you paste it (this is normal), and checks its rights and its account, which must be the one that Zotero syncs. If Zotero has never synced your library, it does not ask for a key and first tells you to set up syncing;
4. offers an OpenAlex key, optional, which helps to find missing DOIs (Enter to skip);
5. asks for a contact email address for the metadata services (optional, Enter to skip);
6. writes the configuration (`config.toml`), the instructions for the agent (`AGENTS.md`) and the working folders.

Then go into the folder:

```
cd ~/Zotero-work
```

Every `zc` command is run from this folder. `zc config show` displays the configuration it reads, including the language of the library.

The folders and files that `zc` creates in the working folder keep their French names, whatever the language of the library (`rapports/` for the reports, `plans/` for the plans, `journal/` for the journal, `suivi/` for the follow-up of each step). The reports, messages and conventions are in the language of the library.

## 6. First audit

```
zc audit
```

The audit changes nothing. It reads a temporary copy of your Zotero database and writes a dated report in `rapports/` (for example `rapports/audit-2026-10-01.md`). The terminal shows its summary, twelve checks marked "OK", "Info" or "To review":

1. overall figures;
2. references filed in no collection;
3. probable duplicates;
4. missing metadata (author, year, DOI, ISBN);
5. files missing from the disk, distinguishing those that are still on zotero.org and can be recovered;
6. identical PDFs attached to several items;
7. automatic tags and nearly identical tags;
8. citation keys;
9. file names;
10. structure of the collections;
11. syncing;
12. outline of the subjects, compared with the collections of the subjects in Zotero (skipped as long as the subjects are not in place).

The full report gives, for each point, the list of the items concerned and what the cleanup can do about them.

For point 5, the audit asks zotero.org, with your API key, which missing files are still stored there. This is the only time it connects, and it only reads. Without a connection, or with the `--offline` option, it only gives the number of missing files.

If point 11 reports **items with an invalid key**, stop there. They block Zotero's syncing, and no cleanup is possible before they are repaired. Open an [issue](https://github.com/deubelen/zot-clean/issues) to ask for help.

## 7. Work with the agent

Open the agent in the working folder, from the terminal:

```
cd ~/Zotero-work
claude        # for Claude Code, or else
codex         # for Codex
```

The agent finds its instructions in `AGENTS.md` and a guide for each step in `.agents/skills/`. Talk to it normally, in your own language. To begin:

> Where does my library stand?

It runs the audit, summarizes it starting with what matters most, and proposes an order of work. You remain in charge of every decision. The agent presents its proposals in bundles, with a recommendation, and waits for your agreement before any change.

For Claude Code, one precaution. If a `CLAUDE.md` file is in the working folder or in a folder above it, Claude Code reads it instead of `AGENTS.md`. `zc init` warns you in that case and tells you how to fix it.

## 8. The cleanup, step by step

The recommended order is the following. Each step can be interrupted and resumed later, the progress is kept in `suivi/`.

| Step | What it does | What you do |
|---|---|---|
| 2. Duplicates | Spots duplicate items and merges them the way Zotero does (notes, attachments, collections and "Related" links brought together). If the kept item carries a suffixed citation key ("dupont2002a") and a merged item the base key ("dupont2002"), the kept item takes the latter. Also handles PDFs that exist in several copies. | You confirm the safe groups in bulk and settle the doubtful cases (two editions of the same book, a translation and its original…). |
| 3. Metadata | Fixes DOIs, changes the type of wrongly typed items, fills empty fields from Crossref, OpenAlex, the BnF, the Sudoc and Open Library. Filling in never replaces a value that is already there. The corrections do change values, each one announced in the report of the plan. A DOI that exists nowhere is replaced by the right one when it is found with certainty. A change of type empties the fields that the new type does not accept, after copying their value into the Extra field. | You judge the uncertain cases, for example a DOI that seems to point to another publication. |
| 4. Outline of the subjects | Proposes, from your collections and your tags, an outline by disciplines and themes, written in `plan.md`. Nothing is changed in Zotero. | You discuss the outline with the agent until you validate it, then decide the fate of each former collection. |
| 5. Filing | Transforms your collections according to the validated outline, keeping those that become themes, then distributes the items, in several passes. | You approve the proposed distributions in bundles. |
| 6. Tags | Sorts your tags according to the method (statuses, concepts, marks), removes the keywords that publishers added automatically, brings the variants of one tag together and gives the tags of the method their color, each on a keyboard key. | You decide the fate of the tags that zc cannot settle alone (keep, turn into a concept, delete) and confirm the variants brought together. |
| 7. Citation keys | With Better BibTeX, separates duplicate keys (the oldest item keeps its key, the others get a suffix a, b…) and puts into the "Citation Key" field the keys that stayed in Extra. A unique key is never changed. Without Better BibTeX, only the separation of duplicates is done. | You fill in the missing keys in Zotero (right-click, Better BibTeX › Fill) and settle the rare cases where Extra and the field give two different keys. |
| 8. File names | Renames the main file of each item after the file-name template set in Zotero (by default "Author - Year - Title"). The new name goes through zotero.org, and each computer renames its files at its next sync. | After the trial, you run Zotero's sync and open the renamed files to check that they open under their new name. |

Step 1 consists of rereading `config.toml` if the default method does not suit you (see [the method](method.md)).

### How a step runs

Every step that changes Zotero follows the same course. The agent drives it, but it is good to know it.

1. **Spot and judge.** A command (`zc duplicates find`, for example) writes the cases in a file in `suivi/`. The agent presents them to you and notes your decisions in it.
2. **Back up.** Close Zotero, then the agent runs `zc backup`. Reopen Zotero afterwards. A backup less than 24 hours old is required before any bulk change. On macOS, it copies the whole Zotero folder in a few seconds, without using extra space as long as nothing changes. On Windows and Linux, it copies the database alone (items, notes, collections), which is enough since `zot-clean` never touches the content of the PDF files (step 8 only changes their name, which `zc undo` knows how to restore).
3. **Plan.** A command (`zc duplicates plan`) prepares the plan and its report in `plans/`. The agent summarizes it for you. You can read it yourself, it is a text file.
4. **Trial.** With your agreement, the agent runs `zc apply <plan> --trial`, which applies only the first five groups. Let Zotero sync (green arrow at the top right if nothing moves), then check these items in Zotero.
5. **Apply.** If the trial suits you, the agent runs `zc apply <plan> --all`. If the command is interrupted (a network cut, for example), just run it again, it picks up where it stopped.
6. **Check.** The agent runs the audit again and tells you what remains.

### Going back

Each application is recorded in `journal/`. To undo a step:

```
zc journal                   # list of the changes made
zc undo plans/<the plan>     # prepares the undo plan
```

The undo is itself a plan, to be tried then applied like the others. One limit only: Zotero empties its trash after 30 days (default setting). A merge whose absorbed item has left the trash can no longer be undone by `zc undo`. The backup is then the last resort.

## 9. Afterwards, sort the new references

Once the subjects are in place, new references arrive in the Inbox (or directly in a project, if that is the collection selected when you save with the Zotero connector). To sort them, tell the agent "sort the Inbox", as often as suits you.

The agent runs `zc inbox prepare`, which looks, for these references only, for duplicates, metadata corrections and the themes where other items by the same author or from the same journal are filed. It proposes a theme for each one, according to the definitions in `plan.md`. When none fits, it proposes the closest one or a new theme, and the reference stays in the Inbox until you have decided. A reference from a project stays there and also receives its theme. Once step 6 is done, the tags of the new references follow the rules you accepted (automatic tags removed, variants brought back to their form), and a new manual tag is only pointed out to you.

`zc inbox plan` gathers everything in a single plan, which the agent summarizes for you. A sorting plan that touches fewer than 50 items is applied at once, without a trial or a recent backup, since the journal and `zc undo` are enough to go back. You check the result afterwards. Beyond that, the usual course applies (trial, backup, application).

## 10. The regular checkup

Each audit keeps a record of what it found. The next one therefore opens on what has appeared and what has been settled since (new duplicates, missing metadata, missing files, references outside the subjects). A twelfth check compares `plan.md` with the collections of the subjects. Since the agent runs the audit at the start of each session, the checkup happens without you thinking about it.

After the cleanup, Zotero is the authority. You can create, rename, move or delete a theme directly in Zotero. The checkup notices it, and `zc subjects track` carries the change over into `plan.md` and into the follow-up files, after your agreement. The agent then proposes a definition for each new theme. A theme that goes beyond the threshold set in `config.toml` (`seuil_sous_theme`) is flagged. If you want to split it, the agent reads all its titles (`zc subjects titles`) and proposes subthemes, only if a clean split emerges.

One possible routine is to sort the Inbox every week and to ask the agent where the library stands once a month.

## Going further with other tools

`zot-clean` puts order in your library and keeps it there. It does not read your PDFs for you, summarize anything or suggest readings. Zotero extensions do that, right in the Zotero window, for example

- [Beaver](https://forums.zotero.org/discussion/126573/), which answers your questions about your library by citing passages from the PDFs, explains a passage in the reader and searches for articles beyond your library;
- [llm-for-zotero](https://github.com/yilewang/llm-for-zotero), which summarizes, compares and explains articles in the reader, with the model of your choice (free and open source);
- [Scite](https://scite.ai), which shows how an article is cited elsewhere, in support or in contrast.

They answer better on a library that has already been cleaned, without duplicates and with accurate metadata. Some of them can also add tags or file items, one at a time after your approval. For the whole library, the steps of `zot-clean` remain safer, since they go through a plan, a trial and a journal that allows undoing. What these extensions change in Zotero, the regular checkup sees as a change made by hand.

Like the agent, they send what they read (titles, abstracts, text of the PDFs) to their provider, and they ignore the items you keep out of sight in `config.toml`. Set them up accordingly.

## Keeping items out of sight

If some references must not be read by the agent (personal files, work under embargo), open `config.toml` with a text editor and fill in the `[confidentialite]` section (the name of the section stays in French, whatever the language of the library):

```toml
[confidentialite]
tags_exclus = ["_private"]
collections_exclues = ["Subjects/Personal"]
```

An item that carries one of these tags (upper or lower case), or that is filed in one of these collections or their subcollections, appears only by its key, with its attachments, notes and annotations, followed by "(confidential item)", in everything that `zc` writes (audit, follow-up, reports). It is never looked up by its title at the metadata services. It is still processed, its duplicates are merged and its DOI is checked. When a decision concerns it, the agent asks you to look at it yourself in Zotero. The tag can also be put on a single attachment or a single note. The plans (`plans/*.json`) and the journal (`journal/`), on the other hand, keep the full values, which `zc` needs in order to apply and undo, and the agent is instructed never to open them.

## Files and backups

Zotero can sync your PDFs through zotero.org, through a WebDAV server, or not at all. `zc` reads this in Zotero's settings and takes it into account at point 5 of the audit. With WebDAV, a file missing from the disk usually comes back when you open the attachment in Zotero, which downloads it again from the server. Whatever your choice, set Zotero to download files "at sync time" on the computer where you run `zc`. `zc` compares and renames the files that are on the disk, and a complete copy is also the best of backups.

`zc backup` puts its copies in `Zotero-sauvegardes` (the name of this folder stays French), next to the Zotero folder, and keeps only two. These copies double the Zotero folder, which your backup software already keeps. On a Mac, `zc` excludes them from Time Machine. Everywhere, it drops into this folder a `CACHEDIR.TAG` file, which Borg (option `exclude_caches`), restic and tar (option `--exclude-caches`) know how to recognize. With other software, exclude this folder by hand.

Do back up your working folder, however. Its journals make it possible to undo a change, and `plan.md` as well as `suivi/` keep your classification decisions.

## Updating zot-clean

```
uv tool install --reinstall git+https://github.com/deubelen/zot-clean
zc --version
cd ~/Zotero-work
zc init --update
```

The first command fetches the latest version from GitHub (`uv tool upgrade zot-clean` does not see it, since the tool comes from a Git repository and not from a package index), and `zc --version` shows the installed number. `zc init --update` replaces the agent's instructions and the step guides with those of the new version. It touches neither `config.toml`, nor `.env`, nor your decisions, reports and journals. Since version 0.4, the commands and the step guides have English names (the command for duplicates is now called `zc duplicates`, and its guide `duplicates`…). The update removes the old step guides, and `zc` answers an old command name by giving the new one. The names of the classification, the reports and the messages stay in the language of the library.

## When zc refuses

`zc` refuses rather than take a risk, and always says why. The most common refusals are the following.

| Message | What to do |
|---|---|
| Zotero is open | Close Zotero, run `zc backup` again, then reopen Zotero. |
| No backup less than 24 hours old | Close Zotero and run `zc backup`. |
| No trial of this plan has succeeded | First run `zc apply <plan> --trial` and check the result in Zotero. |
| Items not yet synced | Leave Zotero open and start its sync (green arrow), then run the command again. When it is only Zotero that has not yet received the latest changes from the server, `zc` does not wait, it reads them on zotero.org. Sync anyway before checking anything in Zotero. |
| Key refused by Zotero | Create a new key on zotero.org (step 4), then run `zc init ~/Zotero-work` again. It rechecks the saved key and, if Zotero refuses it, asks for the new one without changing anything else. |
| The API key belongs to zotero.org account no. …, while Zotero, on this computer, syncs account … | The key was created on a different account from the one on this computer (personal instead of institutional, for example). Sign in on zotero.org with the account named in the message, create a key there (step 4), then run `zc init ~/Zotero-work` again, which replaces the old one. In the meantime, `zc audit --offline` does the audit without using the key. |
| Zotero has never synced this library | In Zotero, open Settings › Sync, sign in to your zotero.org account (create it if needed), sync with the green arrow and wait for the end, then run `zc init ~/Zotero-work` again to save the key. |
| Item(s) with an invalid key | Do not force anything. Open an [issue](https://github.com/deubelen/zot-clean/issues). |

For any other problem, or a question, open an [issue](https://github.com/deubelen/zot-clean/issues) with the message that was displayed, without your API key and without the titles of your references if they are confidential.

## Glossary

- **Agent.** A conversational program that works in a folder on your computer and can run commands, with your agreement (Claude Code, Codex).
- **API, API key.** The entrance of the Zotero server for programs. The key is the pass that lets `zot-clean` change your library.
- **Key (of an item).** An eight-character identifier that Zotero gives to each item, for example `ABCD2345`.
- **Working folder.** Folder created by `zc init`, where `zot-clean` keeps its configuration, its reports, its plans and its journal.
- **Subjects.** The part of the library that classifies all the references by discipline and by theme. See [the method](method.md).
- **Plan.** List of the changes that a step proposes, prepared without touching anything, along with a readable report.
- **Sync.** Exchange between the Zotero on your computer and the zotero.org server. `zot-clean` writes to the server, and your Zotero receives the changes when it syncs.
- **Terminal.** Window where you type commands (Terminal on macOS, PowerShell on Windows).
