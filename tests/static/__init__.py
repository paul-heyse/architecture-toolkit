"""Static-only fixtures.

These modules exist to be type-checked, not executed. Pyrefly checks them because `tests` is in
`project-includes`; pytest collects nothing here because no file is named `test_*`.
"""
