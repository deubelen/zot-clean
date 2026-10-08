#!/bin/sh
# Regenerates tests/donnees/schema_zotero.sql from a copy of zotero.sqlite
# (after a Zotero update that changes the schema). Copies no personal data,
# only the tables, the indexes and the reference tables.
# Usage: sh tests/extract_schema.sh <copy of zotero.sqlite>
set -e
BASE="$1"
SORTIE="$(dirname "$0")/donnees/schema_zotero.sql"
VERSION=$(sqlite3 "$BASE" "select version from version where schema = 'userdata'")
{
  echo "-- Schéma de zotero.sqlite (userdata $VERSION) : tables et index, sans déclencheurs ni données personnelles."
  echo "-- Seules les tables de référence (types, champs, rôles et leurs correspondances) sont remplies. Régénérer avec tests/extract_schema.sh."
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
