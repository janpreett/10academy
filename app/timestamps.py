"""A sortable key for the service's UTC ISO timestamps, to microsecond precision."""

# Preserve created_at in responses. Pad the optional fractional part so equal
# instants written with Z, +00:00, or different precision compare equally.
# SQLite's date functions round to milliseconds, so they would lose precision.
UTC_SORT_KEY = """
substr(created_at, 1, 19) || '.' ||
CASE WHEN substr(created_at, 20, 1) = '.' THEN
    substr(replace(replace(substr(created_at, 21), '+00:00', ''), 'Z', '')
           || '000000', 1, 6)
ELSE '000000' END
""".strip()
