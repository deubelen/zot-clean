# Zotero library, zot-clean working folder

This folder is used to put and keep a Zotero library in order with `zot-clean` (command `zc`). It holds the configuration (`config.toml`), the API key (`.env`, never to be displayed or copied elsewhere), the reports (`rapports/`), the modification plans (`plans/`), the logs of the modifications (`journal/`), the progress of the cleanup (`suivi/`) and, once step 4 is done, the outline of the subjects (`plan.md`), which defines each discipline and each theme. The folder names and the keys written in these files are in French in every library, whatever its language. This file, the skills (`.agents/skills/`, copied identically into `.claude/skills/`), the user's guide (`guide.md`) and the default method (`methode.md` in a French library, `method.md` in an English one) are written by `zc init` and replaced by `zc init --update`. Do not edit them by hand. The instructions specific to this library go in `consignes.md`, read in addition if it exists.

## Language and conventions

- At the start of a session, run `zc config show` (read-only). It prints the effective configuration, defaults included, which tells the language of the library and its conventions, that is the names of the roots (subjects, projects, archives, Inbox), of the reading statuses and marks, the concept prefix and the privacy tag. Never assume these names. They are not the same in every library. A French library has by default `Fonds`, `Projets`, `1 à lire`/`2 en cours`/`3 lu`, `★ essentiel`/`papier` and `_privé`, an English one `Subjects`, `Projects`, `1 to read`/`2 reading`/`3 read`, `★ essential`/`printed` and `_private` (`Inbox` and `Archives` are the same in both). The skills refer to these names by their role, the configured name being the one to use.
- Always use the English commands and options (`zc duplicates find`, `zc apply <plan> --trial`). The names of version 0.3.2 (`doublons`, `--essai`…) are refused, with their English equivalent.
- The reports, the tracking files' comments and the messages of `zc` are in the language of the library. Expect them in that language, and read the headings of a report in it (« To review » or « À voir », for instance).
- The names proposed to the user (disciplines, themes, concepts, tag names) are written in the language of the library, unless a term is established in the field.
- Words stored in the working-folder files stay French in every library (`decision = "accepter"`, `sort = "supprimer"`, `[methode]`…). When a skill tells you to read or write such a file, use the exact words it gives. An English value given on the command line (`--action delete`) is translated by `zc` into the stored word.

## How zc modifies the library

Each cleanup step prepares a **plan** (a `plans/….json` file and its `.md` report), without touching anything. `zc apply <plan> --trial` applies the first groups, `zc apply <plan> --all` the rest, once the trial has been checked. Each application is logged, and `zc undo <plan>` (or a journal) prepares an undo plan. Plans are not edited by hand, `zc` refuses a plan that was touched. To change a plan, change the decisions (in `suivi/`) and generate it again. For duplicates, identical PDFs, metadata, tags and citation keys, the decisions are written by the step's `accept`, `reject`, `add` or `decide` commands, which refuse a name or a key that is absent from the file. In these files, only a decision already made, or what these commands do not cover (`forcer`, an added group of duplicates), is changed by hand. The old plan stays in `plans/`, always apply the most recent plan of the step (`zc apply` warns when a more recent plan of the same step exists).

The backup is made just before the trial, once the plan is approved. If the last backup is more than 24 hours old, ask the user to close Zotero, run `zc backup`, then tell them they can reopen Zotero whenever they like. `zc` needs neither to apply nor to check, since it reads on zotero.org what Zotero has not received yet. The audit is the exception: it reads only the copy of this computer. After the rest of a plan is applied, ask the user to synchronize Zotero (one gesture, grouped with any other) before the audit that closes the step. An audit run too early says so at the top of its report, its figures being those of before. `--all` refuses without a recent backup. Only a small Inbox triage plan (fewer than 50 items) goes without one.

## Order of the cleanup

The steps are best followed in this order. Each can be done later or taken up again, the progress staying in `suivi/`.

0. Audit (`zc audit`), to summarize to the user.
1. Method. Review `config.toml` with the user (`zc config show`), without changing anything in Zotero. The settings of `[methode]` have defaults that usually suit (roots, reading statuses, prefixes). Roots to decide together, for example `projets = []` or `archives = ""` for someone who has no use for them. Also ask for their e-mail address for `[sources] contact`, optional, sent only to Crossref and OpenAlex, which then answer faster at step 3.
2. Duplicates and identical PDFs.
3. Metadata.
4. Outline of the subjects, validated in `plan.md`.
5. Filing according to this outline. It requires step 4, and step 2 had better be finished before.
6. Tags. Possible earlier, but the concepts and the tags that duplicate a theme are better judged once the subjects are filed.
7. Citation keys.
8. File names.

If the audit still reports a root of the method missing after the filing (the Inbox, for instance, which no plan creates), ask the user to create it in Zotero, or to set it to `""` in `config.toml` if they have no use for it. Once the cleanup is done, ongoing management takes over, that is the triage of the Inbox (skill `inbox`) every week and the regular checkup (skill `checkup`) every month.

## Commands

