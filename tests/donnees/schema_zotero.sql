-- Schéma de zotero.sqlite (Zotero 10, userdata 129) : tables et index, sans déclencheurs ni données personnelles.
-- Seules les tables de référence (types, champs, rôles et leurs correspondances) sont remplies. Régénérer avec tests/extraire_schema.sh.
CREATE TABLE baseFieldMappings (    itemTypeID INT,    baseFieldID INT,    fieldID INT,    PRIMARY KEY (itemTypeID, baseFieldID, fieldID),    FOREIGN KEY (itemTypeID) REFERENCES itemTypes(itemTypeID),    FOREIGN KEY (baseFieldID) REFERENCES fields(fieldID),    FOREIGN KEY (fieldID) REFERENCES fields(fieldID));
CREATE TABLE baseFieldMappingsCombined (    itemTypeID INT,    baseFieldID INT,    fieldID INT,    PRIMARY KEY (itemTypeID, baseFieldID, fieldID));
CREATE TABLE charsets (    charsetID INTEGER PRIMARY KEY,    charset TEXT UNIQUE);
CREATE TABLE collectionItems (
    collectionID INT NOT NULL,
    itemID INT NOT NULL,
    orderIndex INT NOT NULL DEFAULT 0,
    PRIMARY KEY (collectionID, itemID),
    FOREIGN KEY (collectionID) REFERENCES collections(collectionID) ON DELETE CASCADE,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE
);
CREATE TABLE collectionRelations (
    collectionID INT NOT NULL,
    predicateID INT NOT NULL,
    object TEXT NOT NULL,
    PRIMARY KEY (collectionID, predicateID, object),
    FOREIGN KEY (collectionID) REFERENCES collections(collectionID) ON DELETE CASCADE,
    FOREIGN KEY (predicateID) REFERENCES relationPredicates(predicateID) ON DELETE CASCADE
);
CREATE TABLE collections (
    collectionID INTEGER PRIMARY KEY,
    collectionName TEXT NOT NULL,
    parentCollectionID INT DEFAULT NULL,
    clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0, clientVersion INT NOT NULL DEFAULT 0,
    UNIQUE (libraryID, key),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE,
    FOREIGN KEY (parentCollectionID) REFERENCES collections(collectionID) ON DELETE CASCADE
);
CREATE TABLE creatorTypes (    creatorTypeID INTEGER PRIMARY KEY,    creatorType TEXT);
CREATE TABLE creators (
    creatorID INTEGER PRIMARY KEY,
    firstName TEXT,
    lastName TEXT,
    fieldMode INT, firstNameNormalized TEXT, lastNameNormalized TEXT,
    UNIQUE (lastName, firstName, fieldMode)
);
CREATE TABLE customBaseFieldMappings (
    customItemTypeID INT,
    baseFieldID INT,
    customFieldID INT,
    PRIMARY KEY (customItemTypeID, baseFieldID, customFieldID),
    FOREIGN KEY (customItemTypeID) REFERENCES customItemTypes(customItemTypeID),
    FOREIGN KEY (baseFieldID) REFERENCES fields(fieldID),
    FOREIGN KEY (customFieldID) REFERENCES customFields(customFieldID)
);
CREATE TABLE customFields (
    customFieldID INTEGER PRIMARY KEY,
    fieldName TEXT,
    label TEXT
);
CREATE TABLE customItemTypeFields (
    customItemTypeID INT NOT NULL,
    fieldID INT,
    customFieldID INT,
    hide INT NOT NULL,
    orderIndex INT NOT NULL,
    PRIMARY KEY (customItemTypeID, orderIndex),
    FOREIGN KEY (customItemTypeID) REFERENCES customItemTypes(customItemTypeID),
    FOREIGN KEY (fieldID) REFERENCES fields(fieldID),
    FOREIGN KEY (customFieldID) REFERENCES customFields(customFieldID)
);
CREATE TABLE customItemTypes (
    customItemTypeID INTEGER PRIMARY KEY,
    typeName TEXT,
    label TEXT,
    display INT DEFAULT 1, -- 0 == hide, 1 == display, 2 == primary
    icon TEXT
);
CREATE TABLE dbDebug1 (
    a INTEGER PRIMARY KEY
);
CREATE TABLE deletedCollections (
    collectionID INTEGER PRIMARY KEY,
    dateDeleted DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (collectionID) REFERENCES collections(collectionID) ON DELETE CASCADE
);
CREATE TABLE deletedItems (
    itemID INTEGER PRIMARY KEY,
    dateDeleted DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE
);
CREATE TABLE deletedSearches (
    savedSearchID INTEGER PRIMARY KEY,
    dateDeleted DEFAULT CURRENT_TIMESTAMP NOT NULL,
    FOREIGN KEY (savedSearchID) REFERENCES savedSearches(savedSearchID) ON DELETE CASCADE
);
CREATE TABLE feedItems (
    itemID INTEGER PRIMARY KEY,
    guid TEXT NOT NULL UNIQUE,
    readTime TIMESTAMP,
    translatedTime TIMESTAMP,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE
);
CREATE TABLE feeds (
    libraryID INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    lastUpdate TIMESTAMP,
    lastCheck TIMESTAMP,
    lastCheckError TEXT,
    cleanupReadAfter INT,
    cleanupUnreadAfter INT,
    refreshInterval INT,
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE fieldFormats (    fieldFormatID INTEGER PRIMARY KEY,    regex TEXT,    isInteger INT);
CREATE TABLE fields (    fieldID INTEGER PRIMARY KEY,    fieldName TEXT,    fieldFormatID INT,    FOREIGN KEY (fieldFormatID) REFERENCES fieldFormats(fieldFormatID));
CREATE TABLE fieldsCombined (    fieldID INT NOT NULL,    fieldName TEXT NOT NULL,    label TEXT,    fieldFormatID INT,    custom INT NOT NULL,    PRIMARY KEY (fieldID));
CREATE TABLE fileTypeMimeTypes (    fileTypeID INT,    mimeType TEXT,    PRIMARY KEY (fileTypeID, mimeType),    FOREIGN KEY (fileTypeID) REFERENCES fileTypes(fileTypeID));
CREATE TABLE fileTypes (    fileTypeID INTEGER PRIMARY KEY,    fileType TEXT UNIQUE);
CREATE TABLE groupItems (
    itemID INTEGER PRIMARY KEY,
    createdByUserID INT,
    lastModifiedByUserID INT,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (createdByUserID) REFERENCES users(userID) ON DELETE SET NULL,
    FOREIGN KEY (lastModifiedByUserID) REFERENCES users(userID) ON DELETE SET NULL
);
CREATE TABLE groups (
    groupID INTEGER PRIMARY KEY,
    libraryID INT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    version INT NOT NULL,
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE "itemAnnotations" (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT NOT NULL,
    type INTEGER NOT NULL,
    authorName TEXT,
    text TEXT,
    comment TEXT,
    color TEXT,
    pageLabel TEXT,
    sortIndex TEXT NOT NULL,
    position TEXT NOT NULL,
    isExternal INT NOT NULL, textNormalized TEXT, commentNormalized TEXT,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (parentItemID) REFERENCES itemAttachments(itemID)
);
CREATE TABLE itemAttachments (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT,
    linkMode INT,
    contentType TEXT,
    charsetID INT,
    path TEXT,
    syncState INT DEFAULT 0,
    storageModTime INT,
    storageHash TEXT, lastProcessedModificationTime INT, lastRead INT,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (parentItemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (charsetID) REFERENCES charsets(charsetID) ON DELETE SET NULL
);
CREATE TABLE itemCreators (
    itemID INT NOT NULL,
    creatorID INT NOT NULL,
    creatorTypeID INT NOT NULL DEFAULT 1,
    orderIndex INT NOT NULL DEFAULT 0,
    PRIMARY KEY (itemID, creatorID, creatorTypeID, orderIndex),
    UNIQUE (itemID, orderIndex),
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (creatorID) REFERENCES creators(creatorID) ON DELETE CASCADE,
    FOREIGN KEY (creatorTypeID) REFERENCES creatorTypes(creatorTypeID)
);
CREATE TABLE itemData (
    itemID INT,
    fieldID INT,
    valueID,
    PRIMARY KEY (itemID, fieldID),
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (fieldID) REFERENCES fieldsCombined(fieldID),
    FOREIGN KEY (valueID) REFERENCES itemDataValues(valueID)
);
CREATE TABLE itemDataValues (
    valueID INTEGER PRIMARY KEY,
    value UNIQUE
, valueNormalized TEXT);
CREATE TABLE itemNotes (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT,
    note TEXT,
    title TEXT,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (parentItemID) REFERENCES items(itemID) ON DELETE CASCADE
);
CREATE TABLE itemRelations (
    itemID INT NOT NULL,
    predicateID INT NOT NULL,
    object TEXT NOT NULL,
    PRIMARY KEY (itemID, predicateID, object),
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (predicateID) REFERENCES relationPredicates(predicateID) ON DELETE CASCADE
);
CREATE TABLE itemTags (
    itemID INT NOT NULL,
    tagID INT NOT NULL,
    type INT NOT NULL,
    PRIMARY KEY (itemID, tagID),
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (tagID) REFERENCES tags(tagID) ON DELETE CASCADE
);
CREATE TABLE itemTypeCreatorTypes (    itemTypeID INT,    creatorTypeID INT,    primaryField INT,    PRIMARY KEY (itemTypeID, creatorTypeID),    FOREIGN KEY (itemTypeID) REFERENCES itemTypes(itemTypeID),    FOREIGN KEY (creatorTypeID) REFERENCES creatorTypes(creatorTypeID));
CREATE TABLE itemTypeFields (    itemTypeID INT,    fieldID INT,    hide INT,    orderIndex INT,    PRIMARY KEY (itemTypeID, orderIndex),    UNIQUE (itemTypeID, fieldID),    FOREIGN KEY (itemTypeID) REFERENCES itemTypes(itemTypeID),    FOREIGN KEY (fieldID) REFERENCES fields(fieldID));
CREATE TABLE itemTypeFieldsCombined (    itemTypeID INT NOT NULL,    fieldID INT NOT NULL,    hide INT,    orderIndex INT NOT NULL,    PRIMARY KEY (itemTypeID, orderIndex),    UNIQUE (itemTypeID, fieldID));
CREATE TABLE itemTypes (    itemTypeID INTEGER PRIMARY KEY,    typeName TEXT,    templateItemTypeID INT,    display INT DEFAULT 1 );
CREATE TABLE itemTypesCombined (    itemTypeID INT NOT NULL,    typeName TEXT NOT NULL,    display INT DEFAULT 1 NOT NULL,    custom INT NOT NULL,    PRIMARY KEY (itemTypeID));
CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    itemTypeID INT NOT NULL,
    dateAdded TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0, clientVersion INT NOT NULL DEFAULT 0,
    UNIQUE (libraryID, key),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE libraries (
    libraryID INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    editable INT NOT NULL,
    filesEditable INT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    storageVersion INT NOT NULL DEFAULT 0,
    lastSync INT NOT NULL DEFAULT 0
, archived INT NOT NULL DEFAULT 0, isAdmin INT NOT NULL DEFAULT 0, clientVersion INT NOT NULL DEFAULT 0);
CREATE TABLE proxies (
    proxyID INTEGER PRIMARY KEY,
    multiHost INT,
    autoAssociate INT,
    scheme TEXT
);
CREATE TABLE proxyHosts (
    hostID INTEGER PRIMARY KEY,
    proxyID INTEGER,
    hostname TEXT,
    FOREIGN KEY (proxyID) REFERENCES proxies(proxyID)
);
CREATE TABLE publicationsItems (
    itemID INTEGER PRIMARY KEY
);
CREATE TABLE relationPredicates (
    predicateID INTEGER PRIMARY KEY,
    predicate TEXT UNIQUE
);
CREATE TABLE retractedItems (
	itemID INTEGER PRIMARY KEY,
	data TEXT, flag INT DEFAULT 0,
	FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE
);
CREATE TABLE savedSearchConditions (
    savedSearchID INT NOT NULL,
    searchConditionID INT NOT NULL,
    condition TEXT NOT NULL,
    operator TEXT,
    value TEXT,
    PRIMARY KEY (savedSearchID, searchConditionID),
    FOREIGN KEY (savedSearchID) REFERENCES savedSearches(savedSearchID) ON DELETE CASCADE
);
CREATE TABLE savedSearches (
    savedSearchID INTEGER PRIMARY KEY,
    savedSearchName TEXT NOT NULL,
    clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0, clientVersion INT NOT NULL DEFAULT 0,
    UNIQUE (libraryID, key),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE settings (
    setting TEXT,
    key TEXT,
    value,
    PRIMARY KEY (setting, key)
);
CREATE TABLE storageDeleteLog (
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    dateDeleted TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (libraryID, key),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE syncCache (
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    syncObjectTypeID INT NOT NULL,
    version INT NOT NULL,
    data TEXT,
    PRIMARY KEY (libraryID, key, syncObjectTypeID, version),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE,
    FOREIGN KEY (syncObjectTypeID) REFERENCES syncObjectTypes(syncObjectTypeID)
);
CREATE TABLE syncDeleteLog (
    syncObjectTypeID INT NOT NULL,
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    dateDeleted TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (syncObjectTypeID, libraryID, key),
    FOREIGN KEY (syncObjectTypeID) REFERENCES syncObjectTypes(syncObjectTypeID),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE syncObjectTypes (    syncObjectTypeID INTEGER PRIMARY KEY,    name TEXT);
CREATE TABLE syncQueue (
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    syncObjectTypeID INT NOT NULL,
    lastCheck TIMESTAMP,
    tries INT,
    PRIMARY KEY (libraryID, key, syncObjectTypeID),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE,
    FOREIGN KEY (syncObjectTypeID) REFERENCES syncObjectTypes(syncObjectTypeID) ON DELETE CASCADE
);
CREATE TABLE syncedSettings (
    setting TEXT NOT NULL,
    libraryID INT NOT NULL,
    value NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0,
    PRIMARY KEY (setting, libraryID),
    FOREIGN KEY (libraryID) REFERENCES libraries(libraryID) ON DELETE CASCADE
);
CREATE TABLE tags (
    tagID INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
, nameNormalized TEXT);
CREATE TABLE translatorCache (
    fileName TEXT PRIMARY KEY,
    metadataJSON TEXT,
    lastModifiedTime INT
);
CREATE TABLE users (
    userID INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE version (
    schema TEXT PRIMARY KEY,
    version INT NOT NULL
);
CREATE TABLE zoteroDummyTable (id INTEGER PRIMARY KEY);
CREATE INDEX baseFieldMappingsCombined_baseFieldID ON baseFieldMappingsCombined(baseFieldID);
CREATE INDEX baseFieldMappingsCombined_fieldID ON baseFieldMappingsCombined(fieldID);
CREATE INDEX baseFieldMappings_baseFieldID ON baseFieldMappings(baseFieldID);
CREATE INDEX baseFieldMappings_fieldID ON baseFieldMappings(fieldID);
CREATE INDEX charsets_charset ON charsets(charset);
CREATE INDEX collectionItems_itemID ON collectionItems(itemID);
CREATE INDEX collectionRelations_object ON collectionRelations(object);
CREATE INDEX collectionRelations_predicateID ON collectionRelations(predicateID);
CREATE INDEX collections_synced ON collections(synced);
CREATE INDEX customBaseFieldMappings_baseFieldID ON customBaseFieldMappings(baseFieldID);
CREATE INDEX customBaseFieldMappings_customFieldID ON customBaseFieldMappings(customFieldID);
CREATE INDEX customItemTypeFields_customFieldID ON customItemTypeFields(customFieldID);
CREATE INDEX customItemTypeFields_fieldID ON customItemTypeFields(fieldID);
CREATE INDEX deletedCollections_dateDeleted ON deletedCollections(dateDeleted);
CREATE INDEX deletedItems_dateDeleted ON deletedItems(dateDeleted);
CREATE INDEX deletedSearches_dateDeleted ON deletedSearches(dateDeleted);
CREATE INDEX fileTypeMimeTypes_mimeType ON fileTypeMimeTypes(mimeType);
CREATE INDEX fileTypes_fileType ON fileTypes(fileType);
CREATE INDEX itemAnnotations_parentItemID ON itemAnnotations(parentItemID);
CREATE INDEX itemAttachments_charsetID ON itemAttachments(charsetID);
CREATE INDEX itemAttachments_contentType ON itemAttachments(contentType);
CREATE INDEX itemAttachments_lastProcessedModificationTime ON itemAttachments(lastProcessedModificationTime);
CREATE INDEX itemAttachments_lastRead ON itemAttachments(lastRead);
CREATE INDEX itemAttachments_parentItemID ON itemAttachments(parentItemID);
CREATE INDEX itemAttachments_syncState ON itemAttachments(syncState);
CREATE INDEX itemCreators_creatorTypeID ON itemCreators(creatorTypeID);
CREATE INDEX itemData_fieldID ON itemData(fieldID);
CREATE INDEX itemData_valueID ON itemData(valueID);
CREATE INDEX itemNotes_parentItemID ON itemNotes(parentItemID);
CREATE INDEX itemRelations_object ON itemRelations(object);
CREATE INDEX itemRelations_predicateID ON itemRelations(predicateID);
CREATE INDEX itemTags_tagID ON itemTags(tagID);
CREATE INDEX itemTypeCreatorTypes_creatorTypeID ON itemTypeCreatorTypes(creatorTypeID);
CREATE INDEX itemTypeFieldsCombined_fieldID ON itemTypeFieldsCombined(fieldID);
CREATE INDEX itemTypeFields_fieldID ON itemTypeFields(fieldID);
CREATE INDEX items_synced ON items(synced);
CREATE INDEX proxyHosts_proxyID ON proxyHosts(proxyID);
CREATE INDEX savedSearches_synced ON savedSearches(synced);
CREATE INDEX schema ON version(schema);
CREATE INDEX syncObjectTypes_name ON syncObjectTypes(name);
INSERT INTO itemTypes VALUES(1,'note',NULL,0);
INSERT INTO itemTypes VALUES(2,'book',NULL,2);
INSERT INTO itemTypes VALUES(3,'bookSection',2,2);
INSERT INTO itemTypes VALUES(4,'journalArticle',NULL,2);
INSERT INTO itemTypes VALUES(5,'magazineArticle',NULL,2);
INSERT INTO itemTypes VALUES(6,'newspaperArticle',NULL,2);
INSERT INTO itemTypes VALUES(7,'thesis',NULL,1);
INSERT INTO itemTypes VALUES(8,'letter',NULL,1);
INSERT INTO itemTypes VALUES(9,'manuscript',NULL,1);
INSERT INTO itemTypes VALUES(10,'interview',NULL,1);
INSERT INTO itemTypes VALUES(11,'film',NULL,1);
INSERT INTO itemTypes VALUES(12,'artwork',NULL,1);
INSERT INTO itemTypes VALUES(13,'webpage',NULL,0);
INSERT INTO itemTypes VALUES(14,'attachment',NULL,0);
INSERT INTO itemTypes VALUES(15,'report',NULL,1);
INSERT INTO itemTypes VALUES(16,'bill',NULL,1);
INSERT INTO itemTypes VALUES(17,'case',NULL,1);
INSERT INTO itemTypes VALUES(18,'hearing',NULL,1);
INSERT INTO itemTypes VALUES(19,'patent',NULL,1);
INSERT INTO itemTypes VALUES(20,'statute',NULL,1);
INSERT INTO itemTypes VALUES(21,'email',NULL,1);
INSERT INTO itemTypes VALUES(22,'map',NULL,1);
INSERT INTO itemTypes VALUES(23,'blogPost',NULL,1);
INSERT INTO itemTypes VALUES(24,'instantMessage',NULL,1);
INSERT INTO itemTypes VALUES(25,'forumPost',NULL,1);
INSERT INTO itemTypes VALUES(26,'audioRecording',NULL,1);
INSERT INTO itemTypes VALUES(27,'presentation',NULL,1);
INSERT INTO itemTypes VALUES(28,'videoRecording',NULL,1);
INSERT INTO itemTypes VALUES(29,'tvBroadcast',NULL,1);
INSERT INTO itemTypes VALUES(30,'radioBroadcast',NULL,1);
INSERT INTO itemTypes VALUES(31,'podcast',NULL,1);
INSERT INTO itemTypes VALUES(32,'computerProgram',NULL,1);
INSERT INTO itemTypes VALUES(33,'conferencePaper',NULL,1);
INSERT INTO itemTypes VALUES(34,'document',NULL,2);
INSERT INTO itemTypes VALUES(35,'encyclopediaArticle',NULL,1);
INSERT INTO itemTypes VALUES(36,'dictionaryEntry',NULL,1);
INSERT INTO itemTypes VALUES(37,'annotation',NULL,1);
INSERT INTO itemTypes VALUES(38,'preprint',NULL,1);
INSERT INTO itemTypes VALUES(39,'dataset',NULL,1);
INSERT INTO itemTypes VALUES(40,'standard',NULL,1);
INSERT INTO fields VALUES(1,'url',NULL);
INSERT INTO fields VALUES(2,'rights',NULL);
INSERT INTO fields VALUES(3,'series',NULL);
INSERT INTO fields VALUES(4,'volume',NULL);
INSERT INTO fields VALUES(5,'issue',NULL);
INSERT INTO fields VALUES(6,'edition',NULL);
INSERT INTO fields VALUES(7,'place',NULL);
INSERT INTO fields VALUES(8,'publisher',NULL);
INSERT INTO fields VALUES(10,'pages',NULL);
INSERT INTO fields VALUES(11,'ISBN',NULL);
INSERT INTO fields VALUES(12,'publicationTitle',NULL);
INSERT INTO fields VALUES(13,'ISSN',NULL);
INSERT INTO fields VALUES(14,'date',NULL);
INSERT INTO fields VALUES(15,'section',NULL);
INSERT INTO fields VALUES(18,'callNumber',NULL);
INSERT INTO fields VALUES(19,'archiveLocation',NULL);
INSERT INTO fields VALUES(21,'distributor',NULL);
INSERT INTO fields VALUES(22,'extra',NULL);
INSERT INTO fields VALUES(25,'journalAbbreviation',NULL);
INSERT INTO fields VALUES(26,'DOI',NULL);
INSERT INTO fields VALUES(27,'accessDate',NULL);
INSERT INTO fields VALUES(28,'seriesTitle',NULL);
INSERT INTO fields VALUES(29,'seriesText',NULL);
INSERT INTO fields VALUES(30,'seriesNumber',NULL);
INSERT INTO fields VALUES(31,'institution',NULL);
INSERT INTO fields VALUES(32,'reportType',NULL);
INSERT INTO fields VALUES(36,'code',NULL);
INSERT INTO fields VALUES(40,'session',NULL);
INSERT INTO fields VALUES(41,'legislativeBody',NULL);
INSERT INTO fields VALUES(42,'history',NULL);
INSERT INTO fields VALUES(43,'reporter',NULL);
INSERT INTO fields VALUES(44,'court',NULL);
INSERT INTO fields VALUES(45,'numberOfVolumes',NULL);
INSERT INTO fields VALUES(46,'committee',NULL);
INSERT INTO fields VALUES(48,'assignee',NULL);
INSERT INTO fields VALUES(50,'patentNumber',NULL);
INSERT INTO fields VALUES(51,'priorityNumbers',NULL);
INSERT INTO fields VALUES(52,'issueDate',NULL);
INSERT INTO fields VALUES(53,'references',NULL);
INSERT INTO fields VALUES(54,'legalStatus',NULL);
INSERT INTO fields VALUES(55,'codeNumber',NULL);
INSERT INTO fields VALUES(59,'artworkMedium',NULL);
INSERT INTO fields VALUES(60,'number',NULL);
INSERT INTO fields VALUES(61,'artworkSize',NULL);
INSERT INTO fields VALUES(62,'libraryCatalog',NULL);
INSERT INTO fields VALUES(63,'videoRecordingFormat',NULL);
INSERT INTO fields VALUES(64,'interviewMedium',NULL);
INSERT INTO fields VALUES(65,'letterType',NULL);
INSERT INTO fields VALUES(66,'manuscriptType',NULL);
INSERT INTO fields VALUES(67,'mapType',NULL);
INSERT INTO fields VALUES(68,'scale',NULL);
INSERT INTO fields VALUES(69,'thesisType',NULL);
INSERT INTO fields VALUES(70,'websiteType',NULL);
INSERT INTO fields VALUES(71,'audioRecordingFormat',NULL);
INSERT INTO fields VALUES(72,'label',NULL);
INSERT INTO fields VALUES(74,'presentationType',NULL);
INSERT INTO fields VALUES(75,'meetingName',NULL);
INSERT INTO fields VALUES(76,'studio',NULL);
INSERT INTO fields VALUES(77,'runningTime',NULL);
INSERT INTO fields VALUES(78,'network',NULL);
INSERT INTO fields VALUES(79,'postType',NULL);
INSERT INTO fields VALUES(80,'audioFileType',NULL);
INSERT INTO fields VALUES(81,'versionNumber',NULL);
INSERT INTO fields VALUES(82,'system',NULL);
INSERT INTO fields VALUES(83,'company',NULL);
INSERT INTO fields VALUES(84,'conferenceName',NULL);
INSERT INTO fields VALUES(85,'encyclopediaTitle',NULL);
INSERT INTO fields VALUES(86,'dictionaryTitle',NULL);
INSERT INTO fields VALUES(87,'language',NULL);
INSERT INTO fields VALUES(88,'programmingLanguage',NULL);
INSERT INTO fields VALUES(89,'university',NULL);
INSERT INTO fields VALUES(90,'abstractNote',NULL);
INSERT INTO fields VALUES(91,'websiteTitle',NULL);
INSERT INTO fields VALUES(92,'reportNumber',NULL);
INSERT INTO fields VALUES(93,'billNumber',NULL);
INSERT INTO fields VALUES(94,'codeVolume',NULL);
INSERT INTO fields VALUES(95,'codePages',NULL);
INSERT INTO fields VALUES(96,'dateDecided',NULL);
INSERT INTO fields VALUES(97,'reporterVolume',NULL);
INSERT INTO fields VALUES(98,'firstPage',NULL);
INSERT INTO fields VALUES(99,'documentNumber',NULL);
INSERT INTO fields VALUES(100,'dateEnacted',NULL);
INSERT INTO fields VALUES(101,'publicLawNumber',NULL);
INSERT INTO fields VALUES(102,'country',NULL);
INSERT INTO fields VALUES(103,'applicationNumber',NULL);
INSERT INTO fields VALUES(104,'forumTitle',NULL);
INSERT INTO fields VALUES(105,'episodeNumber',NULL);
INSERT INTO fields VALUES(107,'blogTitle',NULL);
INSERT INTO fields VALUES(108,'type',NULL);
INSERT INTO fields VALUES(109,'medium',NULL);
INSERT INTO fields VALUES(110,'title',NULL);
INSERT INTO fields VALUES(111,'caseName',NULL);
INSERT INTO fields VALUES(112,'nameOfAct',NULL);
INSERT INTO fields VALUES(113,'subject',NULL);
INSERT INTO fields VALUES(114,'proceedingsTitle',NULL);
INSERT INTO fields VALUES(115,'bookTitle',NULL);
INSERT INTO fields VALUES(116,'shortTitle',NULL);
INSERT INTO fields VALUES(117,'docketNumber',NULL);
INSERT INTO fields VALUES(118,'numPages',NULL);
INSERT INTO fields VALUES(119,'programTitle',NULL);
INSERT INTO fields VALUES(120,'issuingAuthority',NULL);
INSERT INTO fields VALUES(121,'filingDate',NULL);
INSERT INTO fields VALUES(122,'genre',NULL);
INSERT INTO fields VALUES(123,'archive',NULL);
INSERT INTO fields VALUES(124,'repository',NULL);
INSERT INTO fields VALUES(125,'archiveID',NULL);
INSERT INTO fields VALUES(126,'citationKey',NULL);
INSERT INTO fields VALUES(127,'authority',NULL);
INSERT INTO fields VALUES(128,'identifier',NULL);
INSERT INTO fields VALUES(129,'repositoryLocation',NULL);
INSERT INTO fields VALUES(130,'format',NULL);
INSERT INTO fields VALUES(131,'status',NULL);
INSERT INTO fields VALUES(132,'organization',NULL);
INSERT INTO fields VALUES(133,'eventPlace',NULL);
INSERT INTO fields VALUES(134,'originalDate',NULL);
INSERT INTO fields VALUES(135,'originalPublisher',NULL);
INSERT INTO fields VALUES(136,'originalPlace',NULL);
INSERT INTO fields VALUES(137,'partNumber',NULL);
INSERT INTO fields VALUES(138,'partTitle',NULL);
INSERT INTO fields VALUES(139,'PMID',NULL);
INSERT INTO fields VALUES(140,'PMCID',NULL);
INSERT INTO fields VALUES(141,'priorityDate',NULL);
INSERT INTO fields VALUES(142,'sessionTitle',NULL);
INSERT INTO creatorTypes VALUES(1,'author');
INSERT INTO creatorTypes VALUES(2,'contributor');
INSERT INTO creatorTypes VALUES(3,'editor');
INSERT INTO creatorTypes VALUES(4,'translator');
INSERT INTO creatorTypes VALUES(5,'seriesEditor');
INSERT INTO creatorTypes VALUES(6,'interviewee');
INSERT INTO creatorTypes VALUES(7,'interviewer');
INSERT INTO creatorTypes VALUES(8,'director');
INSERT INTO creatorTypes VALUES(9,'scriptwriter');
INSERT INTO creatorTypes VALUES(10,'producer');
INSERT INTO creatorTypes VALUES(11,'castMember');
INSERT INTO creatorTypes VALUES(12,'sponsor');
INSERT INTO creatorTypes VALUES(13,'counsel');
INSERT INTO creatorTypes VALUES(14,'inventor');
INSERT INTO creatorTypes VALUES(15,'attorneyAgent');
INSERT INTO creatorTypes VALUES(16,'recipient');
INSERT INTO creatorTypes VALUES(17,'performer');
INSERT INTO creatorTypes VALUES(18,'composer');
INSERT INTO creatorTypes VALUES(19,'wordsBy');
INSERT INTO creatorTypes VALUES(20,'cartographer');
INSERT INTO creatorTypes VALUES(21,'programmer');
INSERT INTO creatorTypes VALUES(22,'artist');
INSERT INTO creatorTypes VALUES(23,'commenter');
INSERT INTO creatorTypes VALUES(24,'presenter');
INSERT INTO creatorTypes VALUES(25,'guest');
INSERT INTO creatorTypes VALUES(26,'podcaster');
INSERT INTO creatorTypes VALUES(27,'reviewedAuthor');
INSERT INTO creatorTypes VALUES(28,'cosponsor');
INSERT INTO creatorTypes VALUES(29,'bookAuthor');
INSERT INTO creatorTypes VALUES(30,'originalCreator');
INSERT INTO creatorTypes VALUES(31,'host');
INSERT INTO creatorTypes VALUES(32,'narrator');
INSERT INTO creatorTypes VALUES(33,'executiveProducer');
INSERT INTO creatorTypes VALUES(34,'seriesCreator');
INSERT INTO creatorTypes VALUES(35,'chair');
INSERT INTO creatorTypes VALUES(36,'organizer');
INSERT INTO creatorTypes VALUES(37,'creator');
INSERT INTO version VALUES('userdata',129);
INSERT INTO itemTypeFields VALUES(12,110,0,0);
INSERT INTO itemTypeFields VALUES(12,90,0,1);
INSERT INTO itemTypeFields VALUES(12,59,0,2);
INSERT INTO itemTypeFields VALUES(12,61,0,3);
INSERT INTO itemTypeFields VALUES(12,14,0,4);
INSERT INTO itemTypeFields VALUES(12,133,0,5);
INSERT INTO itemTypeFields VALUES(12,26,0,6);
INSERT INTO itemTypeFields VALUES(12,126,0,7);
INSERT INTO itemTypeFields VALUES(12,1,0,8);
INSERT INTO itemTypeFields VALUES(12,27,0,9);
INSERT INTO itemTypeFields VALUES(12,123,0,10);
INSERT INTO itemTypeFields VALUES(12,19,0,11);
INSERT INTO itemTypeFields VALUES(12,116,0,12);
INSERT INTO itemTypeFields VALUES(12,87,0,13);
INSERT INTO itemTypeFields VALUES(12,62,0,14);
INSERT INTO itemTypeFields VALUES(12,18,0,15);
INSERT INTO itemTypeFields VALUES(12,2,0,16);
INSERT INTO itemTypeFields VALUES(12,22,0,17);
INSERT INTO itemTypeFields VALUES(14,110,0,0);
INSERT INTO itemTypeFields VALUES(14,27,0,1);
INSERT INTO itemTypeFields VALUES(14,1,0,2);
INSERT INTO itemTypeFields VALUES(26,110,0,0);
INSERT INTO itemTypeFields VALUES(26,90,0,1);
INSERT INTO itemTypeFields VALUES(26,71,0,2);
INSERT INTO itemTypeFields VALUES(26,28,0,3);
INSERT INTO itemTypeFields VALUES(26,4,0,4);
INSERT INTO itemTypeFields VALUES(26,45,0,5);
INSERT INTO itemTypeFields VALUES(26,72,0,6);
INSERT INTO itemTypeFields VALUES(26,7,0,7);
INSERT INTO itemTypeFields VALUES(26,14,0,8);
INSERT INTO itemTypeFields VALUES(26,77,0,9);
INSERT INTO itemTypeFields VALUES(26,11,0,10);
INSERT INTO itemTypeFields VALUES(26,26,0,11);
INSERT INTO itemTypeFields VALUES(26,126,0,12);
INSERT INTO itemTypeFields VALUES(26,1,0,13);
INSERT INTO itemTypeFields VALUES(26,27,0,14);
INSERT INTO itemTypeFields VALUES(26,123,0,15);
INSERT INTO itemTypeFields VALUES(26,19,0,16);
INSERT INTO itemTypeFields VALUES(26,116,0,17);
INSERT INTO itemTypeFields VALUES(26,87,0,18);
INSERT INTO itemTypeFields VALUES(26,62,0,19);
INSERT INTO itemTypeFields VALUES(26,18,0,20);
INSERT INTO itemTypeFields VALUES(26,2,0,21);
INSERT INTO itemTypeFields VALUES(26,22,0,22);
INSERT INTO itemTypeFields VALUES(16,110,0,0);
INSERT INTO itemTypeFields VALUES(16,90,0,1);
INSERT INTO itemTypeFields VALUES(16,93,0,2);
INSERT INTO itemTypeFields VALUES(16,36,0,3);
INSERT INTO itemTypeFields VALUES(16,94,0,4);
INSERT INTO itemTypeFields VALUES(16,15,0,5);
INSERT INTO itemTypeFields VALUES(16,95,0,6);
INSERT INTO itemTypeFields VALUES(16,41,0,7);
INSERT INTO itemTypeFields VALUES(16,40,0,8);
INSERT INTO itemTypeFields VALUES(16,42,0,9);
INSERT INTO itemTypeFields VALUES(16,14,0,10);
INSERT INTO itemTypeFields VALUES(16,26,0,11);
INSERT INTO itemTypeFields VALUES(16,126,0,12);
INSERT INTO itemTypeFields VALUES(16,1,0,13);
INSERT INTO itemTypeFields VALUES(16,27,0,14);
INSERT INTO itemTypeFields VALUES(16,116,0,15);
INSERT INTO itemTypeFields VALUES(16,87,0,16);
INSERT INTO itemTypeFields VALUES(16,2,0,17);
INSERT INTO itemTypeFields VALUES(16,22,0,18);
INSERT INTO itemTypeFields VALUES(23,110,0,0);
INSERT INTO itemTypeFields VALUES(23,90,0,1);
INSERT INTO itemTypeFields VALUES(23,107,0,2);
INSERT INTO itemTypeFields VALUES(23,70,0,3);
INSERT INTO itemTypeFields VALUES(23,14,0,4);
INSERT INTO itemTypeFields VALUES(23,26,0,5);
INSERT INTO itemTypeFields VALUES(23,126,0,6);
INSERT INTO itemTypeFields VALUES(23,1,0,7);
INSERT INTO itemTypeFields VALUES(23,27,0,8);
INSERT INTO itemTypeFields VALUES(23,13,0,9);
INSERT INTO itemTypeFields VALUES(23,116,0,10);
INSERT INTO itemTypeFields VALUES(23,87,0,11);
INSERT INTO itemTypeFields VALUES(23,2,0,12);
INSERT INTO itemTypeFields VALUES(23,22,0,13);
INSERT INTO itemTypeFields VALUES(2,110,0,0);
INSERT INTO itemTypeFields VALUES(2,90,0,1);
INSERT INTO itemTypeFields VALUES(2,3,0,2);
INSERT INTO itemTypeFields VALUES(2,30,0,3);
INSERT INTO itemTypeFields VALUES(2,4,0,4);
INSERT INTO itemTypeFields VALUES(2,45,0,5);
INSERT INTO itemTypeFields VALUES(2,6,0,6);
INSERT INTO itemTypeFields VALUES(2,14,0,7);
INSERT INTO itemTypeFields VALUES(2,8,0,8);
INSERT INTO itemTypeFields VALUES(2,7,0,9);
INSERT INTO itemTypeFields VALUES(2,134,0,10);
INSERT INTO itemTypeFields VALUES(2,135,0,11);
INSERT INTO itemTypeFields VALUES(2,136,0,12);
INSERT INTO itemTypeFields VALUES(2,130,0,13);
INSERT INTO itemTypeFields VALUES(2,118,0,14);
INSERT INTO itemTypeFields VALUES(2,11,0,15);
INSERT INTO itemTypeFields VALUES(2,26,0,16);
INSERT INTO itemTypeFields VALUES(2,126,0,17);
INSERT INTO itemTypeFields VALUES(2,1,0,18);
INSERT INTO itemTypeFields VALUES(2,27,0,19);
INSERT INTO itemTypeFields VALUES(2,13,0,20);
INSERT INTO itemTypeFields VALUES(2,123,0,21);
INSERT INTO itemTypeFields VALUES(2,19,0,22);
INSERT INTO itemTypeFields VALUES(2,116,0,23);
INSERT INTO itemTypeFields VALUES(2,87,0,24);
INSERT INTO itemTypeFields VALUES(2,62,0,25);
INSERT INTO itemTypeFields VALUES(2,18,0,26);
INSERT INTO itemTypeFields VALUES(2,2,0,27);
INSERT INTO itemTypeFields VALUES(2,22,0,28);
INSERT INTO itemTypeFields VALUES(3,110,0,0);
INSERT INTO itemTypeFields VALUES(3,90,0,1);
INSERT INTO itemTypeFields VALUES(3,115,0,2);
INSERT INTO itemTypeFields VALUES(3,3,0,3);
INSERT INTO itemTypeFields VALUES(3,30,0,4);
INSERT INTO itemTypeFields VALUES(3,4,0,5);
INSERT INTO itemTypeFields VALUES(3,45,0,6);
INSERT INTO itemTypeFields VALUES(3,6,0,7);
INSERT INTO itemTypeFields VALUES(3,14,0,8);
INSERT INTO itemTypeFields VALUES(3,8,0,9);
INSERT INTO itemTypeFields VALUES(3,7,0,10);
INSERT INTO itemTypeFields VALUES(3,134,0,11);
INSERT INTO itemTypeFields VALUES(3,135,0,12);
INSERT INTO itemTypeFields VALUES(3,136,0,13);
INSERT INTO itemTypeFields VALUES(3,130,0,14);
INSERT INTO itemTypeFields VALUES(3,10,0,15);
INSERT INTO itemTypeFields VALUES(3,11,0,16);
INSERT INTO itemTypeFields VALUES(3,26,0,17);
INSERT INTO itemTypeFields VALUES(3,126,0,18);
INSERT INTO itemTypeFields VALUES(3,1,0,19);
INSERT INTO itemTypeFields VALUES(3,27,0,20);
INSERT INTO itemTypeFields VALUES(3,13,0,21);
INSERT INTO itemTypeFields VALUES(3,123,0,22);
INSERT INTO itemTypeFields VALUES(3,19,0,23);
INSERT INTO itemTypeFields VALUES(3,116,0,24);
INSERT INTO itemTypeFields VALUES(3,87,0,25);
INSERT INTO itemTypeFields VALUES(3,62,0,26);
INSERT INTO itemTypeFields VALUES(3,18,0,27);
INSERT INTO itemTypeFields VALUES(3,2,0,28);
INSERT INTO itemTypeFields VALUES(3,22,0,29);
INSERT INTO itemTypeFields VALUES(17,111,0,0);
INSERT INTO itemTypeFields VALUES(17,90,0,1);
INSERT INTO itemTypeFields VALUES(17,44,0,2);
INSERT INTO itemTypeFields VALUES(17,96,0,3);
INSERT INTO itemTypeFields VALUES(17,117,0,4);
INSERT INTO itemTypeFields VALUES(17,43,0,5);
INSERT INTO itemTypeFields VALUES(17,97,0,6);
INSERT INTO itemTypeFields VALUES(17,98,0,7);
INSERT INTO itemTypeFields VALUES(17,42,0,8);
INSERT INTO itemTypeFields VALUES(17,26,0,9);
INSERT INTO itemTypeFields VALUES(17,126,0,10);
INSERT INTO itemTypeFields VALUES(17,1,0,11);
INSERT INTO itemTypeFields VALUES(17,27,0,12);
INSERT INTO itemTypeFields VALUES(17,116,0,13);
INSERT INTO itemTypeFields VALUES(17,87,0,14);
INSERT INTO itemTypeFields VALUES(17,2,0,15);
INSERT INTO itemTypeFields VALUES(17,22,0,16);
INSERT INTO itemTypeFields VALUES(32,110,0,0);
INSERT INTO itemTypeFields VALUES(32,90,0,1);
INSERT INTO itemTypeFields VALUES(32,28,0,2);
INSERT INTO itemTypeFields VALUES(32,81,0,3);
INSERT INTO itemTypeFields VALUES(32,14,0,4);
INSERT INTO itemTypeFields VALUES(32,82,0,5);
INSERT INTO itemTypeFields VALUES(32,83,0,6);
INSERT INTO itemTypeFields VALUES(32,7,0,7);
INSERT INTO itemTypeFields VALUES(32,88,0,8);
INSERT INTO itemTypeFields VALUES(32,2,0,9);
INSERT INTO itemTypeFields VALUES(32,126,0,10);
INSERT INTO itemTypeFields VALUES(32,1,0,11);
INSERT INTO itemTypeFields VALUES(32,27,0,12);
INSERT INTO itemTypeFields VALUES(32,26,0,13);
INSERT INTO itemTypeFields VALUES(32,11,0,14);
INSERT INTO itemTypeFields VALUES(32,123,0,15);
INSERT INTO itemTypeFields VALUES(32,19,0,16);
INSERT INTO itemTypeFields VALUES(32,62,0,17);
INSERT INTO itemTypeFields VALUES(32,18,0,18);
INSERT INTO itemTypeFields VALUES(32,116,0,19);
INSERT INTO itemTypeFields VALUES(32,22,0,20);
INSERT INTO itemTypeFields VALUES(33,110,0,0);
INSERT INTO itemTypeFields VALUES(33,90,0,1);
INSERT INTO itemTypeFields VALUES(33,114,0,2);
INSERT INTO itemTypeFields VALUES(33,84,0,3);
INSERT INTO itemTypeFields VALUES(33,8,0,4);
INSERT INTO itemTypeFields VALUES(33,7,0,5);
INSERT INTO itemTypeFields VALUES(33,14,0,6);
INSERT INTO itemTypeFields VALUES(33,133,0,7);
INSERT INTO itemTypeFields VALUES(33,4,0,8);
INSERT INTO itemTypeFields VALUES(33,5,0,9);
INSERT INTO itemTypeFields VALUES(33,45,0,10);
INSERT INTO itemTypeFields VALUES(33,10,0,11);
INSERT INTO itemTypeFields VALUES(33,3,0,12);
INSERT INTO itemTypeFields VALUES(33,30,0,13);
INSERT INTO itemTypeFields VALUES(33,26,0,14);
INSERT INTO itemTypeFields VALUES(33,11,0,15);
INSERT INTO itemTypeFields VALUES(33,126,0,16);
INSERT INTO itemTypeFields VALUES(33,1,0,17);
INSERT INTO itemTypeFields VALUES(33,27,0,18);
INSERT INTO itemTypeFields VALUES(33,13,0,19);
INSERT INTO itemTypeFields VALUES(33,123,0,20);
INSERT INTO itemTypeFields VALUES(33,19,0,21);
INSERT INTO itemTypeFields VALUES(33,116,0,22);
INSERT INTO itemTypeFields VALUES(33,87,0,23);
INSERT INTO itemTypeFields VALUES(33,62,0,24);
INSERT INTO itemTypeFields VALUES(33,18,0,25);
INSERT INTO itemTypeFields VALUES(33,2,0,26);
INSERT INTO itemTypeFields VALUES(33,22,0,27);
INSERT INTO itemTypeFields VALUES(39,110,0,0);
INSERT INTO itemTypeFields VALUES(39,90,0,1);
INSERT INTO itemTypeFields VALUES(39,128,0,2);
INSERT INTO itemTypeFields VALUES(39,108,0,3);
INSERT INTO itemTypeFields VALUES(39,81,0,4);
INSERT INTO itemTypeFields VALUES(39,14,0,5);
INSERT INTO itemTypeFields VALUES(39,124,0,6);
INSERT INTO itemTypeFields VALUES(39,129,0,7);
INSERT INTO itemTypeFields VALUES(39,130,0,8);
INSERT INTO itemTypeFields VALUES(39,26,0,9);
INSERT INTO itemTypeFields VALUES(39,126,0,10);
INSERT INTO itemTypeFields VALUES(39,1,0,11);
INSERT INTO itemTypeFields VALUES(39,27,0,12);
INSERT INTO itemTypeFields VALUES(39,123,0,13);
INSERT INTO itemTypeFields VALUES(39,19,0,14);
INSERT INTO itemTypeFields VALUES(39,116,0,15);
INSERT INTO itemTypeFields VALUES(39,87,0,16);
INSERT INTO itemTypeFields VALUES(39,62,0,17);
INSERT INTO itemTypeFields VALUES(39,18,0,18);
INSERT INTO itemTypeFields VALUES(39,2,0,19);
INSERT INTO itemTypeFields VALUES(39,22,0,20);
INSERT INTO itemTypeFields VALUES(36,110,0,0);
INSERT INTO itemTypeFields VALUES(36,90,0,1);
INSERT INTO itemTypeFields VALUES(36,86,0,2);
INSERT INTO itemTypeFields VALUES(36,3,0,3);
INSERT INTO itemTypeFields VALUES(36,30,0,4);
INSERT INTO itemTypeFields VALUES(36,4,0,5);
INSERT INTO itemTypeFields VALUES(36,45,0,6);
INSERT INTO itemTypeFields VALUES(36,6,0,7);
INSERT INTO itemTypeFields VALUES(36,14,0,8);
INSERT INTO itemTypeFields VALUES(36,8,0,9);
INSERT INTO itemTypeFields VALUES(36,7,0,10);
INSERT INTO itemTypeFields VALUES(36,10,0,11);
INSERT INTO itemTypeFields VALUES(36,11,0,12);
INSERT INTO itemTypeFields VALUES(36,26,0,13);
INSERT INTO itemTypeFields VALUES(36,126,0,14);
INSERT INTO itemTypeFields VALUES(36,1,0,15);
INSERT INTO itemTypeFields VALUES(36,27,0,16);
INSERT INTO itemTypeFields VALUES(36,123,0,17);
INSERT INTO itemTypeFields VALUES(36,19,0,18);
INSERT INTO itemTypeFields VALUES(36,116,0,19);
INSERT INTO itemTypeFields VALUES(36,87,0,20);
INSERT INTO itemTypeFields VALUES(36,62,0,21);
INSERT INTO itemTypeFields VALUES(36,18,0,22);
INSERT INTO itemTypeFields VALUES(36,2,0,23);
INSERT INTO itemTypeFields VALUES(36,22,0,24);
INSERT INTO itemTypeFields VALUES(34,110,0,0);
INSERT INTO itemTypeFields VALUES(34,90,0,1);
INSERT INTO itemTypeFields VALUES(34,108,0,2);
INSERT INTO itemTypeFields VALUES(34,14,0,3);
INSERT INTO itemTypeFields VALUES(34,8,0,4);
INSERT INTO itemTypeFields VALUES(34,7,0,5);
INSERT INTO itemTypeFields VALUES(34,26,0,6);
INSERT INTO itemTypeFields VALUES(34,126,0,7);
INSERT INTO itemTypeFields VALUES(34,1,0,8);
INSERT INTO itemTypeFields VALUES(34,27,0,9);
INSERT INTO itemTypeFields VALUES(34,123,0,10);
INSERT INTO itemTypeFields VALUES(34,19,0,11);
INSERT INTO itemTypeFields VALUES(34,116,0,12);
INSERT INTO itemTypeFields VALUES(34,87,0,13);
INSERT INTO itemTypeFields VALUES(34,62,0,14);
INSERT INTO itemTypeFields VALUES(34,18,0,15);
INSERT INTO itemTypeFields VALUES(34,2,0,16);
INSERT INTO itemTypeFields VALUES(34,22,0,17);
INSERT INTO itemTypeFields VALUES(21,113,0,0);
INSERT INTO itemTypeFields VALUES(21,90,0,1);
INSERT INTO itemTypeFields VALUES(21,14,0,2);
INSERT INTO itemTypeFields VALUES(21,26,0,3);
INSERT INTO itemTypeFields VALUES(21,126,0,4);
INSERT INTO itemTypeFields VALUES(21,1,0,5);
INSERT INTO itemTypeFields VALUES(21,27,0,6);
INSERT INTO itemTypeFields VALUES(21,116,0,7);
INSERT INTO itemTypeFields VALUES(21,87,0,8);
INSERT INTO itemTypeFields VALUES(21,2,0,9);
INSERT INTO itemTypeFields VALUES(21,22,0,10);
INSERT INTO itemTypeFields VALUES(35,110,0,0);
INSERT INTO itemTypeFields VALUES(35,90,0,1);
INSERT INTO itemTypeFields VALUES(35,85,0,2);
INSERT INTO itemTypeFields VALUES(35,3,0,3);
INSERT INTO itemTypeFields VALUES(35,30,0,4);
INSERT INTO itemTypeFields VALUES(35,4,0,5);
INSERT INTO itemTypeFields VALUES(35,45,0,6);
INSERT INTO itemTypeFields VALUES(35,6,0,7);
INSERT INTO itemTypeFields VALUES(35,14,0,8);
INSERT INTO itemTypeFields VALUES(35,8,0,9);
INSERT INTO itemTypeFields VALUES(35,7,0,10);
INSERT INTO itemTypeFields VALUES(35,10,0,11);
INSERT INTO itemTypeFields VALUES(35,11,0,12);
INSERT INTO itemTypeFields VALUES(35,26,0,13);
INSERT INTO itemTypeFields VALUES(35,126,0,14);
INSERT INTO itemTypeFields VALUES(35,1,0,15);
INSERT INTO itemTypeFields VALUES(35,27,0,16);
INSERT INTO itemTypeFields VALUES(35,123,0,17);
INSERT INTO itemTypeFields VALUES(35,19,0,18);
INSERT INTO itemTypeFields VALUES(35,116,0,19);
INSERT INTO itemTypeFields VALUES(35,87,0,20);
INSERT INTO itemTypeFields VALUES(35,62,0,21);
INSERT INTO itemTypeFields VALUES(35,18,0,22);
INSERT INTO itemTypeFields VALUES(35,2,0,23);
INSERT INTO itemTypeFields VALUES(35,22,0,24);
INSERT INTO itemTypeFields VALUES(11,110,0,0);
INSERT INTO itemTypeFields VALUES(11,90,0,1);
INSERT INTO itemTypeFields VALUES(11,21,0,2);
INSERT INTO itemTypeFields VALUES(11,7,0,3);
INSERT INTO itemTypeFields VALUES(11,14,0,4);
INSERT INTO itemTypeFields VALUES(11,122,0,5);
INSERT INTO itemTypeFields VALUES(11,63,0,6);
INSERT INTO itemTypeFields VALUES(11,77,0,7);
INSERT INTO itemTypeFields VALUES(11,26,0,8);
INSERT INTO itemTypeFields VALUES(11,126,0,9);
INSERT INTO itemTypeFields VALUES(11,1,0,10);
INSERT INTO itemTypeFields VALUES(11,27,0,11);
INSERT INTO itemTypeFields VALUES(11,123,0,12);
INSERT INTO itemTypeFields VALUES(11,19,0,13);
INSERT INTO itemTypeFields VALUES(11,116,0,14);
INSERT INTO itemTypeFields VALUES(11,87,0,15);
INSERT INTO itemTypeFields VALUES(11,62,0,16);
INSERT INTO itemTypeFields VALUES(11,18,0,17);
INSERT INTO itemTypeFields VALUES(11,2,0,18);
INSERT INTO itemTypeFields VALUES(11,22,0,19);
INSERT INTO itemTypeFields VALUES(25,110,0,0);
INSERT INTO itemTypeFields VALUES(25,90,0,1);
INSERT INTO itemTypeFields VALUES(25,104,0,2);
INSERT INTO itemTypeFields VALUES(25,79,0,3);
INSERT INTO itemTypeFields VALUES(25,14,0,4);
INSERT INTO itemTypeFields VALUES(25,26,0,5);
INSERT INTO itemTypeFields VALUES(25,126,0,6);
INSERT INTO itemTypeFields VALUES(25,1,0,7);
INSERT INTO itemTypeFields VALUES(25,27,0,8);
INSERT INTO itemTypeFields VALUES(25,116,0,9);
INSERT INTO itemTypeFields VALUES(25,87,0,10);
INSERT INTO itemTypeFields VALUES(25,2,0,11);
INSERT INTO itemTypeFields VALUES(25,22,0,12);
INSERT INTO itemTypeFields VALUES(18,110,0,0);
INSERT INTO itemTypeFields VALUES(18,90,0,1);
INSERT INTO itemTypeFields VALUES(18,46,0,2);
INSERT INTO itemTypeFields VALUES(18,8,0,3);
INSERT INTO itemTypeFields VALUES(18,45,0,4);
INSERT INTO itemTypeFields VALUES(18,99,0,5);
INSERT INTO itemTypeFields VALUES(18,10,0,6);
INSERT INTO itemTypeFields VALUES(18,41,0,7);
INSERT INTO itemTypeFields VALUES(18,40,0,8);
INSERT INTO itemTypeFields VALUES(18,42,0,9);
INSERT INTO itemTypeFields VALUES(18,14,0,10);
INSERT INTO itemTypeFields VALUES(18,7,0,11);
INSERT INTO itemTypeFields VALUES(18,26,0,12);
INSERT INTO itemTypeFields VALUES(18,126,0,13);
INSERT INTO itemTypeFields VALUES(18,1,0,14);
INSERT INTO itemTypeFields VALUES(18,27,0,15);
INSERT INTO itemTypeFields VALUES(18,116,0,16);
INSERT INTO itemTypeFields VALUES(18,87,0,17);
INSERT INTO itemTypeFields VALUES(18,2,0,18);
INSERT INTO itemTypeFields VALUES(18,22,0,19);
INSERT INTO itemTypeFields VALUES(24,110,0,0);
INSERT INTO itemTypeFields VALUES(24,90,0,1);
INSERT INTO itemTypeFields VALUES(24,14,0,2);
INSERT INTO itemTypeFields VALUES(24,26,0,3);
INSERT INTO itemTypeFields VALUES(24,126,0,4);
INSERT INTO itemTypeFields VALUES(24,1,0,5);
INSERT INTO itemTypeFields VALUES(24,27,0,6);
INSERT INTO itemTypeFields VALUES(24,116,0,7);
INSERT INTO itemTypeFields VALUES(24,87,0,8);
INSERT INTO itemTypeFields VALUES(24,2,0,9);
INSERT INTO itemTypeFields VALUES(24,22,0,10);
INSERT INTO itemTypeFields VALUES(10,110,0,0);
INSERT INTO itemTypeFields VALUES(10,90,0,1);
INSERT INTO itemTypeFields VALUES(10,64,0,2);
INSERT INTO itemTypeFields VALUES(10,14,0,3);
INSERT INTO itemTypeFields VALUES(10,8,0,4);
INSERT INTO itemTypeFields VALUES(10,7,0,5);
INSERT INTO itemTypeFields VALUES(10,26,0,6);
INSERT INTO itemTypeFields VALUES(10,126,0,7);
INSERT INTO itemTypeFields VALUES(10,1,0,8);
INSERT INTO itemTypeFields VALUES(10,27,0,9);
INSERT INTO itemTypeFields VALUES(10,123,0,10);
INSERT INTO itemTypeFields VALUES(10,19,0,11);
INSERT INTO itemTypeFields VALUES(10,116,0,12);
INSERT INTO itemTypeFields VALUES(10,87,0,13);
INSERT INTO itemTypeFields VALUES(10,62,0,14);
INSERT INTO itemTypeFields VALUES(10,18,0,15);
INSERT INTO itemTypeFields VALUES(10,2,0,16);
INSERT INTO itemTypeFields VALUES(10,22,0,17);
INSERT INTO itemTypeFields VALUES(4,110,0,0);
INSERT INTO itemTypeFields VALUES(4,90,0,1);
INSERT INTO itemTypeFields VALUES(4,12,0,2);
INSERT INTO itemTypeFields VALUES(4,8,0,3);
INSERT INTO itemTypeFields VALUES(4,7,0,4);
INSERT INTO itemTypeFields VALUES(4,14,0,5);
INSERT INTO itemTypeFields VALUES(4,4,0,6);
INSERT INTO itemTypeFields VALUES(4,5,0,7);
INSERT INTO itemTypeFields VALUES(4,15,0,8);
INSERT INTO itemTypeFields VALUES(4,137,0,9);
INSERT INTO itemTypeFields VALUES(4,138,0,10);
INSERT INTO itemTypeFields VALUES(4,10,0,11);
INSERT INTO itemTypeFields VALUES(4,3,0,12);
INSERT INTO itemTypeFields VALUES(4,28,0,13);
INSERT INTO itemTypeFields VALUES(4,29,0,14);
INSERT INTO itemTypeFields VALUES(4,25,0,15);
INSERT INTO itemTypeFields VALUES(4,26,0,16);
INSERT INTO itemTypeFields VALUES(4,126,0,17);
INSERT INTO itemTypeFields VALUES(4,1,0,18);
INSERT INTO itemTypeFields VALUES(4,27,0,19);
INSERT INTO itemTypeFields VALUES(4,139,0,20);
INSERT INTO itemTypeFields VALUES(4,140,0,21);
INSERT INTO itemTypeFields VALUES(4,13,0,22);
INSERT INTO itemTypeFields VALUES(4,123,0,23);
INSERT INTO itemTypeFields VALUES(4,19,0,24);
INSERT INTO itemTypeFields VALUES(4,116,0,25);
INSERT INTO itemTypeFields VALUES(4,87,0,26);
INSERT INTO itemTypeFields VALUES(4,62,0,27);
INSERT INTO itemTypeFields VALUES(4,18,0,28);
INSERT INTO itemTypeFields VALUES(4,2,0,29);
INSERT INTO itemTypeFields VALUES(4,22,0,30);
INSERT INTO itemTypeFields VALUES(8,110,0,0);
INSERT INTO itemTypeFields VALUES(8,90,0,1);
INSERT INTO itemTypeFields VALUES(8,65,0,2);
INSERT INTO itemTypeFields VALUES(8,14,0,3);
INSERT INTO itemTypeFields VALUES(8,133,0,4);
INSERT INTO itemTypeFields VALUES(8,26,0,5);
INSERT INTO itemTypeFields VALUES(8,126,0,6);
INSERT INTO itemTypeFields VALUES(8,1,0,7);
INSERT INTO itemTypeFields VALUES(8,27,0,8);
INSERT INTO itemTypeFields VALUES(8,123,0,9);
INSERT INTO itemTypeFields VALUES(8,19,0,10);
INSERT INTO itemTypeFields VALUES(8,116,0,11);
INSERT INTO itemTypeFields VALUES(8,87,0,12);
INSERT INTO itemTypeFields VALUES(8,62,0,13);
INSERT INTO itemTypeFields VALUES(8,18,0,14);
INSERT INTO itemTypeFields VALUES(8,2,0,15);
INSERT INTO itemTypeFields VALUES(8,22,0,16);
INSERT INTO itemTypeFields VALUES(5,110,0,0);
INSERT INTO itemTypeFields VALUES(5,90,0,1);
INSERT INTO itemTypeFields VALUES(5,12,0,2);
INSERT INTO itemTypeFields VALUES(5,8,0,3);
INSERT INTO itemTypeFields VALUES(5,7,0,4);
INSERT INTO itemTypeFields VALUES(5,14,0,5);
INSERT INTO itemTypeFields VALUES(5,4,0,6);
INSERT INTO itemTypeFields VALUES(5,5,0,7);
INSERT INTO itemTypeFields VALUES(5,10,0,8);
INSERT INTO itemTypeFields VALUES(5,13,0,9);
INSERT INTO itemTypeFields VALUES(5,26,0,10);
INSERT INTO itemTypeFields VALUES(5,126,0,11);
INSERT INTO itemTypeFields VALUES(5,1,0,12);
INSERT INTO itemTypeFields VALUES(5,27,0,13);
INSERT INTO itemTypeFields VALUES(5,123,0,14);
INSERT INTO itemTypeFields VALUES(5,19,0,15);
INSERT INTO itemTypeFields VALUES(5,116,0,16);
INSERT INTO itemTypeFields VALUES(5,87,0,17);
INSERT INTO itemTypeFields VALUES(5,62,0,18);
INSERT INTO itemTypeFields VALUES(5,18,0,19);
INSERT INTO itemTypeFields VALUES(5,2,0,20);
INSERT INTO itemTypeFields VALUES(5,22,0,21);
INSERT INTO itemTypeFields VALUES(9,110,0,0);
INSERT INTO itemTypeFields VALUES(9,90,0,1);
INSERT INTO itemTypeFields VALUES(9,66,0,2);
INSERT INTO itemTypeFields VALUES(9,31,0,3);
INSERT INTO itemTypeFields VALUES(9,7,0,4);
INSERT INTO itemTypeFields VALUES(9,14,0,5);
INSERT INTO itemTypeFields VALUES(9,118,0,6);
INSERT INTO itemTypeFields VALUES(9,60,0,7);
INSERT INTO itemTypeFields VALUES(9,26,0,8);
INSERT INTO itemTypeFields VALUES(9,126,0,9);
INSERT INTO itemTypeFields VALUES(9,1,0,10);
INSERT INTO itemTypeFields VALUES(9,27,0,11);
INSERT INTO itemTypeFields VALUES(9,123,0,12);
INSERT INTO itemTypeFields VALUES(9,19,0,13);
INSERT INTO itemTypeFields VALUES(9,116,0,14);
INSERT INTO itemTypeFields VALUES(9,87,0,15);
INSERT INTO itemTypeFields VALUES(9,62,0,16);
INSERT INTO itemTypeFields VALUES(9,18,0,17);
INSERT INTO itemTypeFields VALUES(9,2,0,18);
INSERT INTO itemTypeFields VALUES(9,22,0,19);
INSERT INTO itemTypeFields VALUES(22,110,0,0);
INSERT INTO itemTypeFields VALUES(22,90,0,1);
INSERT INTO itemTypeFields VALUES(22,67,0,2);
INSERT INTO itemTypeFields VALUES(22,68,0,3);
INSERT INTO itemTypeFields VALUES(22,28,0,4);
INSERT INTO itemTypeFields VALUES(22,6,0,5);
INSERT INTO itemTypeFields VALUES(22,8,0,6);
INSERT INTO itemTypeFields VALUES(22,7,0,7);
INSERT INTO itemTypeFields VALUES(22,14,0,8);
INSERT INTO itemTypeFields VALUES(22,26,0,9);
INSERT INTO itemTypeFields VALUES(22,11,0,10);
INSERT INTO itemTypeFields VALUES(22,126,0,11);
INSERT INTO itemTypeFields VALUES(22,1,0,12);
INSERT INTO itemTypeFields VALUES(22,27,0,13);
INSERT INTO itemTypeFields VALUES(22,123,0,14);
INSERT INTO itemTypeFields VALUES(22,19,0,15);
INSERT INTO itemTypeFields VALUES(22,116,0,16);
INSERT INTO itemTypeFields VALUES(22,87,0,17);
INSERT INTO itemTypeFields VALUES(22,62,0,18);
INSERT INTO itemTypeFields VALUES(22,18,0,19);
INSERT INTO itemTypeFields VALUES(22,2,0,20);
INSERT INTO itemTypeFields VALUES(22,22,0,21);
INSERT INTO itemTypeFields VALUES(6,110,0,0);
INSERT INTO itemTypeFields VALUES(6,90,0,1);
INSERT INTO itemTypeFields VALUES(6,12,0,2);
INSERT INTO itemTypeFields VALUES(6,8,0,3);
INSERT INTO itemTypeFields VALUES(6,7,0,4);
INSERT INTO itemTypeFields VALUES(6,14,0,5);
INSERT INTO itemTypeFields VALUES(6,4,0,6);
INSERT INTO itemTypeFields VALUES(6,5,0,7);
INSERT INTO itemTypeFields VALUES(6,6,0,8);
INSERT INTO itemTypeFields VALUES(6,15,0,9);
INSERT INTO itemTypeFields VALUES(6,10,0,10);
INSERT INTO itemTypeFields VALUES(6,13,0,11);
INSERT INTO itemTypeFields VALUES(6,26,0,12);
INSERT INTO itemTypeFields VALUES(6,126,0,13);
INSERT INTO itemTypeFields VALUES(6,1,0,14);
INSERT INTO itemTypeFields VALUES(6,27,0,15);
INSERT INTO itemTypeFields VALUES(6,123,0,16);
INSERT INTO itemTypeFields VALUES(6,19,0,17);
INSERT INTO itemTypeFields VALUES(6,116,0,18);
INSERT INTO itemTypeFields VALUES(6,87,0,19);
INSERT INTO itemTypeFields VALUES(6,62,0,20);
INSERT INTO itemTypeFields VALUES(6,18,0,21);
INSERT INTO itemTypeFields VALUES(6,2,0,22);
INSERT INTO itemTypeFields VALUES(6,22,0,23);
INSERT INTO itemTypeFields VALUES(19,110,0,0);
INSERT INTO itemTypeFields VALUES(19,90,0,1);
INSERT INTO itemTypeFields VALUES(19,7,0,2);
INSERT INTO itemTypeFields VALUES(19,102,0,3);
INSERT INTO itemTypeFields VALUES(19,48,0,4);
INSERT INTO itemTypeFields VALUES(19,120,0,5);
INSERT INTO itemTypeFields VALUES(19,50,0,6);
INSERT INTO itemTypeFields VALUES(19,121,0,7);
INSERT INTO itemTypeFields VALUES(19,10,0,8);
INSERT INTO itemTypeFields VALUES(19,103,0,9);
INSERT INTO itemTypeFields VALUES(19,51,0,10);
INSERT INTO itemTypeFields VALUES(19,52,0,11);
INSERT INTO itemTypeFields VALUES(19,141,0,12);
INSERT INTO itemTypeFields VALUES(19,53,0,13);
INSERT INTO itemTypeFields VALUES(19,54,0,14);
INSERT INTO itemTypeFields VALUES(19,26,0,15);
INSERT INTO itemTypeFields VALUES(19,126,0,16);
INSERT INTO itemTypeFields VALUES(19,1,0,17);
INSERT INTO itemTypeFields VALUES(19,27,0,18);
INSERT INTO itemTypeFields VALUES(19,116,0,19);
INSERT INTO itemTypeFields VALUES(19,87,0,20);
INSERT INTO itemTypeFields VALUES(19,2,0,21);
INSERT INTO itemTypeFields VALUES(19,22,0,22);
INSERT INTO itemTypeFields VALUES(31,110,0,0);
INSERT INTO itemTypeFields VALUES(31,90,0,1);
INSERT INTO itemTypeFields VALUES(31,28,0,2);
INSERT INTO itemTypeFields VALUES(31,105,0,3);
INSERT INTO itemTypeFields VALUES(31,80,0,4);
INSERT INTO itemTypeFields VALUES(31,14,0,5);
INSERT INTO itemTypeFields VALUES(31,8,0,6);
INSERT INTO itemTypeFields VALUES(31,7,0,7);
INSERT INTO itemTypeFields VALUES(31,77,0,8);
INSERT INTO itemTypeFields VALUES(31,26,0,9);
INSERT INTO itemTypeFields VALUES(31,126,0,10);
INSERT INTO itemTypeFields VALUES(31,1,0,11);
INSERT INTO itemTypeFields VALUES(31,27,0,12);
INSERT INTO itemTypeFields VALUES(31,116,0,13);
INSERT INTO itemTypeFields VALUES(31,87,0,14);
INSERT INTO itemTypeFields VALUES(31,2,0,15);
INSERT INTO itemTypeFields VALUES(31,22,0,16);
INSERT INTO itemTypeFields VALUES(38,110,0,0);
INSERT INTO itemTypeFields VALUES(38,90,0,1);
INSERT INTO itemTypeFields VALUES(38,122,0,2);
INSERT INTO itemTypeFields VALUES(38,124,0,3);
INSERT INTO itemTypeFields VALUES(38,125,0,4);
INSERT INTO itemTypeFields VALUES(38,7,0,5);
INSERT INTO itemTypeFields VALUES(38,14,0,6);
INSERT INTO itemTypeFields VALUES(38,3,0,7);
INSERT INTO itemTypeFields VALUES(38,30,0,8);
INSERT INTO itemTypeFields VALUES(38,26,0,9);
INSERT INTO itemTypeFields VALUES(38,126,0,10);
INSERT INTO itemTypeFields VALUES(38,1,0,11);
INSERT INTO itemTypeFields VALUES(38,27,0,12);
INSERT INTO itemTypeFields VALUES(38,123,0,13);
INSERT INTO itemTypeFields VALUES(38,19,0,14);
INSERT INTO itemTypeFields VALUES(38,116,0,15);
INSERT INTO itemTypeFields VALUES(38,87,0,16);
INSERT INTO itemTypeFields VALUES(38,62,0,17);
INSERT INTO itemTypeFields VALUES(38,18,0,18);
INSERT INTO itemTypeFields VALUES(38,2,0,19);
INSERT INTO itemTypeFields VALUES(38,22,0,20);
INSERT INTO itemTypeFields VALUES(27,110,0,0);
INSERT INTO itemTypeFields VALUES(27,90,0,1);
INSERT INTO itemTypeFields VALUES(27,74,0,2);
INSERT INTO itemTypeFields VALUES(27,14,0,3);
INSERT INTO itemTypeFields VALUES(27,75,0,4);
INSERT INTO itemTypeFields VALUES(27,7,0,5);
INSERT INTO itemTypeFields VALUES(27,3,0,6);
INSERT INTO itemTypeFields VALUES(27,142,0,7);
INSERT INTO itemTypeFields VALUES(27,26,0,8);
INSERT INTO itemTypeFields VALUES(27,126,0,9);
INSERT INTO itemTypeFields VALUES(27,1,0,10);
INSERT INTO itemTypeFields VALUES(27,27,0,11);
INSERT INTO itemTypeFields VALUES(27,116,0,12);
INSERT INTO itemTypeFields VALUES(27,87,0,13);
INSERT INTO itemTypeFields VALUES(27,2,0,14);
INSERT INTO itemTypeFields VALUES(27,22,0,15);
INSERT INTO itemTypeFields VALUES(30,110,0,0);
INSERT INTO itemTypeFields VALUES(30,90,0,1);
INSERT INTO itemTypeFields VALUES(30,119,0,2);
INSERT INTO itemTypeFields VALUES(30,105,0,3);
INSERT INTO itemTypeFields VALUES(30,71,0,4);
INSERT INTO itemTypeFields VALUES(30,78,0,5);
INSERT INTO itemTypeFields VALUES(30,7,0,6);
INSERT INTO itemTypeFields VALUES(30,14,0,7);
INSERT INTO itemTypeFields VALUES(30,77,0,8);
INSERT INTO itemTypeFields VALUES(30,26,0,9);
INSERT INTO itemTypeFields VALUES(30,126,0,10);
INSERT INTO itemTypeFields VALUES(30,1,0,11);
INSERT INTO itemTypeFields VALUES(30,27,0,12);
INSERT INTO itemTypeFields VALUES(30,123,0,13);
INSERT INTO itemTypeFields VALUES(30,19,0,14);
INSERT INTO itemTypeFields VALUES(30,116,0,15);
INSERT INTO itemTypeFields VALUES(30,87,0,16);
INSERT INTO itemTypeFields VALUES(30,62,0,17);
INSERT INTO itemTypeFields VALUES(30,18,0,18);
INSERT INTO itemTypeFields VALUES(30,2,0,19);
INSERT INTO itemTypeFields VALUES(30,22,0,20);
INSERT INTO itemTypeFields VALUES(15,110,0,0);
INSERT INTO itemTypeFields VALUES(15,90,0,1);
INSERT INTO itemTypeFields VALUES(15,92,0,2);
INSERT INTO itemTypeFields VALUES(15,32,0,3);
INSERT INTO itemTypeFields VALUES(15,31,0,4);
INSERT INTO itemTypeFields VALUES(15,7,0,5);
INSERT INTO itemTypeFields VALUES(15,14,0,6);
INSERT INTO itemTypeFields VALUES(15,28,0,7);
INSERT INTO itemTypeFields VALUES(15,30,0,8);
INSERT INTO itemTypeFields VALUES(15,10,0,9);
INSERT INTO itemTypeFields VALUES(15,26,0,10);
INSERT INTO itemTypeFields VALUES(15,11,0,11);
INSERT INTO itemTypeFields VALUES(15,126,0,12);
INSERT INTO itemTypeFields VALUES(15,1,0,13);
INSERT INTO itemTypeFields VALUES(15,27,0,14);
INSERT INTO itemTypeFields VALUES(15,13,0,15);
INSERT INTO itemTypeFields VALUES(15,123,0,16);
INSERT INTO itemTypeFields VALUES(15,19,0,17);
INSERT INTO itemTypeFields VALUES(15,116,0,18);
INSERT INTO itemTypeFields VALUES(15,87,0,19);
INSERT INTO itemTypeFields VALUES(15,62,0,20);
INSERT INTO itemTypeFields VALUES(15,18,0,21);
INSERT INTO itemTypeFields VALUES(15,2,0,22);
INSERT INTO itemTypeFields VALUES(15,22,0,23);
INSERT INTO itemTypeFields VALUES(40,110,0,0);
INSERT INTO itemTypeFields VALUES(40,90,0,1);
INSERT INTO itemTypeFields VALUES(40,132,0,2);
INSERT INTO itemTypeFields VALUES(40,46,0,3);
INSERT INTO itemTypeFields VALUES(40,108,0,4);
INSERT INTO itemTypeFields VALUES(40,60,0,5);
INSERT INTO itemTypeFields VALUES(40,81,0,6);
INSERT INTO itemTypeFields VALUES(40,6,0,7);
INSERT INTO itemTypeFields VALUES(40,131,0,8);
INSERT INTO itemTypeFields VALUES(40,14,0,9);
INSERT INTO itemTypeFields VALUES(40,8,0,10);
INSERT INTO itemTypeFields VALUES(40,7,0,11);
INSERT INTO itemTypeFields VALUES(40,137,0,12);
INSERT INTO itemTypeFields VALUES(40,138,0,13);
INSERT INTO itemTypeFields VALUES(40,11,0,14);
INSERT INTO itemTypeFields VALUES(40,26,0,15);
INSERT INTO itemTypeFields VALUES(40,126,0,16);
INSERT INTO itemTypeFields VALUES(40,1,0,17);
INSERT INTO itemTypeFields VALUES(40,27,0,18);
INSERT INTO itemTypeFields VALUES(40,123,0,19);
INSERT INTO itemTypeFields VALUES(40,19,0,20);
INSERT INTO itemTypeFields VALUES(40,116,0,21);
INSERT INTO itemTypeFields VALUES(40,118,0,22);
INSERT INTO itemTypeFields VALUES(40,87,0,23);
INSERT INTO itemTypeFields VALUES(40,62,0,24);
INSERT INTO itemTypeFields VALUES(40,18,0,25);
INSERT INTO itemTypeFields VALUES(40,2,0,26);
INSERT INTO itemTypeFields VALUES(40,22,0,27);
INSERT INTO itemTypeFields VALUES(20,112,0,0);
INSERT INTO itemTypeFields VALUES(20,90,0,1);
INSERT INTO itemTypeFields VALUES(20,36,0,2);
INSERT INTO itemTypeFields VALUES(20,55,0,3);
INSERT INTO itemTypeFields VALUES(20,101,0,4);
INSERT INTO itemTypeFields VALUES(20,100,0,5);
INSERT INTO itemTypeFields VALUES(20,10,0,6);
INSERT INTO itemTypeFields VALUES(20,15,0,7);
INSERT INTO itemTypeFields VALUES(20,40,0,8);
INSERT INTO itemTypeFields VALUES(20,42,0,9);
INSERT INTO itemTypeFields VALUES(20,26,0,10);
INSERT INTO itemTypeFields VALUES(20,126,0,11);
INSERT INTO itemTypeFields VALUES(20,1,0,12);
INSERT INTO itemTypeFields VALUES(20,27,0,13);
INSERT INTO itemTypeFields VALUES(20,116,0,14);
INSERT INTO itemTypeFields VALUES(20,87,0,15);
INSERT INTO itemTypeFields VALUES(20,2,0,16);
INSERT INTO itemTypeFields VALUES(20,22,0,17);
INSERT INTO itemTypeFields VALUES(7,110,0,0);
INSERT INTO itemTypeFields VALUES(7,90,0,1);
INSERT INTO itemTypeFields VALUES(7,69,0,2);
INSERT INTO itemTypeFields VALUES(7,89,0,3);
INSERT INTO itemTypeFields VALUES(7,7,0,4);
INSERT INTO itemTypeFields VALUES(7,14,0,5);
INSERT INTO itemTypeFields VALUES(7,3,0,6);
INSERT INTO itemTypeFields VALUES(7,30,0,7);
INSERT INTO itemTypeFields VALUES(7,118,0,8);
INSERT INTO itemTypeFields VALUES(7,26,0,9);
INSERT INTO itemTypeFields VALUES(7,11,0,10);
INSERT INTO itemTypeFields VALUES(7,126,0,11);
INSERT INTO itemTypeFields VALUES(7,1,0,12);
INSERT INTO itemTypeFields VALUES(7,27,0,13);
INSERT INTO itemTypeFields VALUES(7,13,0,14);
INSERT INTO itemTypeFields VALUES(7,123,0,15);
INSERT INTO itemTypeFields VALUES(7,19,0,16);
INSERT INTO itemTypeFields VALUES(7,116,0,17);
INSERT INTO itemTypeFields VALUES(7,87,0,18);
INSERT INTO itemTypeFields VALUES(7,62,0,19);
INSERT INTO itemTypeFields VALUES(7,18,0,20);
INSERT INTO itemTypeFields VALUES(7,2,0,21);
INSERT INTO itemTypeFields VALUES(7,22,0,22);
INSERT INTO itemTypeFields VALUES(29,110,0,0);
INSERT INTO itemTypeFields VALUES(29,90,0,1);
INSERT INTO itemTypeFields VALUES(29,119,0,2);
INSERT INTO itemTypeFields VALUES(29,105,0,3);
INSERT INTO itemTypeFields VALUES(29,63,0,4);
INSERT INTO itemTypeFields VALUES(29,78,0,5);
INSERT INTO itemTypeFields VALUES(29,7,0,6);
INSERT INTO itemTypeFields VALUES(29,14,0,7);
INSERT INTO itemTypeFields VALUES(29,77,0,8);
INSERT INTO itemTypeFields VALUES(29,26,0,9);
INSERT INTO itemTypeFields VALUES(29,126,0,10);
INSERT INTO itemTypeFields VALUES(29,1,0,11);
INSERT INTO itemTypeFields VALUES(29,27,0,12);
INSERT INTO itemTypeFields VALUES(29,123,0,13);
INSERT INTO itemTypeFields VALUES(29,19,0,14);
INSERT INTO itemTypeFields VALUES(29,116,0,15);
INSERT INTO itemTypeFields VALUES(29,87,0,16);
INSERT INTO itemTypeFields VALUES(29,62,0,17);
INSERT INTO itemTypeFields VALUES(29,18,0,18);
INSERT INTO itemTypeFields VALUES(29,2,0,19);
INSERT INTO itemTypeFields VALUES(29,22,0,20);
INSERT INTO itemTypeFields VALUES(28,110,0,0);
INSERT INTO itemTypeFields VALUES(28,90,0,1);
INSERT INTO itemTypeFields VALUES(28,63,0,2);
INSERT INTO itemTypeFields VALUES(28,28,0,3);
INSERT INTO itemTypeFields VALUES(28,4,0,4);
INSERT INTO itemTypeFields VALUES(28,45,0,5);
INSERT INTO itemTypeFields VALUES(28,76,0,6);
INSERT INTO itemTypeFields VALUES(28,7,0,7);
INSERT INTO itemTypeFields VALUES(28,14,0,8);
INSERT INTO itemTypeFields VALUES(28,77,0,9);
INSERT INTO itemTypeFields VALUES(28,11,0,10);
INSERT INTO itemTypeFields VALUES(28,26,0,11);
INSERT INTO itemTypeFields VALUES(28,126,0,12);
INSERT INTO itemTypeFields VALUES(28,1,0,13);
INSERT INTO itemTypeFields VALUES(28,27,0,14);
INSERT INTO itemTypeFields VALUES(28,123,0,15);
INSERT INTO itemTypeFields VALUES(28,19,0,16);
INSERT INTO itemTypeFields VALUES(28,116,0,17);
INSERT INTO itemTypeFields VALUES(28,87,0,18);
INSERT INTO itemTypeFields VALUES(28,62,0,19);
INSERT INTO itemTypeFields VALUES(28,18,0,20);
INSERT INTO itemTypeFields VALUES(28,2,0,21);
INSERT INTO itemTypeFields VALUES(28,22,0,22);
INSERT INTO itemTypeFields VALUES(13,110,0,0);
INSERT INTO itemTypeFields VALUES(13,90,0,1);
INSERT INTO itemTypeFields VALUES(13,91,0,2);
INSERT INTO itemTypeFields VALUES(13,70,0,3);
INSERT INTO itemTypeFields VALUES(13,14,0,4);
INSERT INTO itemTypeFields VALUES(13,8,0,5);
INSERT INTO itemTypeFields VALUES(13,7,0,6);
INSERT INTO itemTypeFields VALUES(13,26,0,7);
INSERT INTO itemTypeFields VALUES(13,126,0,8);
INSERT INTO itemTypeFields VALUES(13,1,0,9);
INSERT INTO itemTypeFields VALUES(13,27,0,10);
INSERT INTO itemTypeFields VALUES(13,116,0,11);
INSERT INTO itemTypeFields VALUES(13,87,0,12);
INSERT INTO itemTypeFields VALUES(13,2,0,13);
INSERT INTO itemTypeFields VALUES(13,22,0,14);
INSERT INTO baseFieldMappings VALUES(12,109,59);
INSERT INTO baseFieldMappings VALUES(26,109,71);
INSERT INTO baseFieldMappings VALUES(26,8,72);
INSERT INTO baseFieldMappings VALUES(16,60,93);
INSERT INTO baseFieldMappings VALUES(16,4,94);
INSERT INTO baseFieldMappings VALUES(16,10,95);
INSERT INTO baseFieldMappings VALUES(16,127,41);
INSERT INTO baseFieldMappings VALUES(23,12,107);
INSERT INTO baseFieldMappings VALUES(23,108,70);
INSERT INTO baseFieldMappings VALUES(2,109,130);
INSERT INTO baseFieldMappings VALUES(3,12,115);
INSERT INTO baseFieldMappings VALUES(3,109,130);
INSERT INTO baseFieldMappings VALUES(17,110,111);
INSERT INTO baseFieldMappings VALUES(17,127,44);
INSERT INTO baseFieldMappings VALUES(17,14,96);
INSERT INTO baseFieldMappings VALUES(17,60,117);
INSERT INTO baseFieldMappings VALUES(17,4,97);
INSERT INTO baseFieldMappings VALUES(17,10,98);
INSERT INTO baseFieldMappings VALUES(32,8,83);
INSERT INTO baseFieldMappings VALUES(33,12,114);
INSERT INTO baseFieldMappings VALUES(39,60,128);
INSERT INTO baseFieldMappings VALUES(39,8,124);
INSERT INTO baseFieldMappings VALUES(39,7,129);
INSERT INTO baseFieldMappings VALUES(39,109,130);
INSERT INTO baseFieldMappings VALUES(36,12,86);
INSERT INTO baseFieldMappings VALUES(21,110,113);
INSERT INTO baseFieldMappings VALUES(35,12,85);
INSERT INTO baseFieldMappings VALUES(11,8,21);
INSERT INTO baseFieldMappings VALUES(11,108,122);
INSERT INTO baseFieldMappings VALUES(11,109,63);
INSERT INTO baseFieldMappings VALUES(25,12,104);
INSERT INTO baseFieldMappings VALUES(25,108,79);
INSERT INTO baseFieldMappings VALUES(18,60,99);
INSERT INTO baseFieldMappings VALUES(18,127,41);
INSERT INTO baseFieldMappings VALUES(10,109,64);
INSERT INTO baseFieldMappings VALUES(8,108,65);
INSERT INTO baseFieldMappings VALUES(9,108,66);
INSERT INTO baseFieldMappings VALUES(9,8,31);
INSERT INTO baseFieldMappings VALUES(22,108,67);
INSERT INTO baseFieldMappings VALUES(19,127,120);
INSERT INTO baseFieldMappings VALUES(19,60,50);
INSERT INTO baseFieldMappings VALUES(19,14,52);
INSERT INTO baseFieldMappings VALUES(19,134,141);
INSERT INTO baseFieldMappings VALUES(19,131,54);
INSERT INTO baseFieldMappings VALUES(31,60,105);
INSERT INTO baseFieldMappings VALUES(31,109,80);
INSERT INTO baseFieldMappings VALUES(38,108,122);
INSERT INTO baseFieldMappings VALUES(38,8,124);
INSERT INTO baseFieldMappings VALUES(38,60,125);
INSERT INTO baseFieldMappings VALUES(27,108,74);
INSERT INTO baseFieldMappings VALUES(27,12,142);
INSERT INTO baseFieldMappings VALUES(30,12,119);
INSERT INTO baseFieldMappings VALUES(30,60,105);
INSERT INTO baseFieldMappings VALUES(30,109,71);
INSERT INTO baseFieldMappings VALUES(30,8,78);
INSERT INTO baseFieldMappings VALUES(15,60,92);
INSERT INTO baseFieldMappings VALUES(15,108,32);
INSERT INTO baseFieldMappings VALUES(15,8,31);
INSERT INTO baseFieldMappings VALUES(40,127,132);
INSERT INTO baseFieldMappings VALUES(20,110,112);
INSERT INTO baseFieldMappings VALUES(20,60,101);
INSERT INTO baseFieldMappings VALUES(20,14,100);
INSERT INTO baseFieldMappings VALUES(7,108,69);
INSERT INTO baseFieldMappings VALUES(7,8,89);
INSERT INTO baseFieldMappings VALUES(29,12,119);
INSERT INTO baseFieldMappings VALUES(29,60,105);
INSERT INTO baseFieldMappings VALUES(29,109,63);
INSERT INTO baseFieldMappings VALUES(29,8,78);
INSERT INTO baseFieldMappings VALUES(28,109,63);
INSERT INTO baseFieldMappings VALUES(28,8,76);
INSERT INTO baseFieldMappings VALUES(13,12,91);
INSERT INTO baseFieldMappings VALUES(13,108,70);
INSERT INTO itemTypeCreatorTypes VALUES(12,22,1);
INSERT INTO itemTypeCreatorTypes VALUES(12,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(26,17,1);
INSERT INTO itemTypeCreatorTypes VALUES(26,30,0);
INSERT INTO itemTypeCreatorTypes VALUES(26,18,0);
INSERT INTO itemTypeCreatorTypes VALUES(26,19,0);
INSERT INTO itemTypeCreatorTypes VALUES(26,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(26,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(16,12,1);
INSERT INTO itemTypeCreatorTypes VALUES(16,28,0);
INSERT INTO itemTypeCreatorTypes VALUES(16,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(23,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(23,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(23,23,0);
INSERT INTO itemTypeCreatorTypes VALUES(23,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(2,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(2,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(2,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(2,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(2,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(3,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(3,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(3,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(3,29,0);
INSERT INTO itemTypeCreatorTypes VALUES(3,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(3,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(17,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(17,13,0);
INSERT INTO itemTypeCreatorTypes VALUES(17,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(32,21,1);
INSERT INTO itemTypeCreatorTypes VALUES(32,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(33,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(33,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(33,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(33,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(33,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(39,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(39,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(36,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(36,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(36,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(36,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(36,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(34,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(34,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(34,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(34,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(34,27,0);
INSERT INTO itemTypeCreatorTypes VALUES(21,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(21,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(21,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(21,16,0);
INSERT INTO itemTypeCreatorTypes VALUES(35,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(35,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(35,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(35,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(35,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,8,1);
INSERT INTO itemTypeCreatorTypes VALUES(11,10,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,9,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,11,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,31,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,25,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,32,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(11,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(25,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(25,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(18,2,1);
INSERT INTO itemTypeCreatorTypes VALUES(24,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(24,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(24,16,0);
INSERT INTO itemTypeCreatorTypes VALUES(10,6,1);
INSERT INTO itemTypeCreatorTypes VALUES(10,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(10,7,0);
INSERT INTO itemTypeCreatorTypes VALUES(10,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(4,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(4,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(4,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(4,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(4,27,0);
INSERT INTO itemTypeCreatorTypes VALUES(8,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(8,16,0);
INSERT INTO itemTypeCreatorTypes VALUES(8,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(8,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(5,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(5,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(5,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(5,27,0);
INSERT INTO itemTypeCreatorTypes VALUES(9,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(9,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(9,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(22,20,1);
INSERT INTO itemTypeCreatorTypes VALUES(22,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(22,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(6,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(6,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(6,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(6,27,0);
INSERT INTO itemTypeCreatorTypes VALUES(19,14,1);
INSERT INTO itemTypeCreatorTypes VALUES(19,15,0);
INSERT INTO itemTypeCreatorTypes VALUES(19,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,26,1);
INSERT INTO itemTypeCreatorTypes VALUES(31,25,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,10,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,33,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,34,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,8,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,9,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,11,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(31,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(38,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(38,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(38,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(38,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(38,27,0);
INSERT INTO itemTypeCreatorTypes VALUES(27,24,1);
INSERT INTO itemTypeCreatorTypes VALUES(27,35,0);
INSERT INTO itemTypeCreatorTypes VALUES(27,36,0);
INSERT INTO itemTypeCreatorTypes VALUES(27,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(27,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,37,1);
INSERT INTO itemTypeCreatorTypes VALUES(30,31,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,25,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,10,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,33,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,34,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,8,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,9,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,11,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(30,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(15,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(15,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(15,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(15,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(15,5,0);
INSERT INTO itemTypeCreatorTypes VALUES(40,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(40,3,0);
INSERT INTO itemTypeCreatorTypes VALUES(40,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(20,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(20,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(7,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(7,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,8,1);
INSERT INTO itemTypeCreatorTypes VALUES(29,10,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,33,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,34,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,9,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,11,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,31,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,25,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,32,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(29,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,37,1);
INSERT INTO itemTypeCreatorTypes VALUES(28,8,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,10,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,9,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,33,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,11,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,31,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,25,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,32,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,4,0);
INSERT INTO itemTypeCreatorTypes VALUES(28,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(13,1,1);
INSERT INTO itemTypeCreatorTypes VALUES(13,2,0);
INSERT INTO itemTypeCreatorTypes VALUES(13,4,0);
