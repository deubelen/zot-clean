"""Command registry (D213, D219, phase 0 of the switch to English).

Every command, subcommand, option and value of version 0.3.2, with its English
name in version 0.4.0. It is used to refuse an old name while giving its
equivalent (D213) and to check the commands quoted in documents, reports and
help. A value given in English on the command line is translated into the word
that the files of the working folder store, which does not change (D209).
"""

import unicodedata

# Old command -> (new, old subcommand -> new).
COMMANDS: dict[str, tuple[str, dict[str, str]]] = {
    'init': ('init', {}),
    'audit': ('audit', {}),
    'sauvegarder': ('backup', {}),
    'appliquer': ('apply', {}),
    'annuler': ('undo', {}),
    'doublons': ('duplicates', {'chercher': 'find', 'planifier': 'plan', 'accepter': 'accept', 'refuser': 'reject'}),
    'pieces': ('attachments', {'chercher': 'find', 'planifier': 'plan', 'accepter': 'accept', 'refuser': 'reject'}),
    'metadonnees': ('metadata', {'identifiants': 'identifiers', 'types': 'types', 'completer': 'complete',
                                 'accepter': 'accept', 'refuser': 'reject'}),
    'inbox': ('inbox', {'preparer': 'prepare', 'planifier': 'plan'}),
    'fonds': ('subjects', {'inventaire': 'inventory', 'valider': 'validate', 'suivre': 'track', 'titres': 'titles',
                           'a-ranger': 'pending', 'planifier': 'plan'}),
    'tags': ('tags', {'inventaire': 'inventory', 'planifier': 'plan', 'accepter': 'accept', 'refuser': 'reject',
                      'ajouter': 'add'}),
    'cles': ('citation-keys', {'planifier': 'plan', 'decider': 'decide'}),
    'noms': ('filenames', {'planifier': 'plan'}),
    'journal': ('journal', {}),
    'voir': ('show', {}),
}

# Old option -> new. An option keeps the same English name in every command that has it.
OPTIONS: dict[str, str] = {
    '--dossier': '--workspace',
    '--dossier-zotero': '--zotero-dir',
    '--maj': '--update',
    '--sans-empreintes': '--no-hashes',
    '--hors-ligne': '--offline',
    '--essai': '--trial',
    '--tout': '--all',
    '--surs': '--certain',
    '--sauf': '--except',
    '--conserver': '--keep',
    '--raison': '--reason',
    '--corbeille': '--trash',
    '--rattacher': '--move',
    '--rafraichir': '--refresh',
    '--evidents': '--obvious',
    '--enregistrer': '--save',
    '--resume': '--abstract',
    '--examinees': '--reviewed',
    '--laisser': '--leave-out',
    '--racines': '--roots',
    '--variantes': '--variants',
    '--regle-automatiques': '--automatic-rule',
    '--regle-importes': '--imported-rule',
    '--sort': '--action',
    '--cible': '--target',
    '--utilisateur': '--user',
    '--tag': '--tag',
    '--version': '--version',
}

# Values: « command subcommand » and option, or argument for a value written FICHE=value, -> old value
# -> new. The word stored in the files stays the old one (D209).
TAG_ACTIONS = {'supprimer': 'delete', 'garder': 'keep', 'concept': 'concept', 'état': 'status',
                  'fusionner': 'merge'}
VALUES: dict[tuple[str, str], dict[str, str]] = {
    ('tags accepter', '--sort'): TAG_ACTIONS,
    ('tags ajouter', '--sort'): TAG_ACTIONS,
    ('cles decider', 'decisions'): {'garder': 'keep', 'écarter': 'skip', 'natif': 'native', 'extra': 'extra'},
}

# Appeared with version 0.4.0 or later, with no old name.
NEW_COMMANDS = ('config show', 'init --library-language', 'subjects accept', 'subjects reject', 'subjects --add',
                'subjects --from', 'subjects --note')


def _form(word: str) -> str:
    return unicodedata.normalize('NFKD', word).encode('ascii', 'ignore').decode().strip().lower()


def _value(table: dict[str, str], word: str) -> str:
    """Translated value, in the form 0.3.2 accepted (without accents, in capitals…), otherwise as is."""
    return next((n for a, n in table.items() if _form(a) == _form(word)), word)


def translate(arguments: list[str]) -> list[str]:
    """0.3.2 command line (without `zc`) written with the English names. What is not an old name
    (paths, keys, tag names) is left as is."""
    if not arguments or arguments[0] not in COMMANDS:
        return list(arguments)
    command = arguments[0]
    new, under = COMMANDS[command]
    res, rest = [new], arguments[1:]
    path = command
    if under and rest and rest[0] in under:
        path += ' ' + rest[0]
        res.append(under[rest[0]])
        rest = rest[1:]
    option = ''
    for word in rest:
        if word.startswith('--'):
            name, equals, value = word.partition('=')
            table = VALUES.get((path, name))
            res.append(OPTIONS.get(name, name) + (equals + (_value(table, value) if table else value)))
            option = '' if equals else name
            continue
        if table := VALUES.get((path, option)):
            res.append(_value(table, word))
        elif (table := VALUES.get((path, 'decisions'))) and '=' in word:
            item, _, decision = word.partition('=')
            res.append(f'{item}={_value(table, decision)}')
        else:
            res.append(word)
        option = ''
    return res
