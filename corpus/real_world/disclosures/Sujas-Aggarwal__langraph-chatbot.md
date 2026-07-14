# Generated SQL runs unreviewed on a superuser connection (`versions/v2.6.0.py`)

Hello, and thanks for publishing langraph-chatbot.

I'm reaching out as part of an academic study of agent-workflow verification, in
which we review publicly available agent code for control-flow and safety patterns.
I found a data-safety gap in the text-to-SQL flow that I think is worth your
attention. I've described the mechanism but deliberately left out any ready-to-run
destructive statement.

## What I looked at

`versions/v2.6.0.py`, pinned at commit
`1e5cc6bd1ea8875de5058289fab6d3ad71138a5a`:

https://github.com/Sujas-Aggarwal/langraph-chatbot/blob/1e5cc6bd1ea8875de5058289fab6d3ad71138a5a/versions/v2.6.0.py

## What I found

LLM-generated SQL is executed verbatim, with no human review of the SQL on any
path and no read-only restriction, against a superuser database connection:

- `route_after_spell_check` (lines **492–496**) sends a high-confidence spelling
  match straight to `generate_sql` (skipping the `confirmation` node), and the
  graph then runs `generate_sql → execute_query → END` (lines **519–520**).
- The `confirmation` node (lines **384–397**) only asks the user to confirm a
  **village-name spelling** — it never shows or approves the SQL. So even the
  "confirmed" path never reviews the query.
- `generate_sql_node` builds the query from the **raw** user request embedded in the
  prompt (lines **419–432**), with no instruction to stay read-only.
- `execute_query_node` (lines **459–472**) hands that SQL to
  `PostgreSQLManager.execute_query` (lines **166–174**), which runs *any* statement
  — there's no `SELECT`-only check or sanitisation.
- The connection string at line **674** is a superuser DSN
  (`postgresql://postgres:admin@localhost:5432/...`).

So a user request — or a prompt injection that steers generation — can cause a
statement beyond a read-only `SELECT` to run with superuser privileges and no
review. (I noticed `execute_query` never `commit()`s, so plain writes may roll back
on connection close; I'd treat that as incidental rather than a safeguard, since a
superuser connection has side-effecting paths that don't depend on a committed
transaction.)

## Why it matters

The one confirmation prompt in the flow only covers spelling, so there is no path on
which a human sees the SQL before it runs. Combined with a superuser connection,
that turns "the model wrote an unexpected query" into "the database ran it."

## A possible minimal fix

Two changes together close the gap:

1. **Least privilege:** connect with a **read-only** database role and reject
   anything that isn't a `SELECT` (a parse-and-allowlist check before execution),
   rather than connecting as `postgres`.
2. **Review gate:** show the generated SQL and require an explicit human "yes"
   before `execute_query` on **every** path (not only the spelling-confirmation
   branch).

Either helps; both together are robust.

## Scope note

As published this looks like a local CLI demo against `localhost`, so the immediate
risk is limited — it grows if the app is ever deployed and its query box is exposed
to untrusted users. The fixes above are cheap to add now regardless.

## Offer

Happy to sketch the read-only-role + SELECT-allowlist check as a small PR if that's
useful, or to adjust anything I've mischaracterised.

Thanks again.

— [SENDER]
(part of an academic study of agent-workflow verification)
</content>
