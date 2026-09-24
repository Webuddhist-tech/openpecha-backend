# Database package reference

This document provides an overview of the Neo4j-backed data access layer in [functions/database](../../functions/database). No file in this package was previously documented in the docs; this single overview covers all modules.

---

## Table of Contents

1. [Overview](#overview)
2. [Connection](#connection)
3. [Database facade](#database-facade)
4. [Annotation subpackage](#annotation-subpackage)
5. [Supporting modules](#supporting-modules)

---

## Overview

The database package provides a single entrypoint, the **Database** class in [functions/database/database.py](../../functions/database/database.py). It holds a Neo4j driver and exposes domain-specific accessors (e.g. `db.person`, `db.expression`) that perform Cypher queries and return data as Pydantic models or dicts. The package is used as a context manager (`with Database() as db`) or by calling `get_session()` for lower-level access.

---

## Connection

**Constructor:** `Database(neo4j_uri: str | None = None, neo4j_auth: tuple | None = None)`

- **With arguments** – Uses the given `neo4j_uri` and `neo4j_auth` (e.g. in tests). Connects and verifies connectivity on init.
- **Without arguments** – Reads from environment: `NEO4J_URI` (required), `NEO4J_USERNAME` (default `"neo4j"`), `NEO4J_PASSWORD` (required). Raises `ValueError` if required env vars are missing.

**Methods:**

- `get_session() -> Session` – Returns a Neo4j session for the default database.
- `close()` – Closes the driver.
- `__enter__` / `__exit__` – Context manager support; `__exit__` calls `close()`.

---

## Database facade

Each attribute below is an instance of the corresponding module, used to perform CRUD and queries for that domain.

| Attribute | Module | Responsibility |
|-----------|--------|-----------------|
| **db.api_key** | [api_key_database.py](../../functions/database/api_key_database.py) | API key creation, validation, and optional binding to an application. |
| **db.application** | [application_database.py](../../functions/database/application_database.py) | Application (tenant) CRUD; used for multi-tenant isolation. |
| **db.expression** | [expression_database.py](../../functions/database/expression_database.py) | Expression (text/work) CRUD, contributions, commentary/translation relationships, listing by filter. |
| **db.edition** | [edition_database.py](../../functions/database/edition_database.py) | Manifestation (edition) CRUD, content, related editions, alignment and expression relationships. |
| **db.annotation** | [database.py](../../functions/database/database.py) (AnnotationDatabase) | Aggregate for annotation sub-modules: alignment, segmentation, pagination, table of contents, note, bibliographic, attributes. |
| **db.segment** | [segment_database.py](../../functions/database/segment_database.py) | Segment CRUD and search-related segmentation. |
| **db.person** | [person_database.py](../../functions/database/person_database.py) | Person CRUD and listing with optional name/bdrc/wiki filters. |
| **db.language** | [language_database.py](../../functions/database/language_database.py) | Language code CRUD and listing. |
| **db.category** | [category_database.py](../../functions/database/category_database.py) | Category CRUD and hierarchy (parent/children). |
| **db.span** | [span_database.py](../../functions/database/span_database.py) | Span and text content operations (e.g. for edition content and PATCH). |

Method-level detail for each module is left to the source; this doc describes roles only.

---

## Annotation subpackage

[functions/database/annotation/](../../functions/database/annotation/) contains annotation-type-specific modules. They are not used as top-level `db.*` attributes; they are attached under **db.annotation**:

| Attribute | File | Responsibility |
|-----------|------|-----------------|
| **db.annotation.segmentation** | [segmentation_database.py](../../functions/database/annotation/segmentation_database.py) | Segmentation annotations. |
| **db.annotation.pagination** | [pagination_database.py](../../functions/database/annotation/pagination_database.py) | Pagination (volume/page) annotations. |
| **db.annotation.table_of_contents** | [table_of_contents_database.py](../../functions/database/annotation/table_of_contents_database.py) | Table of contents annotations with localized section titles, summaries, spans, and recursive subsection hierarchy. |
| **db.annotation.note** | [note_database.py](../../functions/database/annotation/note_database.py) | Note annotations (e.g. durchen). |
| **db.annotation.mark** | [mark_database.py](../../functions/database/annotation/mark_database.py) | Span-only mark annotations (currently yigchung). |
| **db.annotation.bibliographic** | [bibliographic_database.py](../../functions/database/annotation/bibliographic_database.py) | Bibliographic metadata annotations. |
| **db.annotation.attributes** | [attribute_database.py](../../functions/database/annotation/attribute_database.py) | Attribute annotations (e.g. OCR confidence). |

`db.alignment` is a top-level service for direct edition-pair segment alignment relationships.

---

## Supporting modules

These modules are not exposed as `db.<name>` but are used internally by the facade modules.

| Module | Responsibility |
|--------|----------------|
| [database_validator.py](../../functions/database/database_validator.py) | **DatabaseValidator** – Static methods for validation inside write transactions: e.g. original expression uniqueness per work, person/person_bdrc reference checks, expression creation rules, edition alignment uniqueness. Used by expression and edition (and related) code. |
| [nomen_database.py](../../functions/database/nomen_database.py) | **NomenDatabase** – Nomenclature/name handling: creating Nomen nodes with localized text and optional alternative-of links. Used by person_database and expression_database (and similar) for name/title storage. |

For method-level detail and Cypher usage, see the source files in [functions/database](../../functions/database).
