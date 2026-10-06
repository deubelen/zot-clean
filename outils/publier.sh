#!/bin/sh
# Publie l'état de `main` dans le dépôt public github.com/deubelen/zot-clean, en un commit par version, sans
# l'historique de travail, qui reste dans le dépôt privé (zot-clean-atelier). À lancer depuis la racine du dépôt,
# arbre propre. Le dépôt public n'est jamais modifié à la main : chaque publication remplace tout son contenu.
set -eu

PUBLIC=https://github.com/deubelen/zot-clean.git

if [ -n "$(git status --porcelain)" ]; then
    echo "Arbre de travail modifié : commiter d'abord." >&2
    exit 1
fi
if [ "$(git rev-parse --abbrev-ref HEAD)" != main ]; then
    echo "Publier depuis main." >&2
    exit 1
fi

version=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
source=$(git rev-parse --short HEAD)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

if git ls-remote --exit-code "$PUBLIC" main >/dev/null 2>&1; then
    git clone -q --depth 1 "$PUBLIC" "$tmp/public"
else
    git init -q -b main "$tmp/public"
    git -C "$tmp/public" remote add origin "$PUBLIC"
fi
# Contenu remplacé en entier par celui de main (fichiers suivis seulement).
find "$tmp/public" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD | tar -x -C "$tmp/public"

cd "$tmp/public"
git add -A
if git diff --cached --quiet; then
    echo "Rien de nouveau à publier."
    exit 0
fi
git commit -q -m "zot-clean $version (atelier $source)"
git push -q origin main
echo "Publié : zot-clean $version, depuis $source."
