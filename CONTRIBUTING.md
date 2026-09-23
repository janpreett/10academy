# Working on advisor-accounts

Read [Engineering standards](docs/ENGINEERING_STANDARDS.md) before changing code.
The standards are project decisions informed by the linked official sources;
they are not a claim that the seed already meets them.

## Workflow

1. Read the relevant routes, database schema, tests, and ticket. Preserve the
   existing API contract and the original tests.
2. Reproduce the defect or define the feature's observable acceptance criteria.
3. Make one focused change with descriptive Python names and minimal complexity.
4. Add meaningful tests for each transfer defect, including failure paths and
   persisted state. Use isolated temporary databases and synthetic data.
5. Run `pytest` from this repository's root. Record the actual result and any
   checks that could not run. Review the entire diff before committing.
6. Check staged files for credentials, databases, client data, and generated
   files. Use a focused commit message such as `fix: make transfers atomic`.

Do not delete, skip, or weaken existing tests to make the suite pass. Do not
apply `review/pr_17.diff`: it is an input for the written code review.

## Assignment completion

- Fix failing tests and other transfer defects, adding regression coverage.
- Implement transaction history according to `docs/TKT-212.md`, including stable
  pagination when new transactions arrive.
- Write `PR.md` (at most 200 words) describing problems, changes, and justified
  exclusions.
- Write `REVIEW.md` with file/line, severity, problem, and suggested fix for each
  comment, ending in approve or request changes.
- Write `NOTES.md`: What I don't trust (at most 150 words) and AI use (at most
  100 words). Describe tools and verification honestly.
- Confirm `pytest` passes from the root before submitting the repository link.

The initial baseline contains the supplied exercise, these standards, and ignore
rules. Assignment fixes and final submission documents are still pending.
