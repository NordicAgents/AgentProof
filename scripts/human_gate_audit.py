#!/usr/bin/env python3
"""Uniform human-gate audit (policy HGP-1) over the 32 source-level side-effecting workflows.

Motivation
----------
The three policy-violation cases previously reported on the 119-workflow validation
sample were produced by two *different* checks (``human_presence`` on mined graphs and
``human_gate_coverage`` on reconstructed graphs). That is not a single estimand. This
script records the result of applying ONE prospectively specified policy
(``papers/paper1/aaai/HUMAN_GATE_POLICY.md``) independently to every workflow in the
sample whose source contains a side-effecting tool, so that false negatives lying
outside both flag universes become visible.

The verdicts below are the product of manual source review against HGP-1; this script
is the machine-checkable record of them. It recomputes descriptive audit
proportions, Wilson summaries, the flag-universe cross-reference, and the
false-negative list from the corpus artifacts, and fails loudly if the corpus
no longer agrees with the audit.

Usage:
    python scripts/human_gate_audit.py
    python scripts/human_gate_audit.py --output corpus/real_world/human_gate_audit.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path

from slugkey import ambiguous_slugs

POLICY_ID = "HGP-1"
POLICY_PATH = "papers/paper1/aaai/HUMAN_GATE_POLICY.md"
GT_TRIAGE = "corpus/real_world/gt_triage_results.json"
REVISION = "corpus/real_world/revision_analyses.json"
SOURCES = "corpus/real_world/sources"

# ---------------------------------------------------------------------------
# Threshold rule actually applied (policy (a)): a side-effecting callable counts
# only if it is (i) invocable by an agent/LLM, or (ii) called inside a graph node
# body that executes during a workflow run. Script-level setup/teardown/reporting
# code that is not part of an agent workflow run does not count. This is what
# separates the "binds an exec tool but never runs an agent" cases (compliant)
# from the "agent can call it right now" cases (violation).
# ---------------------------------------------------------------------------

AUDIT: list[dict] = [
    # ---------------- VIOLATIONS ----------------
    {
        "slug": "AdaptiveBProcess__bpm_agent__main",
        "verdict": "violation",
        "tool": "run_pipeline / list_logs -> run_subprocess (subprocess.Popen, shell=True)",
        "category": "exec",
        "source_lines": [52, 195],
        "justification": "L182 binds tools to the model; L195 dispatches TOOL_MAP[name](**args) "
                         "immediately on the LLM's choice; L52 runs subprocess.Popen with shell=True on a "
                         "command string built from LLM-supplied args (L92-100). Only human interaction is "
                         "st.chat_input (L236), a generic task REPL, excluded by policy (b).",
        "not_merely_tutorial": "Streamlit app wired to a real business-process-simulation CLI with st.secrets "
                               "config and subprocess timeout handling; classified application_like.",
        "gate": None,
    },
    {
        "slug": "Arhamirfan__Snake-Agents__snake_autogen",
        "verdict": "violation",
        "tool": "UserProxyAgent code_execution_config (auto-executes agent-authored python/shell/PowerShell)",
        "category": "exec",
        "source_lines": [20, 21, 24],
        "justification": "human_input_mode='TERMINATE' (L20) is explicitly NOT a gate under policy (b); "
                         "use_docker=False (L24) with work_dir='code' (L22) means agent-authored code runs on "
                         "the host, so E6 does not apply. Engineer (L28) and QA (L38) are instructed to write "
                         "and run code; the seed task (L70) demands files be saved to disk.",
        "not_merely_tutorial": "Executes model-authored shell/PowerShell on the host with no container. The "
                               "demo framing does not change what the code does (policy N1).",
        "gate": "placebo: UserProxyAgent typed 'human' in the reference graph but human_input_mode='TERMINATE'",
    },
    {
        "slug": "Harsh1210__llm-opsbot__main",
        "verdict": "violation",
        "tool": "requests.post to Meta WhatsApp Graph API",
        "category": "comms_third_party",
        "source_lines": [148, 159],
        "justification": "POST /webhook (L94) schedules process_message (L115), which invokes the agent (L131) "
                         "and delivers the result to a phone number taken from inbound webhook data (L104) via "
                         "requests.post (L148). No input(), interrupt, or UserProxyAgent exists in the file.",
        "not_merely_tutorial": "Live FastAPI webhook service sending WhatsApp messages to real third-party "
                               "recipients; classified application_like.",
        "gate": None,
    },
    {
        "slug": "Itzkuldeep__AgentE-com__main",
        "verdict": "violation",
        "tool": "smart_email_sender (agent-invocable), plus team_state.json / team_history.json writes",
        "category": "comms_third_party",
        "source_lines": [245, 342, 347],
        "justification": "In the imported wiring, smart_email_sender is registered both for_llm (agents.py L252) "
                         "and for_execution (agents.py L260) on EmailSenderAgent itself, so the proposing and "
                         "executing agent are identical; user_proxy is placed LAST in the round-robin (L262) and "
                         "never speaks between proposal and execution, failing policy (b)3. Writes at L342/L347 "
                         "are unconditional local-filesystem writes (N4).",
        "not_merely_tutorial": "E-commerce assistant with real SMTP/Gmail send path behind a WebSocket endpoint; "
                               "classified application_like.",
        "gate": "non-dominating: UserProxyAgent human_input_mode='ALWAYS' (L233/L250) exists but is ordered after "
                "the executing agent",
    },
    {
        "slug": "NavalGear__Manufacturing_Process_Plan__autogen_agents",
        "verdict": "violation",
        "tool": "UserProxyAgent code_execution_config (auto-executes agent-authored Python)",
        "category": "exec",
        "source_lines": [50, 52, 66],
        "justification": "human_input_mode='NEVER' (L50) is explicitly not a gate; use_docker=False (L52) with "
                         "work_dir='execution_env' runs agent-authored Python on the host. L66-67 additionally "
                         "writes part_specs.json. initiate_chat (L83) drives the loop with no confirmation.",
        "not_merely_tutorial": "Manufacturing-process planning tool executing model-generated CNC optimisation "
                               "code locally; classified application_like.",
        "gate": None,
    },
    {
        "slug": "SAMAR-CODE404__backend__Main",
        "verdict": "violation",
        "tool": "financial_reporting / operations_reporting -> open(output_path,'w') report writes",
        "category": "external_write",
        "source_lines": [50, 54, 58],
        "justification": "Six nodes named *_human_approval (Main.py L50/54/58/68/72/76) sit on the path to the "
                         "report writes (fin_agent.py L84-85, operations_agent.py L131-132), but their body is "
                         "'proceed = self.approval' (research_agent.py L72, fin_agent.py L98) reading a "
                         "constructor flag hard-set to True (Main.py L32-38). No human input is ever read, so "
                         "under policy (b) these are not gates.",
        "not_merely_tutorial": "M&A due-diligence backend writing financial/valuation/risk reports; classified "
                               "application_like. This is the placebo-gate exemplar.",
        "gate": "placebo: 6 nodes typed 'human' in the reference graph whose body reads a hard-coded True flag",
    },
    {
        "slug": "SAMAR-CODE404__backend__merger_agent",
        "verdict": "violation",
        "tool": "open(feasibility/valuation/risk_report_path,'w') inside node bodies",
        "category": "external_write",
        "source_lines": [70, 119, 168],
        "justification": "Three report files are written from node bodies at L70-71, L119-120 and L168-169. "
                         "grep for input/interrupt/human_input_mode/confirm/approv returns nothing in this "
                         "file: there is no gate of any kind on any path.",
        "not_merely_tutorial": "Part of the same M&A due-diligence backend; persists analyst-facing reports.",
        "gate": None,
    },
    {
        "slug": "SAMAR-CODE404__backend__report_agent",
        "verdict": "violation",
        "tool": "open(report_filename,'w') inside node body",
        "category": "external_write",
        "source_lines": [245],
        "justification": "Final report written at L245-246 from a node body. No input/interrupt/approval "
                         "construct exists anywhere in the file.",
        "not_merely_tutorial": "Same production backend; emits the deliverable report artifact.",
        "gate": None,
    },
    {
        "slug": "Sujas-Aggarwal__langraph-chatbot__v2.6.0",
        "verdict": "violation",
        "tool": "psycopg2 cursor.execute CREATE EXTENSION / INSERT INTO locations + conn.commit",
        "category": "external_write",
        "source_lines": [43, 99, 76],
        "justification": "Schema and row writes at L43, L46-76 and L98-120 run with no gate at all. The "
                         "confirmation_node (L372) covers only location spelling and is bypassed on the "
                         "auto-confirm branch (L399-404) whenever similarity clears the threshold, so it does "
                         "not dominate the write path.",
        "not_merely_tutorial": "Postgres-backed chatbot performing DDL and row inserts against a live database. "
                               "This is the case both existing checks already flag.",
        "gate": "partial: confirmation_node exists but auto-confirms above threshold (L399-404)",
    },
    {
        "slug": "blueming333__aicraft-class-autogen__GitHubOfficialMcpExample",
        "verdict": "violation",
        "tool": "unrestricted GitHub MCP server toolset (file create/update, PR creation)",
        "category": "external_write",
        "source_lines": [69, 76, 123],
        "justification": "StdioServerParams (L69-73) launches the official GitHub MCP server with args=[] (no "
                         "toolset restriction) and the real GITHUB_TOKEN; mcp_server_tools (L76) loads every "
                         "tool and all are bound to the agent (L123). The system message advertises creating and "
                         "updating files and opening pull requests (L100-104). The team is run at L157. The "
                         "input() at L151 selects a task, which policy (b) excludes as a gate; the user may also "
                         "type an arbitrary custom task.",
        "not_merely_tutorial": "Grants unrestricted write-capable GitHub credentials to an autonomous agent. "
                               "The example framing does not restrict the toolset (policy N1/N3). "
                               "subprocess.run(['which',...]) at L52 was NOT counted: constant, not model-influenced.",
        "gate": None,
    },
    {
        "slug": "blueming333__aicraft-class-autogen__PythonAstREPLTool",
        "verdict": "violation",
        "tool": "PythonAstREPLTool (arbitrary in-process Python execution)",
        "category": "exec",
        "source_lines": [21, 33, 43],
        "justification": "PythonAstREPLTool is wrapped at L21 and bound to the AssistantAgent at L33; the team "
                         "is run autonomously at L43-45 with only a TextMentionTermination condition. The tool "
                         "executes model-authored Python in the host process with no sandbox, so E6 does not apply.",
        "not_merely_tutorial": "A Python REPL tool is unrestricted code execution regardless of the toy "
                               "'average passenger age' prompt (policy N1); the model chooses the code.",
        "gate": None,
    },
    {
        "slug": "ed-donner__agents__sequential_agents",
        "verdict": "violation",
        "tool": "save_order_to_sheet (Google Sheets write)",
        "category": "external_write",
        "source_lines": [5, 148],
        "justification": "save_order_to_sheet is imported at L5 and bound as a live agent tool at L148. The "
                         "'reply confirm' step exists only as natural-language instruction inside the prompt "
                         "(L133-138); policy (b)2 requires the negative branch to exist in source, and it does "
                         "not. The model holds the tool and can invoke it without the confirmation turn.",
        "not_merely_tutorial": "Persists customer orders (name, phone, email, payment method) to a real Google "
                               "Sheet. Prompt-level confirmation is unenforced, which is precisely the failure mode.",
        "gate": "prompt-level only: unenforced natural-language confirmation, no source branch",
    },

    # ---------------- COMPLIANT ----------------
    {
        "slug": "Md-Emon-Hasan__LangGraph__7_human_in_the_loop",
        "verdict": "compliant",
        "tool": "buy_stocks (returns a formatted string; no external effect)",
        "category": None,
        "source_lines": [26, 30, 63],
        "justification": "interrupt() at L26 blocks before any action and its negative branch at L30-31 returns "
                         "'Buying declined.', skipping the effect; the checkpointer (L51) plus input() (L63) and "
                         "Command(resume=...) (L64) make the block genuine. The tool body itself performs no "
                         "external action (E5).",
        "not_merely_tutorial": None,
        "gate": "genuine: LangGraph interrupt() dominating, negative branch present",
    },
    {
        "slug": "MdArshath2004__snowflakeoptimization__tes",
        "verdict": "compliant",
        "tool": "cursor.execute(optimized_query) against Snowflake",
        "category": "exec",
        "source_lines": [232, 527, 542],
        "justification": "The SQL execution at L232 is reachable only via agent.workflow.invoke at L542, which "
                         "sits inside an action-specific `if st.button('Run Execution Validation'...)` at L527 "
                         "preceded by an explicit warning (L521); ALTER WAREHOUSE at L100 is likewise reachable "
                         "only from inside button handlers (L384, L527). The gate dominates both call sites.",
        "not_merely_tutorial": None,
        "gate": "genuine: action-specific Streamlit button dominating the call site",
    },
    {
        "slug": "LightningGod7__prometheus__test_agent",
        "verdict": "compliant",
        "tool": "LocalCommandLineCodeExecutor (bound, never invoked)",
        "category": "exec",
        "source_lines": [110, 118],
        "justification": "The executor is constructed at L110 but the only operations performed on any agent are "
                         "dump_component/load_component round-trips and assertions (L38-48, L116-126). No path "
                         "from any test entry point reaches an invocation, so condition (c) is not satisfied.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "ericjiang18__Agent-Q-Mix__test_agent",
        "verdict": "compliant",
        "tool": "LocalCommandLineCodeExecutor (bound, never invoked)",
        "category": "exec",
        "source_lines": [110],
        "justification": "Same autogen serialization test as above: the executor is bound at L110 and grep for "
                         "run/on_messages/execute_code finds no invocation anywhere in the file.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "microsoft__ACV__test_agent",
        "verdict": "compliant",
        "tool": "LocalCommandLineCodeExecutor (bound, never invoked)",
        "category": "exec",
        "source_lines": [110, 118],
        "justification": "Agent is only serialized and deserialized (L118) and asserted on (L124-126); the "
                         "executor is never driven.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "microsoft__ACV__test_cache_agent",
        "verdict": "compliant",
        "tool": "Cache.disk (test-harness infrastructure, not agent-invocable)",
        "category": None,
        "source_lines": [104, 139, 151],
        "justification": "The agent-invocable side effect is code execution, and it is E6-excluded: work_dir is "
                         "a tempfile.TemporaryDirectory (L139, L179) and use_docker='python:3' (L151, L197), so "
                         "the confinement is visible in source. Cache.disk at L104/L117 is harness scaffolding "
                         "around the chat, not a callable the agent can invoke, so it falls outside the policy "
                         "(a) threshold.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "project194-cognitivellm__cognitivellm__gwt_run_autogen_eval",
        "verdict": "compliant",
        "tool": "execute_action -> env.step (in-process ALFWorld simulator)",
        "category": None,
        "source_lines": [239, 215, 266],
        "justification": "The one agent-invocable tool, execute_action (registered L239-245), drives env.step "
                         "(L31) against a simulated ALFWorld environment constructed in-process at L215-216, "
                         "which is E3. The CSV write at L266 is script-level reporting in main() after the chat "
                         "completes, not an agent-invocable tool nor a node body, so it is outside the policy "
                         "(a) threshold. Note this is one of the three cases the existing check flags.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "Sidreyas__The_Grand_AI_Repo__builder",
        "verdict": "compliant",
        "tool": "LocalCommandLineCodeExecutor / PythonCodeExecutionTool (configured, never invoked)",
        "category": "exec",
        "source_lines": [331, 424],
        "justification": "This module authors a gallery of team *configurations* and serializes them: the only "
                         "runtime effect is open('gallery_default.json','w') at L424-425 under __main__ (L421), "
                         "which is script-level, not an agent-invocable tool or node body. No agent or team is "
                         "ever run, so the exec tool at L331-332 is never reachable — the same rule applied to "
                         "the serialization tests above.",
        "not_merely_tutorial": None,
        "gate": "inert: web_user_proxy (L273) is serialized into a config, never executed",
    },
    {
        "slug": "waqasniazi9__voice-agent__builder",
        "verdict": "compliant",
        "tool": "LocalCommandLineCodeExecutor / McpWorkbench filesystem (configured, never invoked)",
        "category": "exec",
        "source_lines": [433, 565, 633],
        "justification": "Structurally identical to Sidreyas builder: gallery configs are assembled and dumped "
                         "to gallery_default.json at L633-634 under __main__ (L628). The exec tool (L433) and "
                         "filesystem MCP workbench (L565) are serialized into configs, never invoked here.",
        "not_merely_tutorial": None,
        "gate": "inert: web_user_proxy serialized into a config, never executed",
    },

    # ---------------- ARGUABLE ----------------
    {
        "slug": "Zen7-Labs__Zen7-Payment-Agent__agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "payer_agent / settlement_agent (USDC/DAI payment creation and settlement)",
        "category": "financial",
        "source_lines": [4, 5, 60, 94],
        "justification": "The absence of a gate is certain and deliberate: the prompts forbid confirmation four "
                         "times (L19, L22, L23, L94 'DO NOT make any confirmation'). But every sub-agent that "
                         "would move money is imported from .sub_agents.* (L4-8) and no such file exists in the "
                         "corpus, so whether a real settlement executes cannot be established from source.",
        "not_merely_tutorial": "Crypto payment settlement service; the single most concerning arguable. Only the "
                               "callee body is unverifiable, not the missing gate.",
        "gate": None,
    },
    {
        "slug": "Jamahl__fraya-25__crew",
        "verdict": "arguable",
        "arguable_reason": "(ii)",
        "tool": "composio Gmail + Google Calendar MCP tools (resolved at runtime)",
        "category": "comms_third_party",
        "source_lines": [119, 43, 51],
        "justification": "No gate exists: neither Task sets human_input=True (L54-63) and the Crew's only "
                         "step_callback is print (L65-70), which policy (b) excludes. But the tool set is "
                         "enumerated dynamically by MCPServerAdapter (L119) from remote endpoints, so no "
                         "specific callee can be pinned. The concrete requests.delete/post/patch helpers "
                         "(L89-102) are defined but never bound to any agent and never called.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "gabrielpreda__adk-sql-agent__agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "SQL generation/execution inside subagents.generator / subagents.routing",
        "category": "external_write",
        "source_lines": [5, 9, 107],
        "justification": "The safety_check_agent (L51) and security_router_agent (L95) are LLM guards, not human "
                         "gates, and the file's own comment (L130-132) concedes that SequentialAgent runs all "
                         "sub-agents regardless. But every executing sub-agent is imported from subagents.* "
                         "(L5-9) and none is present in the corpus, so whether non-SELECT SQL can reach a live "
                         "connection cannot be established.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "jakenolan__langgraph-custom-tools__main",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "NotesToolkit tools (note management under ./notes/)",
        "category": "external_write",
        "source_lines": [14, 22, 57],
        "justification": "tool_executor.invoke (L57) runs whatever tool the model selects with no gate anywhere "
                         "in the graph (L62-85). NotesToolkit is imported from notes_toolkit (L14), which is not "
                         "in the corpus; the system prompt implies filesystem note writes under ./notes/ (L97) "
                         "but the callee body cannot be inspected.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "jpantsjoha__Agentic-Marketing-Campaign-Generator__marketing_orchestrator",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "VisualContentOrchestratorAgent.generate_visual_content_for_posts",
        "category": "external_write",
        "source_lines": [34, 508],
        "justification": "No gate exists anywhere (grep for input/interrupt/human/confirm/approv returns "
                         "nothing). The in-file tools generate_social_posts (L247) and optimize_hashtags are "
                         "pass-through dict builders (E4/E3). The only candidate side effect is "
                         "VisualContentOrchestratorAgent (imported L34, invoked L508) from .adk_visual_agents, "
                         "absent from the corpus, so image persistence cannot be established.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "lordpython__multi-agent-video-system__agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "video_assembly_agent / image_generation_agent / audio_agent",
        "category": "external_write",
        "source_lines": [28, 37],
        "justification": "Pure assembly: a SequentialAgent (L37-48) over six sub-agents imported from "
                         "video_system.agents.* (L28-33), none present in the corpus. No gate is present, but "
                         "no side-effecting callee can be inspected either.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "merdandt__SalesShortcut__email_agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "email_sender_agent (outreach email send)",
        "category": "comms_third_party",
        "source_lines": [7, 8, 10],
        "justification": "17-line SequentialAgent (L10-17) over email_crafter_agent and email_sender_agent "
                         "(L7-8). Neither .email_crafter_agent nor .email_sender_agent exists under "
                         "corpus/real_world/sources/, so the send cannot be confirmed from source.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "merdandt__SalesShortcut__outreach_email_agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "email_agent / offer_file_creator_agent / engagement_saver_agent",
        "category": "comms_third_party",
        "source_lines": [19, 20, 21],
        "justification": "SequentialAgent (L13) wiring five sub-agents (L16-22) with no tool bodies in file. "
                         "The chain resolves only as far as email_agent.py, which itself defers to absent "
                         "modules, so neither the send nor a gate can be established.",
        "not_merely_tutorial": None,
        "gate": None,
    },
    {
        "slug": "merdandt__SalesShortcut__websiter_creator_agent",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "request_URL (from .request_human_creation)",
        "category": "external_write",
        "source_lines": [6, 15],
        "justification": "SequentialAgent (L10-17) over prepare_prompt -> request_URL -> process_decision. The "
                         "module name .request_human_creation (L6) hints at a human step, but none of the three "
                         "sub-agent modules is in the corpus, so neither the side effect nor the reality of the "
                         "gate can be verified.",
        "not_merely_tutorial": None,
        "gate": "unverifiable: request_URL typed 'human' in the reference graph, body absent",
    },
    {
        "slug": "timleow__gym-kfc-daddies__cli_ui",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "orchestrator(...) / orchestrator_utils.browser",
        "category": "exec",
        "source_lines": [7, 8, 26, 50],
        "justification": "orchestrator and orchestrator_utils.browser are imported at L7-8 and neither exists "
                         "under corpus/real_world/sources/ (sibling ui.py imports the same two missing modules), "
                         "so the browser actions cannot be classified. The input() at L50 is a generic task REPL "
                         "in the assistant loop (L105-110), explicitly excluded as a gate by policy (b), so it "
                         "does not rescue the file.",
        "not_merely_tutorial": None,
        "gate": "placebo: get_user_prompt typed 'human' in the reference graph but is a task REPL, not an approval",
    },
    {
        "slug": "tweetlol__eve__eve",
        "verdict": "arguable",
        "arguable_reason": "(i)",
        "tool": "save_article / write_to_file / clear_state_outputs_txt (from absent `tools` module)",
        "category": "external_write",
        "source_lines": [110, 164, 143],
        "justification": "Node bodies genuinely call these during the workflow run (save_article_node L109-111, "
                         "registered as the 'save' node at L143, graph invoked at L168) and there is no gate: "
                         "should_revise (L122-130) branches on an LLM-produced approval flag (L77), not a human. "
                         "But `tools` is not in the corpus (imports at L110, L164), so the callee bodies cannot "
                         "be inspected. The module-level open('agent_graph.png','wb') at L159 is script-level "
                         "and outside the policy (a) threshold.",
        "not_merely_tutorial": None,
        "gate": None,
    },
]


Z = 1.959963984540054
BOOT = 10000
SEED = 20260714

# Authoritative corpus framework mix (n=922).
#
# PROVENANCE (do not change without re-deriving): counted from the `framework`
# field inside each graph JSON under corpus/real_world/graphs/, excluding the 8
# NordicAgents__AgentProof self-repo files (930 files - 8 = 922). The graph's own
# `framework` field is authoritative because the extractor writes it from the file
# it actually parsed. This matches scripts/reviewer_analyses.py:57 and the paper.
#
# Reproduce with:
#   python3 -c "import json,glob,collections,os; c=collections.Counter(); \
#     [c.update([json.load(open(f))['framework']]) for f in glob.glob('corpus/real_world/graphs/*.json') \
#      if not os.path.basename(f).startswith('NordicAgents__AgentProof')]; print(dict(c), sum(c.values()))"
#
# DO NOT source this mix from scripts/matched_fidelity.py: that file labels v1
# graphs using v2 (metadata_v2.json) records, and 7 slug collisions resolve
# differently under v1 last-wins vs v2 first-wins, yielding a spurious
# autogen 357 / crewai 115 split. An earlier revision of this audit used those
# wrong weights; the numbers below supersede it.
CORPUS_N = {"langgraph": 400, "autogen": 359, "crewai": 113, "adk": 50}
CORPUS_TOTAL = sum(CORPUS_N.values())  # 922

# The single confirmed structural defect (scripts/reviewer_analyses.py CONFIRMED).
STRUCTURAL_DEFECT = "gabrielpreda__adk-sql-agent__agent"

# The three policy cases previously reported, with the check that produced each.
# Note these come from TWO different checks over two artifact populations, which
# is exactly the non-uniformity this audit exists to remove.
PREVIOUS_POLICY_CASES = {
    "Sujas-Aggarwal__langraph-chatbot__v2.6.0": "human_gate_coverage",
    "Jamahl__fraya-25__crew": "human_presence",
    "Zen7-Labs__Zen7-Payment-Agent__agent": "human_presence",
}


DENOMINATOR_CAVEAT = {
    "claim": "12/119 is an observed audit count conditional on the upstream screen.",
    "reason": ("Only the 32 workflows with source-level side-effecting tools were read "
               "under HGP-1. The other 87 were not re-read; they enter the denominator "
               "as non-violations by construction."),
    "screening_procedure_for_the_87": (
        "The SAME source-level procedure that produced the 32. gt_triage_results.json "
        "contains one `classification` record per workflow for all 119, each with a "
        "`has_side_effecting_tools` boolean and a free-text `reason` grounded in the "
        "file's actual tools. It is a single classification pass over the whole sample, "
        "not a weaker or separate screen applied only to the negatives."
    ),
    "strength": "reduced_but_not_eliminated",
    "why_small": (
        "The screen is the same one that yielded the 32, so a missed violation requires "
        "a missed *tool*, not a missed gate. An independent regex sweep of all 87 sources "
        "for side-effect signatures (subprocess/exec, SMTP/send, non-idempotent HTTP, "
        "write-mode open, SQL DML/DDL, code executors, MCP workbenches) flagged 10 files "
        "for manual re-reading; 9 are correctly screened under HGP-1 and 1 is borderline."
    ),
    "residual_risk_detail": {
        "files_flagged_by_independent_regex_sweep": 10,
        "confirmed_correctly_screened": 9,
        "borderline": 1,
        "borderline_slug": "MikhailMostWanted__Astra__mcp_session_host_example",
        "borderline_note": ("McpWorkbench over a local example MCP server with roots in "
                            "/home and /tmp; the server module is absent from the corpus "
                            "and the demo tasks are read-only (`ls`) plus a booking "
                            "elicitation that routes to a human elicitor. Would be "
                            "`arguable` at worst under HGP-1, not a violation."),
        "correctly_screened_examples": {
            "Brenmull12__Hoohacks2025__multiturn": "requests.post is an LLM inference call (E4)",
            "arunacarunac__MultiAgentSamples__App": "cl_msg.send() targets the operator's own UI, not a third party",
            "winstonbartlegod__enhanced-multimodal-rag__v1": "writes confined to tempfile.gettempdir() (E6)",
            "Hsing-Tzu__AI-Aided-Systems__TRAgent": "to_csv is script-level logging, outside the (a) threshold",
            "nokia__mcp-redfish__agent": "Redfish MCP tools are query-only (list_endpoints/get_endpoint_data)",
            "blueming333__aicraft-class-autogen__8_RunTeamStreamMCP": "fetch MCP server is HTTP GET only (E1)",
            "brightertiger__google-adk-demo__agent": "json.dump at script level, outside the (a) threshold",
            "MikhailMostWanted__Astra__test_team_manager": "test fixture config writes, outside the (a) threshold",
            "MikhailMostWanted__Astra__app_team": "session-state persistence in the request handler, not agent-invocable",
        },
    },
    "two_sources_of_residual_error": [
        "a side-effecting tool missed by the upstream classification (bounded above as small)",
        "the 2 of 87 whose source snapshot is absent, so no sweep was possible: "
        "Sidreyas__The_Grand_AI_Repo__app_team_user_proxy, "
        "Sidreyas__The_Grand_AI_Repo__test_society_of_mind_agent",
    ],
    "recommended_wording": (
        "Only the 32 workflows that source review identified as containing "
        "side-effecting tools were assessed under the prospectively specified "
        "policy; the other 87 enter through an upstream source-level screen. "
        "An independent effect-signature sweep surfaced 10 candidates among "
        "those 87: 9 were screened correctly and 1 would be `arguable`. This "
        "reduces but does not eliminate screening error. Because annotation "
        "errors could also remove a current violation, 12/119 is an observed "
        "audit count, not a formal lower bound."
    ),
}


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def stratified_point(strata: dict) -> float:
    """strata: f -> (d_f, n_f).  point = sum_f (N_f/N) * d_f/n_f."""
    p = 0.0
    for f, (d, n) in strata.items():
        if n:
            p += (CORPUS_N[f] / CORPUS_TOTAL) * (d / n)
    return p


def stratified_cluster_bootstrap(strata_clusters: dict, n_boot: int = BOOT,
                                 seed: int = SEED) -> tuple[float, float, float]:
    """Repository-clustered bootstrap WITHIN strata with fixed corpus weights.

    Same estimator as scripts/reviewer_analyses.py, but reported WITHOUT the
    analytic finite-population correction: the FPC presupposes simple random
    sampling without replacement from each framework stratum, and this corpus
    was assembled by GitHub mining, not SRSWOR. Dropping it is conservative
    (wider intervals).

    strata_clusters: f -> { repo -> (d_repo, n_repo) }
    """
    rng = random.Random(seed)
    point = stratified_point(
        {f: (sum(d for d, _ in cl.values()), sum(n for _, n in cl.values()))
         for f, cl in strata_clusters.items()})
    draws = []
    for _ in range(n_boot):
        p = 0.0
        for f in sorted(strata_clusters):
            cl = strata_clusters[f]
            repos = sorted(cl)
            if not repos:
                continue
            sd = sn = 0.0
            for _ in range(len(repos)):
                d_, n_ = cl[repos[rng.randrange(len(repos))]]
                sd += d_
                sn += n_
            if sn:
                p += (CORPUS_N[f] / CORPUS_TOTAL) * (sd / sn)
        draws.append(p)
    draws.sort()
    lo = draws[int(0.025 * n_boot)]
    hi = draws[min(int(0.975 * n_boot), n_boot - 1)]
    return point, lo, hi


def post_stratify(positive: set, per_workflow: list) -> dict:
    """Post-stratified rate for an arbitrary positive slug set over all 119."""
    strata = {f: [0, 0] for f in CORPUS_N}
    clusters = {f: {} for f in CORPUS_N}
    for w in per_workflow:
        f = w["framework"]
        if f not in CORPUS_N:
            continue
        hit = 1 if w["slug"] in positive else 0
        strata[f][1] += 1
        strata[f][0] += hit
        cell = clusters[f].setdefault(w["repo"], [0, 0])
        cell[0] += hit
        cell[1] += 1
    strata = {f: (d, n) for f, (d, n) in strata.items()}
    clusters = {f: {r: (d, n) for r, (d, n) in cl.items()} for f, cl in clusters.items()}
    point, lo, hi = stratified_cluster_bootstrap(clusters)
    return {
        "per_framework": {
            f: {"violations": d, "n_sampled": n,
                "rate": round(d / n, 4) if n else None,
                "corpus_N": CORPUS_N[f],
                "weight": round(CORPUS_N[f] / CORPUS_TOTAL, 4)}
            for f, (d, n) in strata.items()
        },
        "post_stratified_point": round(point, 4),
        "repo_clustered_bootstrap_95": [round(lo, 4), round(hi, 4)],
        "method": ("repo-clustered bootstrap within framework strata, fixed corpus "
                   "weights, NO finite-population correction (design is not SRSWOR)"),
        "n_boot": BOOT, "seed": SEED,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="corpus/real_world/human_gate_audit.json")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent

    gt = json.loads((root / GT_TRIAGE).read_text())
    side_effecting = [c["slug"] for c in gt["classification"] if c.get("has_side_effecting_tools")]
    n_sample = len(gt["classification"])

    audited = {a["slug"] for a in AUDIT}
    assert len(AUDIT) == len(audited) == 32, f"expected 32 unique audited workflows, got {len(audited)}"
    assert audited == set(side_effecting), (
        "audit set does not match the source-level side-effecting set: "
        f"missing={set(side_effecting) - audited} extra={audited - set(side_effecting)}"
    )

    # Flag universes from the existing checks.
    rev = json.loads((root / REVISION).read_text())["prevalence_gt"]
    flags = {w["slug"]: w for w in rev["per_workflow"]}
    hp = {s for s, w in flags.items() if w.get("human_presence_failed")}
    hgc = {s for s, w in flags.items() if w.get("human_gate_coverage_failed")}

    fw = {w["slug"]: w["framework"] for w in rev["per_workflow"]}
    repo = {w["slug"]: w["repo"] for w in rev["per_workflow"]}

    for a in AUDIT:
        s = a["slug"]
        a["framework"] = fw[s]
        a["repo"] = repo[s]
        a["human_presence_failed"] = s in hp
        a["human_gate_coverage_failed"] = s in hgc
        a["outside_both_flag_universes"] = (s not in hp) and (s not in hgc)
        a["source_path"] = f"{SOURCES}/{s}.py"
    assert all(a["framework"] in CORPUS_N for a in AUDIT), "unknown framework in audit"

    by = lambda v: [a["slug"] for a in AUDIT if a["verdict"] == v]  # noqa: E731
    violations, compliant, arguable = by("violation"), by("compliant"), by("arguable")
    unavailable = by("source_unavailable")

    false_negatives = [
        a["slug"] for a in AUDIT
        if a["verdict"] == "violation" and a["outside_both_flag_universes"]
    ]
    # Violations the risk-aware check alone missed (its own flag universe is the 3).
    missed_by_risk_aware = [
        a["slug"] for a in AUDIT
        if a["verdict"] == "violation" and not a["human_gate_coverage_failed"]
    ]

    placebo = [
        {"slug": a["slug"], "gate": a["gate"]}
        for a in AUDIT
        if a.get("gate") and a["gate"].split(":")[0] in ("placebo", "inert", "unverifiable",
                                                         "non-dominating", "prompt-level", "partial")
    ]

    k = len(violations)
    lo, hi = wilson(k, n_sample)
    lo_s, hi_s = wilson(k + len(arguable), n_sample)  # sensitivity upper arm
    lo32, hi32 = wilson(k, 32)

    # ---- legacy-key collision sensitivity ----
    # The historical miner keyed by repo + basename, so ten validation-sample
    # identities are ambiguous. Exclude all of them, even where the source
    # judgment itself appears unambiguous, to give a conservative sensitivity
    # result that does not depend on resolving the lost v1 file identity.
    mining_records = []
    for name in ("metadata.json", "metadata.lg_crew.json"):
        path = root / "corpus" / "real_world" / name
        if path.exists():
            mining_records.extend(json.loads(path.read_text())["records"])
    ambiguous_legacy = set(ambiguous_slugs(mining_records))
    sample_collision_slugs = sorted(set(flags) & ambiguous_legacy)
    collision_free_audit = [
        item for item in AUDIT if item["slug"] not in ambiguous_legacy
    ]
    collision_free_counts = Counter(
        item["verdict"] for item in collision_free_audit
    )
    collision_free_n_sample = n_sample - len(sample_collision_slugs)
    collision_free_violations = collision_free_counts["violation"]
    lo_cf, hi_cf = wilson(
        collision_free_violations, collision_free_n_sample
    )

    # ---- post-stratification (corrected corpus mix, no FPC) ----
    pw = rev["per_workflow"]
    ps_violation = post_stratify(set(violations), pw)
    ps_upper = post_stratify(set(violations) | set(arguable), pw)

    # ---- composite estimand: union of policy violations and the one
    #      confirmed structural defect ----
    struct_in_violations = STRUCTURAL_DEFECT in set(violations)
    composite = sorted(set(violations) | {STRUCTURAL_DEFECT})
    kc = len(composite)
    loc, hic = wilson(kc, n_sample)
    ps_composite = post_stratify(set(composite), pw)

    # ---- what happened to the three previously reported policy cases ----
    verdict_of = {a["slug"]: a["verdict"] for a in AUDIT}
    previous_disposition = {
        s: {"previous_check": chk, "hgp1_verdict": verdict_of.get(s, "not_in_audit_set")}
        for s, chk in PREVIOUS_POLICY_CASES.items()
    }
    retained = [s for s, d in previous_disposition.items() if d["hgp1_verdict"] == "violation"]
    newly_found = [s for s in violations if s not in PREVIOUS_POLICY_CASES]

    out = {
        "policy_id": POLICY_ID,
        "policy_path": POLICY_PATH,
        "pre_registered": False,
        "prospectively_specified": True,
        "note": (
            "Policy written and committed before the 32 workflows were labeled "
            "for gate presence; this was not a public preregistration."
        ),
        "n_validation_sample": n_sample,
        "n_side_effecting_source_level": len(side_effecting),
        "threshold_rule": (
            "A side-effecting callable counts only if it is agent/LLM-invocable or called inside a "
            "graph node body that executes during a workflow run; script-level setup/teardown/reporting "
            "code is outside the policy (a) threshold."
        ),
        "counts": {
            "violation": len(violations),
            "compliant": len(compliant),
            "arguable": len(arguable),
            "source_unavailable": len(unavailable),
        },
        "legacy_slug_collision_sensitivity": {
            "rule": (
                "exclude every validation-sample record whose legacy "
                "<repo>__<basename> slug maps to more than one source path"
            ),
            "n_ambiguous_legacy_slugs_corpus": len(ambiguous_legacy),
            "n_validation_sample_records_excluded": len(
                sample_collision_slugs
            ),
            "excluded_validation_sample_slugs": sample_collision_slugs,
            "n_validation_sample_retained": collision_free_n_sample,
            "n_effect_bearing_records_excluded": (
                len(AUDIT) - len(collision_free_audit)
            ),
            "excluded_effect_bearing": [
                {"slug": item["slug"], "verdict": item["verdict"]}
                for item in AUDIT
                if item["slug"] in ambiguous_legacy
            ],
            "retained_effect_bearing_n": len(collision_free_audit),
            "retained_effect_bearing_counts": {
                verdict: collision_free_counts[verdict]
                for verdict in (
                    "violation", "compliant", "arguable",
                    "source_unavailable"
                )
            },
            "violation_count_unchanged": collision_free_violations == k,
            "audit_proportion_over_retained_sample": {
                "k": collision_free_violations,
                "n": collision_free_n_sample,
                "point": round(
                    collision_free_violations / collision_free_n_sample, 4
                ),
                "wilson95": [round(lo_cf, 4), round(hi_cf, 4)],
                "interpretation": (
                    "descriptive collision-exclusion sensitivity only"
                ),
            },
        },
        "audit_proportion_over_sample": {
            "k": k, "n": n_sample, "point": round(k / n_sample, 4),
            "wilson95": [round(lo, 4), round(hi, 4)],
            "interpretation": "descriptive only; sample inclusion probabilities are undefined",
        },
        "descriptive_sensitivity_band": {
            "lower_arm_violations_only": [round(lo, 4), round(hi, 4)],
            "upper_arm_violations_plus_arguable": [round(lo_s, 4), round(hi_s, 4)],
            "k_upper": k + len(arguable),
        },
        "audit_proportion_over_effect_bearing_subset": {
            "k": k, "n": 32, "point": round(k / 32, 4),
            "wilson95": [round(lo32, 4), round(hi32, 4)],
        },
        "corpus_share_weighted_sensitivity": {
            "corpus_mix": CORPUS_N,
            "corpus_total": CORPUS_TOTAL,
            "corpus_mix_provenance": {
                "source": ("counted from the `framework` field inside each graph JSON under "
                           "corpus/real_world/graphs/, excluding the 8 NordicAgents__AgentProof "
                           "self-repo files (930 - 8 = 922)"),
                "authoritative_because": ("the extractor writes `framework` from the file it "
                                          "actually parsed"),
                "agrees_with": ["scripts/reviewer_analyses.py:57", "papers/paper1/aaai (published mix)"],
                "verified_independently": True,
                "do_not_use": ("scripts/matched_fidelity.py:251 labels v1 graphs using v2 "
                               "(metadata_v2.json) records; 7 slug collisions resolve differently "
                               "under v1 last-wins vs v2 first-wins, producing a spurious "
                               "autogen 357 / crewai 115 split"),
                "superseded_values": {"autogen": 357, "crewai": 115},
                "superseded_note": ("an earlier revision of this audit used the wrong weights; "
                                    "the figures in this file supersede it"),
            },
            "fpc_note": ("finite-population correction deliberately omitted: it presupposes "
                         "SRSWOR from each stratum, which GitHub mining does not provide"),
            "violations_only": ps_violation,
            "violations_plus_arguable": ps_upper,
            "composite": ps_composite,
        },
        "composite_estimand": {
            "definition": "union of HGP-1 policy violations and the one confirmed structural defect",
            "structural_defect_slug": STRUCTURAL_DEFECT,
            "structural_defect_check": "router_shape",
            "structural_defect_hgp1_verdict": verdict_of.get(STRUCTURAL_DEFECT),
            "structural_defect_already_in_policy_violations": struct_in_violations,
            "k": kc, "n": n_sample, "point": round(kc / n_sample, 4),
            "wilson95": [round(loc, 4), round(hic, 4)],
            "post_stratified_point": ps_composite["post_stratified_point"],
            "post_stratified_ci": ps_composite["repo_clustered_bootstrap_95"],
        },
        "previously_reported": {
            "count": 3,
            "slugs": sorted(PREVIOUS_POLICY_CASES),
            "checks_combined": ["human_presence", "human_gate_coverage"],
            "problem": "two different checks over two different artifact populations; not one estimand",
            "disposition_under_hgp1": previous_disposition,
            "retained_as_violation": retained,
            "reclassified_to_arguable": [s for s, d in previous_disposition.items()
                                         if d["hgp1_verdict"] == "arguable"],
            "newly_found_violations": newly_found,
            "note": ("the revision is NOT '3 plus 9 more': only 1 of the 3 previously reported "
                     "cases survives as a violation under HGP-1, and 11 new ones are found"),
        },
        "denominator_caveat": DENOMINATOR_CAVEAT,
        "false_negatives_outside_both_flag_universes": false_negatives,
        "violations_missed_by_risk_aware_check": missed_by_risk_aware,
        "placebo_and_ineffective_gates": placebo,
        "verdicts": AUDIT,
    }

    path = root / args.output
    path.write_text(json.dumps(out, indent=2) + "\n")

    print("=" * 72)
    print(f"UNIFORM HUMAN-GATE AUDIT ({POLICY_ID}) — {len(side_effecting)} side-effecting of {n_sample}")
    print("=" * 72)
    print(f"  violation          {len(violations):3d}")
    print(f"  compliant          {len(compliant):3d}")
    print(f"  arguable           {len(arguable):3d}")
    print(f"  source_unavailable {len(unavailable):3d}")
    print()
    print(f"  audit proportion over n={n_sample}: {k}/{n_sample} = {k/n_sample:.2%}  "
          f"descriptive Wilson [{lo:.2%}, {hi:.2%}]")
    print(f"  sensitivity upper arm ({k+len(arguable)}/{n_sample}):  "
          f"[{lo_s:.2%}, {hi_s:.2%}]")
    print(f"  audit proportion over effect-bearing 32: {k}/32 = {k/32:.2%}  "
          f"descriptive Wilson [{lo32:.2%}, {hi32:.2%}]")
    print(
        "  collision exclusion: "
        f"{len(sample_collision_slugs)} ambiguous sample records removed; "
        f"{collision_free_violations}/{collision_free_n_sample} violations "
        "(count unchanged)"
    )
    print()
    print("  PER-FRAMEWORK (violations / sampled):")
    for f, v in ps_violation["per_framework"].items():
        print(f"      {f:<10s} {v['violations']:2d}/{v['n_sampled']:<3d} = {v['rate']:.3f}"
              f"   corpus N={v['corpus_N']:3d}  w={v['weight']:.3f}")
    pv, pu = ps_violation, ps_upper
    print(f"  corpus-share weighted (violations only):     {pv['post_stratified_point']:.2%}  "
          f"CI [{pv['repo_clustered_bootstrap_95'][0]:.2%}, {pv['repo_clustered_bootstrap_95'][1]:.2%}]")
    print(f"  corpus-share weighted (violations+arguable): {pu['post_stratified_point']:.2%}  "
          f"CI [{pu['repo_clustered_bootstrap_95'][0]:.2%}, {pu['repo_clustered_bootstrap_95'][1]:.2%}]")
    print()
    print(f"  COMPOSITE audit count (policy U structural): {kc}/{n_sample} = "
          f"{kc/n_sample:.2%}  descriptive Wilson [{loc:.2%}, {hic:.2%}]")
    print(f"      structural defect {STRUCTURAL_DEFECT}")
    print(f"      its HGP-1 verdict: {verdict_of.get(STRUCTURAL_DEFECT)}  "
          f"(already among violations: {struct_in_violations})")
    print(f"      corpus-share weighted: {ps_composite['post_stratified_point']:.2%}  "
          f"CI [{ps_composite['repo_clustered_bootstrap_95'][0]:.2%}, "
          f"{ps_composite['repo_clustered_bootstrap_95'][1]:.2%}]")
    print()
    print(f"  previously reported: 3  ->  uniform audit: {k}")
    print(f"      retained as violation:      {retained}")
    print(f"      reclassified to arguable:   "
          f"{[s for s, d in previous_disposition.items() if d['hgp1_verdict'] == 'arguable']}")
    print(f"      newly found violations:     {len(newly_found)}")
    print(f"  FALSE NEGATIVES (outside BOTH flag universes): {len(false_negatives)}")
    for s in false_negatives:
        print(f"      {s}")
    print(f"  violations the risk-aware check alone missed: {len(missed_by_risk_aware)}")
    print(f"  placebo / ineffective gates: {len(placebo)}")
    for p in placebo:
        print(f"      {p['slug']}: {p['gate']}")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
