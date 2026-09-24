# Review of PR #17

Line numbers refer to the proposed code in `review/pr_17.diff`, not the current
working files. I reviewed the diff without applying it.

## 1. Search input can change the SQL query

- File and line: `app/routes/search.py:14`
- Severity: blocker
- Problem: `name` is inserted directly into the SQL string. A value such as
  `' OR 1=1 --` can change the condition and return all accounts.
- Suggested fix: use `WHERE client_name LIKE ?` and pass the search pattern as a
  separate parameter. Add tests with quotes and SQL-like input to confirm they
  are treated as text. See [OWASP's SQL guidance](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html).

## 2. Retrying a ledger request can move money twice

- File and line: `app/services/ledger_client.py:33`
- Severity: blocker
- Problem: the ledger might save a transfer but time out before sending its
  response. The retry sends another POST without a stable transfer ID or retry
  key. The ledger cannot reliably tell that both requests are the same transfer.
- Suggested fix: send the local transfer ID as a stable idempotency key. Confirm
  that the ledger stores that key and returns the original result on retries.
  Build the payload once and reuse it. Test a timeout after the ledger has saved
  the transfer and check that only one transfer exists there.

## 3. Local success and ledger delivery can disagree

- File and line: `app/routes/transfers.py:45`
- Severity: blocker
- Problem: the local database is already committed before `post_transfer` runs.
  If delivery fails, the caller gets an error even though balances changed. A
  process crash after the commit can also leave the ledger unaware of the
  transfer. There is no saved delivery job to recover it.
- Suggested fix: save a pending delivery row in the same database transaction
  as the transfer. Have a worker send it, retry with the stable key, and record
  success. This is called an outbox. Test recovery after a crash and a ledger
  outage. Moving the HTTP call before the commit alone does not solve this.

## 4. Error logs expose full account numbers

- File and line: `app/services/ledger_client.py:37`
- Severity: blocker
- Problem: every failed attempt writes both account numbers to the logs. This
  copies private financial identifiers into another place that needs protection.
- Suggested fix: log the transfer ID, attempt number, and a safe error category.
  Leave account numbers and request bodies out. Add a test that captures logs
  and checks that neither account number appears. See [OWASP's logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

## 5. The retry handler repeats permanent failures

- File and line: `app/services/ledger_client.py:17`
- Severity: should-fix
- Problem: `httpx.HTTPError` includes errors raised for HTTP status codes. A bad
  request or rejected credentials can therefore be sent three times without
  anything changing. All callers also wait for the same fixed delays.
- Suggested fix: after making retries safe, retry only agreed temporary failures.
  Do not retry ordinary 400, 401, or 403 responses. Respect `Retry-After` where
  supported and add a small random delay with a total time limit. Test the
  request count for permanent and temporary failures. See [HTTPX's exception list](https://www.python-httpx.org/exceptions/).

## 6. The submitted time has no timezone

- File and line: `app/services/ledger_client.py:30`
- Severity: should-fix
- Problem: `datetime.now()` uses local time without a timezone. That conflicts
  with the service's UTC convention and can be read differently by the ledger.
  It also creates a different submitted time on each retry.
- Suggested fix: reuse the transfer's original UTC timestamp in every attempt.
  Test that the timestamp has a UTC offset and stays the same after a retry.

## 7. Database failures look like successful empty searches

- File and line: `app/routes/search.py:17`
- Severity: should-fix
- Problem: `except Exception` turns database errors and coding mistakes into a
  200 response with no results. Users cannot tell whether no clients matched or
  the search failed.
- Suggested fix: catch only errors that have a defined recovery path. Return a
  suitable error status for a failed search and keep SQL details out of the
  response. Test a database failure separately from a valid search with no match.

## 8. Search can return the whole account table

- File and line: `app/routes/search.py:15`
- Severity: should-fix
- Problem: `fetchall()` has no result limit. An empty name matches every account;
  `%` and `_` also act as search wildcards. Large results can use too much memory
  and expose more client records than the user needs.
- Suggested fix: reject blank or overly long search terms and add bounded
  pagination. Decide whether wildcard search is intended; escape those characters
  if the search should treat them literally. Test empty terms, wildcards, and
  searches that match more than one page.

Decision: request changes.
