# Suggestion: human-review gate before the crew sends email / changes the calendar

Hi, and thanks for sharing fraya-25.

I'm writing as part of an academic study of agent-workflow verification — we review
publicly available agent code for control-flow and safety patterns. I noticed
something in `crew.py` that you may want to consider; it's a suggestion rather than
a bug report, and I may be missing context, so please read it in that spirit.

## What I looked at

`crew.py`, pinned at commit `8da54c34951398cf66e0bba1144dfba40f240c3c`:

https://github.com/Jamahl/fraya-25/blob/8da54c34951398cf66e0bba1144dfba40f240c3c/crew.py

## What I noticed

The crew runs as an autonomous two-task pipeline with no human-review step, while
its agents hold tools that can take real external actions:

- Both agents are created with `tools=mcp_tools` (lines **43** and **50**), and the
  `__main__` block loads Composio **Gmail + Google Calendar** MCP servers
  (lines **108–109**) — i.e. message-send and calendar write/delete capability.
- The two `Task`s (lines **54–63**) do **not** set CrewAI's `human_input=True`
  flag, and the crew is assembled and run straight through with
  `crew.kickoff(email_json)` (lines **65–72**). So there's no point at which a
  human approves an action before it happens.
- The module docstring (line **5**) describes the purpose as "... action (e.g.,
  booking meetings, drafting/sending replies)", and `reply_task` (line **60**)
  covers "rearranging a meeting or cancelling a meeting" — actions that mutate a
  real calendar. The preferences block hardcodes a specific individual's address
  and user id (lines **30**, **36**).

Put together: if the crew ever proceeds past drafting to actually sending a reply or
changing the calendar, it does so on a live account with no human in the loop, and
a misread intent (or an adversarial inbound email) becomes an outbound action.

I should be honest that this depends on how far the crew goes: `reply_agent`'s goal
is "Draft email replies" (line 48) and `reply_task`'s expected output is a "Drafted
reply" (line 61), so if a human always sends the draft manually afterwards, the gap
is smaller than it looks. That's exactly the point I'd like to check with you.

## Why it matters

Sending email and mutating a calendar are hard to undo and are visible to third
parties. A per-task confirmation gate is a cheap insurance policy against the agent
acting on a wrong or manipulated interpretation.

## A possible minimal fix

CrewAI supports `human_input=True` on a `Task`. Setting it on `reply_task` (and on
any task that can send email or change the calendar) inserts a human confirmation
before the action runs, without changing the analysis flow.

## Offer

If this is helpful I'm glad to send a small PR adding the gate, or to close this out
if the sending/mutation is already handled by a human step I couldn't see from
`crew.py` alone.

Thanks for the project.

— [SENDER]
(part of an academic study of agent-workflow verification)
</content>
