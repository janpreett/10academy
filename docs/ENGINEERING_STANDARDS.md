# Engineering standards

Researched: 2026-09-23. Scope: the Python 3.11+ FastAPI/SQLite assignment.
These are implementation and review requirements for future changes, not an
audit certification. Preserve the assignment's public API and existing tests.
Source links are included so decisions can be checked against primary guidance.

## 1. Consistent, descriptive Python

Use `snake_case` for functions, variables, parameters, and modules; `PascalCase`
for classes; and `UPPER_SNAKE_CASE` for constants. Prefer `source_account`,
`destination_account`, `transfer_amount`, and `database_connection` over
`src`, `dst`, `amt`, or vague names such as `data` and `temp`. Established short
names are acceptable where their meaning is immediately clear.

Use four-space indentation, grouped imports, and readable expressions. Add type
annotations to changed function boundaries. Types help reasoning but do not
replace runtime validation. Comments explain business rules, constraints, and
non-obvious choices; keep them current. Preserve external field names even when
an internal name changes. Use an alias for the query parameter `from` because it
is a Python keyword.

Source: [Python PEP 8](https://peps.python.org/pep-0008/).

## 2. Simple design and practical SOLID

The following are this project's application of SOLID, not a requirement to
introduce a class hierarchy:

- Single responsibility: keep HTTP parsing, business decisions, and database
  details understandable. Extract a helper or service when it clarifies a real
  responsibility, rather than splitting every small function.
- Open/closed: centralize genuine shared rules, such as money validation, so a
  new use does not duplicate them. Avoid speculative plugin systems.
- Liskov substitution: replacements and test doubles must preserve their
  contract, including exceptions and transaction behavior.
- Interface segregation: expose only the operations a caller needs. Avoid a
  generic manager responsible for unrelated work.
- Dependency inversion: pass database or external-service dependencies through
  explicit boundaries. FastAPI dependency overrides support isolated tests.

Prefer composition, small functions, and explicit control flow. Reuse actual
shared logic; do not build abstractions solely to satisfy a slogan. Add packages
only for a clear benefit, after checking compatibility and maintenance.

Implementation reference:
[FastAPI dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/).

## 3. Money and transfer invariants

Use decimal arithmetic or integer minor units for money, with an explicit
precision and rounding policy. Do not perform balance arithmetic with binary
floats. Reject non-finite values, non-positive transfers, unsupported precision,
and values outside documented limits. Return money as strings with exactly two
decimal places, preserving the API.

The seed stores money in SQLite `REAL`. Decide and document how compatibility
will be maintained or migrated before implementation; formatting a float to two
places alone does not make its arithmetic exact.

Treat source debit, destination credit, transfer record, ledger entries, and any
idempotency record as one atomic operation. Roll back the entire operation on
failure. Reject same-account transfers and verify both accounts before mutation.
Protect the balance check and updates from concurrent requests; test with
separate connections. SQLite permits one writer at a time, but that alone does
not make an earlier unprotected read/check safe. Choose transaction boundaries
deliberately and handle lock contention explicitly.

Persist idempotency state under a unique key. Repeating the same request must
return the original response without moving money again. Define the conflict
behavior when the same key is used with different inputs. Test concurrent
duplicates and rollback behavior. Do not blindly retry financial side effects.

Sources: [Python decimal](https://docs.python.org/3.11/library/decimal.html),
[Python 3.11 sqlite3](https://docs.python.org/3.11/library/sqlite3.html), and
[SQLite isolation](https://www.sqlite.org/isolation.html).

## 4. Input validation and safe database access

Validate request structure and business meaning on the server: types, ranges,
allowed transaction types, ISO dates, date ordering, and cursor structure/size.
Bound page sizes and other user-controlled work. Follow the ticket's error
codes, including 400 for invalid cursors, 404 for unknown accounts, and 422 for
invalid query parameters.

Bind all SQL values with placeholders. Never interpolate request values into
SQL. If identifiers or sort options must vary, select them from a fixed internal
allowlist; SQL parameters cannot bind identifiers. Enable foreign keys on each
connection and use appropriate uniqueness/check constraints to reinforce
business rules. Close connections and keep transactions short.

Catch exceptions only where a meaningful response or recovery is possible.
Never turn a database failure into a successful empty result. Keep stack traces,
SQL statements, local paths, and credentials out of client-facing errors.

Sources: [Python sqlite3 placeholders](https://docs.python.org/3.11/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries),
[OWASP input validation](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html),
and [OWASP REST security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html).

## 5. Authorization, secrets, and privacy

Account identifiers and pagination cursors are not proof of permission. A
production service needs authenticated callers and server-side authorization for
each account operation, including both sides of a transfer. Deny access unless
explicitly allowed, and give infrastructure identities only necessary rights.

The seed has no authentication contract. Record that limitation; introducing an
identity platform during this exercise requires a deliberate API/scope decision.
Do not describe this baseline or a passing test suite as production banking
security. Production deployment also needs HTTPS, protected database files and
backups, secret management, retention rules, and tested operational controls.

Use synthetic test data. Commit no credentials, environment files, private keys,
database files, or real client exports. Ignore rules are only one guard: inspect
staged files before publishing. Inject production secrets through the deployment
environment or an appropriate secret store.

Return only required fields. Do not log raw account numbers, client names,
authorization headers, request bodies, or financial details. Use minimal
correlation identifiers and safe event categories; control log access and
retention. Treat untrusted log fields as untrusted input.

Sources: [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
[OWASP logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html),
and [OWASP REST security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html).

## 6. Data structures, queries, and pagination

Choose structures for the operation: ordered lists for response items, sets for
membership checks, dictionaries for keyed lookup. Keep filtering, ordering, and
bounded retrieval in SQL rather than loading the entire history into Python.
Avoid one lookup query per result row; use joins where appropriate. Add indexes
for real filter/order patterns, then examine query plans instead of assuming
an index improves every query.

For TKT-212, the proposed design is keyset pagination with deterministic
`created_at DESC, id DESC` ordering. A timestamp alone cannot distinguish ties.
Fetch `limit + 1` rows to detect whether another page exists.

Define the traversal as a snapshot of records present at its start. Carry a
first-page insertion watermark alongside the last-seen sort key so later
inserts, including backdated ones, do not change that traversal. With the seed's
autoincrement IDs this can use an initial maximum ID; verify assumptions about
insertion and immutability in tests. Bind cursor context to the account and
filters and validate it on every page. Encoding is not authorization or
tamper protection. Decide whether integrity signing is needed and document the
secret-management implications rather than hardcoding a signing secret.

Test tied timestamps, new and backdated inserts between pages, empty results,
last pages, malformed cursors, and incompatible cursor/filter combinations.
Document that a watermark does not preserve deleted rows or old values after
updates; those need a stronger history/snapshot design if required.

This pagination approach is a project design proposal derived from
[TKT-212](TKT-212.md), to be validated during implementation.

## 7. Verification and review

Test observable behavior and database invariants, not just status codes. Cover
money conservation, no partial writes, invalid inputs, missing accounts,
precision, idempotency conflicts, and concurrent requests where relevant.
Every additional transfer defect needs its own regression coverage. Use
temporary databases and avoid real external services in tests.

Run the full existing suite from the repository root after changes. Review
dependencies for supported versions and known vulnerabilities before shipping;
record a reproducible tested environment rather than claiming an unrun audit.
Keep scope small, inspect diffs, and state verification gaps honestly. Review
the supplied PR as text; do not merge its code as part of writing the review.
