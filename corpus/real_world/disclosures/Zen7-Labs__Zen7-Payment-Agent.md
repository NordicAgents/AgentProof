# Suggested safety gate before payment settlement in `host_agent/agent.py`

Hello, and thank you for open-sourcing Zen7-Payment-Agent.

I'm reaching out as part of an academic study of agent-workflow verification, in
which we review publicly available agent code for control-flow and safety
patterns. While looking at your repository I noticed something on the payment path
that I think is worth flagging. I've kept this to a private report first, since it
touches money movement; please feel free to make it public if you'd prefer.

## What I looked at

`host_agent/agent.py`, pinned at commit
`a1546be076c14d1f270b1109c1e055fd53b685c8`:

https://github.com/Zen7-Labs/Zen7-Payment-Agent/blob/a1546be076c14d1f270b1109c1e055fd53b685c8/host_agent/agent.py

## What I found

The payment pipeline creates a payment and then settles it as a single
uninterrupted sequence, with no human-approval step in between:

- Lines **60–64** define
  `SequentialAgent("PaymentAgentPipeline", sub_agents=[payer_agent, settlement_agent, payee_agent])`.
  A `SequentialAgent` runs its sub-agents in order, so payment creation flows
  directly into settlement and then payee notification with nothing to pause on.
- The live host instruction at line **94** explicitly discourages a confirmation
  step: *"Immediate make decision, tranfer to the target agent and automatical
  start the process, DO NOT make any confirmation."*

For an irreversible on-chain settlement (USDC/DAI), that means a wrong amount, a
wrong payee, or a maliciously-crafted inbound instruction can settle funds with no
opportunity for a human to intervene.

I want to be upfront about the limits of my review: I only examined
`host_agent/agent.py` at the commit above. The sub-agent modules
(`payer_agent`, `settlement_agent`, `payee_agent`) were not in the snapshot I
looked at, so if one of them already implements an approval/hold step before
settlement, then this may not apply and I'd be glad to hear that. I'm also aware
the long block of `#`-commented text near the top (roughly lines 9–57) is inert
documentation, not active behaviour — I'm relying only on the live line-94
instruction and the pipeline structure.

## Why it matters

Crypto settlement can't be undone. A human-in-the-loop confirmation before the
settlement step is a small change that turns "an unexpected instruction moves
money" into "an unexpected instruction is caught before money moves."

## A possible minimal fix

Insert an explicit approval step between payment creation and settlement — for
example an ADK `LongRunningFunctionTool` (or a small confirmation sub-agent) placed
between `payer_agent` and `settlement_agent` in `PaymentAgentPipeline` — and relax
the line-94 instruction so it no longer forbids confirmation on the money-movement
path. That keeps the automated flow for everything up to settlement while requiring
a human "go" for the irreversible step.

## Offer

Happy to help — I can open a follow-up issue with a concrete sketch, or a small PR,
if that's useful. And if I've misread the flow (e.g. a downstream gate I couldn't
see), I'd genuinely appreciate the correction.

Thanks again for the project.

— [SENDER]
(part of an academic study of agent-workflow verification; contactable at the
address in this message)
</content>
