# Enterprise Intranet Assistant: Authorization & Permission Matrix

This document defines and documents the least-privilege role-based access control (RBAC) matrix for all organizational roles within the Enterprise Intranet Assistant.

## 1. Principles of Least Privilege

- **Separation of Concerns**: System administration and diagnostics are strictly separated from business and departmental data.
- **Administrative Boundary**: Possessing the `admin` (Security Administrator) role grants account provisioning, password reset, audit log access, and capacity diagnostics. It does **NOT** grant access to HR records, employee compensation, performance reviews, or proprietary engineering source repositories.
- **Deny-by-Default**: If a role is not explicitly granted a permission or listed in a document's `.acl.json`, access is rejected with HTTP 403 Forbidden or omitted from search results.

---

## 2. Role-to-Permission Mapping

| Role | Role Title | Assigned Permissions | Accessible Resources |
| :--- | :--- | :--- | :--- |
| **employee** | General Employee | `chat:use`<br>`documents:search`<br>`database:read` | • Intranet Chat Assistant<br>• Public documents (IT Security, Leave Policy)<br>• Public employee directory (`directory.by_department`) |
| **engineer** | Software / Systems Engineer | `chat:use`<br>`documents:search`<br>`database:read`<br>`engineering:read` | • Everything in `employee`<br>• Engineering Handbook & architecture runbooks<br>• Engineering system inventory query |
| **hr** | Human Resources Partner | `chat:use`<br>`documents:search`<br>`database:read`<br>`hr:read` | • Everything in `employee`<br>• HR Benefits Guide & confidential policies<br>• HR employee compensation & detailed records query |
| **analyst** | Financial / Data Analyst | `chat:use`<br>`database:read` | • Intranet Chat Assistant<br>• Public employee directory query |
| **admin** | Security Administrator | `chat:use`<br>`database:read`<br>`admin:diagnostics`<br>`users:read`<br>`users:write`<br>`audit:read` | • Intranet Chat Assistant<br>• Public employee directory query<br>• User account creation, update, & password resets<br>• Administrative audit event logs<br>• LLM inference capacity & queue metrics<br>*(Excluded from HR records and Engineering runbooks)* |

---

## 3. Resource Boundary Matrix

| Resource Identifier | Resource Type | Required Permission / Role | Allowed Roles |
| :--- | :--- | :--- | :--- |
| `directory.by_department` | SQL Catalog Query | `database:read` | `employee`, `engineer`, `hr`, `analyst`, `admin` |
| `hr.employee_records` | SQL Catalog Query | `hr:read` | `hr` |
| `engineering.system_inventory` | SQL Catalog Query | `engineering:read` | `engineer` |
| `it_security_guide.md` | Document Root | `documents:search` + ACL | `employee`, `analyst`, `admin`, `engineer`, `hr` |
| `leave_policy.md` | Document Root | `documents:search` + ACL | `employee`, `analyst`, `admin`, `engineer`, `hr` |
| `engineering_handbook.md` | Document Root | `documents:search` + ACL | `engineer` |
| `hr_benefits_guide.md` | Document Root | `documents:search` + ACL | `hr` |
| `/api/v1/admin/users` (GET) | REST Endpoint | `users:read` | `admin` |
| `/api/v1/admin/users` (POST, PATCH) | REST Endpoint | `users:write` | `admin` |
| `/api/v1/admin/users/{u}/reset-password` | REST Endpoint | `users:write` | `admin` |
| `/api/v1/admin/audit-events` | REST Endpoint | `audit:read` | `admin` |
| `/api/v1/admin/metrics` | REST Endpoint | `admin:diagnostics` | `admin` |

---

## 4. Enforcement Points

1. **API Router**: Endpoints enforce permissions via `Depends(require_permission(...))`.
2. **MCP Tool Execution**: `BaseMCPTool.execute` independently verifies `tool.required_permission in identity.permissions`.
3. **Database Service**: `DatabaseQueryService.execute` matches `query.required_permission` against the user's active permissions.
4. **Document Indexer**: `DocumentIndexer.search` checks intersection between chunk `allowed_roles` and user `roles`.
5. **Prompt / Graph Restrictor**: `_format_system_prompt` and `reason_node` only expose and permit tools authorized for the caller.
