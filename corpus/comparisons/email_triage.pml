/*
 * Promela model of the lg_email_triage workflow.
 *
 * This manually-written SPIN model encodes the same workflow that
 * Agentproof extracts automatically from LangGraph source code.
 * The contrast demonstrates the modeling effort gap: 60+ lines of
 * Promela vs. a single call to extract_langgraph().
 *
 * Workflow topology:
 *   __start__ -> classify -> router --(urgent)--> urgent_handler -> send -> __end__
 *                                   \--(normal)--> normal_handler -> draft_response (DEAD END)
 *
 * Properties to verify:
 *   1. Exit reachability: can __end__ always be reached?
 *   2. Dead-end freedom: are there nodes with no outgoing transitions?
 */

mtype = { START, CLASSIFY, ROUTER, URGENT, NORMAL, DRAFT, SEND, END_NODE };

mtype current_node = START;
bool reached_end = false;
bool is_urgent;    /* non-deterministic routing decision */

active proctype email_triage() {
    /* __start__ */
    current_node = START;

    /* __start__ -> classify */
    current_node = CLASSIFY;

    /* classify -> router */
    current_node = ROUTER;

    /* router: non-deterministic choice between urgent and normal */
    if
    :: is_urgent = true;
       current_node = URGENT;
       /* urgent_handler -> send */
       current_node = SEND;
       /* send -> __end__ */
       current_node = END_NODE;
       reached_end = true;
    :: is_urgent = false;
       current_node = NORMAL;
       /* normal_handler -> draft_response (BUG: dead end, no edge to send) */
       current_node = DRAFT;
       /* STUCK: draft_response has no outgoing edge */
    fi;
}

/*
 * LTL property: the workflow should always eventually reach __end__.
 * This property FAILS because the normal-priority path gets stuck
 * at draft_response.
 *
 * To verify with SPIN:
 *   spin -a email_triage.pml
 *   cc -o pan pan.c
 *   ./pan -a -N exit_reachable
 */
ltl exit_reachable { <> (current_node == END_NODE) }

/*
 * =========================================================================
 * COMPARISON: Agentproof equivalent
 * =========================================================================
 *
 * With Agentproof, the same verification requires NO manual modeling:
 *
 *   from agentproof import verify
 *   from agentproof.graph.model import graph_from_dict
 *   import json
 *
 *   graph = graph_from_dict(json.load(open("lg_email_triage.json")))
 *   report = verify(graph, require_human=True)
 *   # => dead_ends: ["draft_response"]
 *   # => witness: __start__ -> classify -> router -> normal_handler -> draft_response
 *
 * Key differences:
 *   - SPIN: 60+ lines of manual Promela, requires expertise in formal methods
 *   - Agentproof: automatic extraction, 3 lines of Python
 *   - SPIN: general-purpose (handles arbitrary concurrent systems)
 *   - Agentproof: domain-specific (agent workflow graphs only)
 *   - SPIN: verification time comparable for small graphs, but modeling time is hours
 *   - Agentproof: total time < 1ms including extraction
 */
