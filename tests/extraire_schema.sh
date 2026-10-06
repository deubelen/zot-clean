#!/bin/sh
# Régénère tests/donnees/schema_zotero.sql à partir d'une copie de zotero.sqlite
# (après une mise à jour de Zotero qui change le schéma). Ne copie aucune donnée
# personnelle, seulement les tables, les index et les tables de référence.
# Usage : sh tests/extraire_schema.sh <copie de zotero.sqlite>
set -e
BASE="$1"
SORTIE="$(dirname "$0")/donnees/schema_zotero.sql"
VERSION=$(sqlite3 "$BASE" "select version from version where schema = 'userdata'")
{
  echo "-- Schéma de zotero.sqlite (userdata $VERSION) : tables et index, sans déclencheurs ni données personnelles."
  echo "-- Seules les tables de référence (types, champs, rôles et leurs correspondances) sont remplies. Régénérer avec tests/extraire_schema.sh."
  sqlite3 "$BASE" "select sql || ';' from sqlite_master where type in ('table', 'index') and sql is not null
                   and name not like 'sqlite_%' and name not like 'fulltext%' order by type desc, name"
  sqlite3 "$BASE" ".mode insert itemTypes" "select * from itemTypes"
  sqlite3 "$BASE" ".mode insert fields" "select * from fields"
  sqlite3 "$BASE" ".mode insert creatorTypes" "select * from creatorTypes"
  for t in itemTypeFields baseFieldMappings itemTypeCreatorTypes; do
    sqlite3 "$BASE" ".mode insert $t" "select * from $t"
  done
  echo "INSERT INTO version VALUES('userdata',$VERSION);"
} > "$SORTIE"
echo "$SORTIE (userdata $VERSION)"
