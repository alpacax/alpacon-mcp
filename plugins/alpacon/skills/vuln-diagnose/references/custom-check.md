# The person's own check command

When none of the install methods fits, the person supplies the command. Before running it:

- It must only read. A command that installs, edits, restarts, or deletes anything belongs in `vuln-remediate`, not here; say so and do not run it.
- It must print one line per server that says the verdict, ideally `verdict=affected`, `verdict=not_affected`, or `verdict=unknown`. If it prints something else, agree with the person how to read its output before running it.

Output that does not match what you agreed is `unknown`, with the output in the reason.