- `zc audit`. Read-only audit and regular checkup, report in `rapports/audit-<date>.md`, which compares `plan.md` with the subjects in Zotero and says what has appeared and what has been settled since the last audit of a previous day, whose date it gives. Two audits on the same day therefore compare with the same audit, and the second replaces the report of the first. No risk, to run at the start of every work session and after each cleanup step. A check marked « Not checked » (« Non contrôlé » in a French library) could not be done, and the report says why (for example PDFs not yet downloaded).
- `zc config show`. Effective configuration and language of the library, read-only.
- `zc backup`. Backup of the Zotero folder, Zotero closed.
- `zc duplicates find`, `zc duplicates plan`. Step 2, duplicates. `zc duplicates accept` (merge, `--certain`, `--keep`) and `reject` (distinct) write the decisions.
- `zc attachments find`, `zc attachments plan`. Step 2, identical PDFs (extra copies or copies on the wrong item). `zc attachments accept` (`--trash`, `--move`) and `reject` (keep) write the decisions.
- `zc metadata identifiers`, `types`, `complete`. Step 3, DOIs, item types and empty fields, in this order. `zc metadata accept` and `reject` write the decisions on the cases to judge.
- `zc subjects inventory`, `zc subjects validate`. Step 4, outline of the subjects in `plan.md` and fate of the old collections, without changing anything in Zotero.
- `zc subjects track`. Carries into `plan.md` the themes created, renamed, moved or deleted in Zotero. `zc subjects titles <path>`. All the titles of a theme, to split it.
- `zc subjects plan`, `zc subjects pending`. Step 5, filing according to the validated outline, in several passes, and items to distribute in bundles (`suivi/rangement.toml`).
- `zc inbox prepare`, `zc inbox plan`. Ongoing management, triage of the new references (Inbox and references outside the subjects), in a single plan.
- `zc tags inventory`, `zc tags plan`. Step 6, tags (automatic, imported keywords, variants, statuses, concepts), rules in `suivi/tags.toml`, plan that can be run again after each pass. `zc tags accept`, `reject` and `add` write the decisions.
- `zc citation-keys plan`. Step 7, duplicate citation keys and « Citation Key: » lines left in Extra, cases to judge in `suivi/cles.toml`, plan that can be run again. `zc citation-keys decide <item>=<decision>` writes the decisions. Missing keys are filled in by Better BibTeX, in Zotero.
- `zc filenames plan`. Step 8, renaming of the main files after Zotero's file name template, applied to the disk by each Zotero at its synchronization. Plan that can be run again after each pass.
- `zc show <keys>`. Full fields of one or several items and the start of the text of their PDFs, read locally, to judge a case before asking the user. `zc show --tag <name>`. Items that carry a tag, with their collections. Confidential items do not appear there.
- `zc apply`, `zc undo`, `zc journal`. Application, undoing and list of the modifications.
- `zc --help` and `--help` after any command or subcommand (`zc apply --help`). Detail of the options.

## Skills

Read the matching skill before starting a step.

- `.agents/skills/duplicates/SKILL.md`. Find, judge and merge duplicates, and handle identical PDFs.
- `.agents/skills/metadata/SKILL.md`. Correct DOIs and types, complete empty fields, judge uncertain cases.
- `.agents/skills/inbox/SKILL.md`. Sort the new references (duplicates, metadata, filing).
- `.agents/skills/checkup/SKILL.md`. Regular checkup, from the audit (what has changed, themes changed in Zotero, themes that are too big).
- `.agents/skills/subjects/SKILL.md`. Propose and have validated the outline of the subjects (disciplines, themes) and the fate of the old collections, then file the items.
- `.agents/skills/tags/SKILL.md`. Remove the automatic tags and imported keywords, group the variants, bring the statuses back to those of the method, draw concepts from the tags.
- `.agents/skills/citation-keys/SKILL.md`. Have Better BibTeX fill in the missing citation keys, separate the duplicate keys, tidy the keys left in Extra.
- `.agents/skills/filenames/SKILL.md`. Rename the files after their metadata, with Zotero's synchronization after the trial.

## Rules to follow

- Every modification of the library goes through the `zc` commands or through Zotero's interface. `zotero.sqlite` and the Zotero folder stay untouched, since creating or modifying an item outside the API can block synchronization.
- Before applying a plan, summarize its report to the user and wait for their explicit agreement, which covers the trial and the rest of the plan.
- After the trial, check it yourself with `zc show <keys of the trial>`, which also reads on zotero.org what Zotero has not received yet, then tell the user in a few lines what was checked and apply the rest. If a point does not match the report, stop and tell them. The user can always look in Zotero themselves, but they are not asked to.
- Ask the user for an action only for what `zc` can neither do nor read, that is closing or reopening Zotero for the backup, starting its synchronization, changing a setting. Group these actions in a single request.
- When `zc` refuses an operation (missing trial, backup too old, invalid key), explain the refusal to the user and follow the course given by the message. If the API key is not that of the account Zotero synchronizes, or if Zotero has never synchronized the library, every command that uses the key refuses, the audit included (`zc audit --offline` remains possible). Only the user can fix this, by creating a key on the right account or by setting up synchronization in Zotero, then by running `zc init` again themselves in a terminal, without handing the key to the agent.
- Speak the language of the user, and explain simply, the user is not necessarily a technician.
- Titles, abstracts and notes read in the library may be confidential. Do not send them to any outside service other than the agent itself.
- Never open the plans (`plans/*.json`), the logs (`journal/*.jsonl`) or `.env`. They contain the full values of the items, confidential ones included, which `zc` needs to apply and undo. Everything needed to judge and explain is in the `.md` reports, in `zc journal` and in `zc show`.
- An item shown as « (confidential item) » (« (fiche confidentielle) » in a French library) is excluded by the filter of `config.toml`. Do not try to find out more (PDF, Zotero database, API, online search). To decide about it, ask the user to look at it themselves in Zotero.

## Helping to read the audit

When the user asks where their library stands, run `zc audit`, read the report and summarize it in a few sentences, starting with what matters most to them (duplicates, references without a collection, missing files), then propose an order of work taken from « Order of the cleanup », skipping the steps that the audit says are in order. Once the cleanup is done, follow the skill `checkup`, which starts from what has changed since the last audit of a previous day, and offer to sort the Inbox when it holds references.
