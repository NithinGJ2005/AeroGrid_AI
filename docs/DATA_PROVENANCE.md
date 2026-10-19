# Data Provenance & Directory Catalog Specification

## 1. Overview and Provenance
The internal corporate directory is stored in SQLite (`sample_db.sqlite3`, table `employee_directory`).
In an enterprise environment, this table is synced from corporate identity providers, Human Resources Information Systems (HRIS), or automated CSV/LDAP pipelines into the internal query database.

### System of Record Details
- **Database Engine**: SQLite 3 (WAL mode)
- **Table Name**: `employee_directory`
- **Catalog Query**: `directory.by_department` (`SELECT employee_id, display_name, department FROM employee_directory WHERE department = :department ORDER BY display_name LIMIT 100`)
- **Query Permission**: `database:read` (Available to all authorized employees)

---

## 2. Department Records & Exact Filtering
The `employee_directory` table currently contains records for the following distinct corporate departments:
1. **Engineering**: Alice Chen (`EMP-001`), Bob Smith (`EMP-002`)
2. **Product**: Carol Danvers (`EMP-003`)
3. **Human Resources**: David Miller (`EMP-004`)
4. **Finance**: Emma Watson (`EMP-005`)

### Department Filtering Invariants
- **No Silent Substitution**: If a user queries for “Data Engineering” (`department: "Data Engineering"`), the query returns **0 rows**. The assistant must faithfully state:
  > *"No matching records were found for the Data Engineering department in internal company records."*
- The assistant **must not** fabricate records, nor silently broaden the query to “Engineering” to return Alice Chen or Bob Smith.
- When querying “Engineering” (`department: "Engineering"`), the database matches Alice Chen and Bob Smith.

---

## 3. Provenance and Citation Accuracy
- **Database Citations**: When a database query returns authorized records, citations accurately attribute the data to:
  `sample_db.sqlite3 [table: employee_directory]`
- **Empty Query Result**: When a database query returns 0 rows, **no citations are generated**, and no false source attribution is displayed.
- **Execution Badge**: The execution status badge in the chat UI displays the exact query executed (`directory.by_department` on internal SQLite database) rather than misrepresenting database queries as document scans or vice-versa.
