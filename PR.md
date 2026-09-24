# Transfer fixes

The positions endpoint made a separate database query for each fund. Transfers
used floating-point math, returned inconsistent money strings, and ignored retry
keys. Negative amounts and transfers to the same account could change balances
incorrectly. Some invalid inputs and database locks caused server errors.

I replaced the fund lookups with a join. I used Decimal for transfer math and
formatted money with two decimal places. I added checks for invalid amounts,
accounts, balances, and retry keys. Transfer writes and the saved retry response
now succeed or fail together. Repeated requests return the original response.
Reusing a key with different inputs returns 409. A busy database returns 503 so
the caller can retry.

I fixed test imports so pytest runs from the repository root. All tests pass,
including the unchanged original tests. Added tests cover stored balances,
simultaneous requests, retries, and failures during writes.

I kept the API fields and existing money columns to stay compatible with the
seed. I added a money limit instead of changing storage in this step. Login and
account access rules remain outside this exercise because no identity model was
provided. These are still needed before production use.
