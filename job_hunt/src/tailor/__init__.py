"""Resume tailoring: one master resume, tailored per posting.

`document` reads and writes the master's Markdown shape, `grounding`
checks that a tailored line says nothing its master lines did not,
`claude` holds the two prompts, and `tailor` ties them together.
"""
