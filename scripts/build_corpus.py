#!/usr/bin/env python3
"""Build the curated agent workflow corpus from illustrative definitions.

Each workflow models a pattern commonly found in open-source agent projects.
These are author-constructed examples for benchmarking and illustration,
not mined from real repositories. Graphs are serialized as JSON to
corpus/curated/.

Usage:
    python scripts/build_corpus.py
"""

from __future__ import annotations

import json
from pathlib import Path

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    graph_to_dict,
)


def _g(name: str, framework: str, nodes: list[GraphNode], edges: list[GraphEdge],
        entry: str = "__start__", exits: tuple[str, ...] = ("__end__",)) -> AgentGraph:
    return AgentGraph(name=name, framework=framework, nodes=tuple(nodes),
                      edges=tuple(edges), entry_id=entry, exit_ids=exits)


# ---------------------------------------------------------------------------
# LangGraph workflows
# ---------------------------------------------------------------------------

def lg_customer_support() -> AgentGraph:
    """LangGraph: Customer support with sentiment routing and escalation."""
    return _g("lg_customer_support", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("classify", NodeKind.LLM, label="classify_intent"),
        GraphNode("router", NodeKind.ROUTER, label="intent_router"),
        GraphNode("faq_lookup", NodeKind.TOOL, label="faq_lookup", tools=("search_faq",)),
        GraphNode("order_status", NodeKind.TOOL, label="order_status", tools=("query_orders_db",)),
        GraphNode("agent", NodeKind.LLM, label="support_agent"),
        GraphNode("escalate", NodeKind.HUMAN, label="human_escalation"),
        GraphNode("respond", NodeKind.LLM, label="generate_response"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "classify"),
        GraphEdge("classify", "router"),
        GraphEdge("router", "faq_lookup", EdgeKind.CONDITIONAL, "intent=faq"),
        GraphEdge("router", "order_status", EdgeKind.CONDITIONAL, "intent=order"),
        GraphEdge("router", "escalate", EdgeKind.CONDITIONAL, "intent=complaint"),
        GraphEdge("faq_lookup", "respond"),
        GraphEdge("order_status", "respond"),
        GraphEdge("escalate", "respond"),
        GraphEdge("agent", "respond"),
        GraphEdge("respond", "__end__"),
    ])


def lg_rag_pipeline() -> AgentGraph:
    """LangGraph: RAG pipeline with query rewriting and grading."""
    return _g("lg_rag_pipeline", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("rewrite", NodeKind.LLM, label="query_rewriter"),
        GraphNode("retrieve", NodeKind.TOOL, label="retriever", tools=("vector_search",)),
        GraphNode("grade", NodeKind.LLM, label="relevance_grader"),
        GraphNode("grade_router", NodeKind.ROUTER, label="grade_decision"),
        GraphNode("generate", NodeKind.LLM, label="answer_generator"),
        GraphNode("web_search", NodeKind.TOOL, label="web_search", tools=("tavily_search",)),
        GraphNode("hallucination_check", NodeKind.LLM, label="hallucination_grader"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "rewrite"),
        GraphEdge("rewrite", "retrieve"),
        GraphEdge("retrieve", "grade"),
        GraphEdge("grade", "grade_router"),
        GraphEdge("grade_router", "generate", EdgeKind.CONDITIONAL, "relevant"),
        GraphEdge("grade_router", "web_search", EdgeKind.CONDITIONAL, "not_relevant"),
        GraphEdge("web_search", "generate"),
        GraphEdge("generate", "hallucination_check"),
        GraphEdge("hallucination_check", "__end__"),
    ])


def lg_multi_agent_research() -> AgentGraph:
    """LangGraph: Multi-agent research with planner, researcher, writer."""
    return _g("lg_multi_agent_research", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("planner", NodeKind.LLM, label="research_planner"),
        GraphNode("researcher", NodeKind.LLM, label="researcher"),
        GraphNode("search", NodeKind.TOOL, label="web_search", tools=("tavily_search", "arxiv_search")),
        GraphNode("writer", NodeKind.LLM, label="writer"),
        GraphNode("reviewer", NodeKind.LLM, label="reviewer"),
        GraphNode("review_router", NodeKind.ROUTER, label="review_decision"),
        GraphNode("human_review", NodeKind.HUMAN, label="human_editor"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "planner"),
        GraphEdge("planner", "researcher"),
        GraphEdge("researcher", "search"),
        GraphEdge("search", "writer"),
        GraphEdge("writer", "reviewer"),
        GraphEdge("reviewer", "review_router"),
        GraphEdge("review_router", "researcher", EdgeKind.CONDITIONAL, "needs_revision"),
        GraphEdge("review_router", "human_review", EdgeKind.CONDITIONAL, "needs_human"),
        GraphEdge("review_router", "__end__", EdgeKind.CONDITIONAL, "approved"),
        GraphEdge("human_review", "__end__"),
    ])


def lg_code_assistant() -> AgentGraph:
    """LangGraph: Code generation assistant with tests and debugging loop."""
    return _g("lg_code_assistant", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("understand", NodeKind.LLM, label="understand_task"),
        GraphNode("generate", NodeKind.LLM, label="generate_code"),
        GraphNode("run_tests", NodeKind.TOOL, label="test_runner", tools=("execute_code", "run_pytest")),
        GraphNode("test_router", NodeKind.ROUTER, label="test_result_check"),
        GraphNode("debug", NodeKind.LLM, label="debugger"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "understand"),
        GraphEdge("understand", "generate"),
        GraphEdge("generate", "run_tests"),
        GraphEdge("run_tests", "test_router"),
        GraphEdge("test_router", "__end__", EdgeKind.CONDITIONAL, "all_pass"),
        GraphEdge("test_router", "debug", EdgeKind.CONDITIONAL, "failures"),
        GraphEdge("debug", "generate"),
    ])


def lg_email_triage() -> AgentGraph:
    """LangGraph: Email triage — DEFECT: dead-end node (draft_response has no outgoing edge)."""
    return _g("lg_email_triage", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("classify", NodeKind.LLM, label="email_classifier"),
        GraphNode("router", NodeKind.ROUTER, label="priority_router"),
        GraphNode("urgent_handler", NodeKind.LLM, label="urgent_handler"),
        GraphNode("normal_handler", NodeKind.LLM, label="normal_handler"),
        GraphNode("draft_response", NodeKind.LLM, label="draft_response"),  # Dead-end!
        GraphNode("send", NodeKind.TOOL, label="send_email", tools=("smtp_send",)),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "classify"),
        GraphEdge("classify", "router"),
        GraphEdge("router", "urgent_handler", EdgeKind.CONDITIONAL, "urgent"),
        GraphEdge("router", "normal_handler", EdgeKind.CONDITIONAL, "normal"),
        GraphEdge("urgent_handler", "send"),
        GraphEdge("normal_handler", "draft_response"),
        # Missing: GraphEdge("draft_response", "send"),  <-- DEFECT
        GraphEdge("send", "__end__"),
    ])


# ---------------------------------------------------------------------------
# CrewAI workflows
# ---------------------------------------------------------------------------

def crewai_content_pipeline() -> AgentGraph:
    """CrewAI: Content creation pipeline (research, write, edit, publish)."""
    return _g("crewai_content_pipeline", "crewai", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("research", NodeKind.TOOL, label="researcher", tools=("web_search", "scraper")),
        GraphNode("write", NodeKind.LLM, label="writer"),
        GraphNode("edit", NodeKind.LLM, label="editor"),
        GraphNode("seo", NodeKind.TOOL, label="seo_optimizer", tools=("keyword_analyzer",)),
        GraphNode("publish", NodeKind.TOOL, label="publisher", tools=("cms_api",)),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "research"),
        GraphEdge("research", "write"),
        GraphEdge("write", "edit"),
        GraphEdge("edit", "seo"),
        GraphEdge("seo", "publish"),
        GraphEdge("publish", "__end__"),
    ])


def crewai_hiring_pipeline() -> AgentGraph:
    """CrewAI: Hiring pipeline with screening and interviews."""
    return _g("crewai_hiring_pipeline", "crewai", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("screen", NodeKind.TOOL, label="resume_screener", tools=("parse_resume",)),
        GraphNode("score", NodeKind.LLM, label="candidate_scorer"),
        GraphNode("interview_prep", NodeKind.LLM, label="interview_preparer"),
        GraphNode("schedule", NodeKind.TOOL, label="scheduler", tools=("calendar_api",)),
        GraphNode("review", NodeKind.HUMAN, label="hiring_manager_review"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "screen"),
        GraphEdge("screen", "score"),
        GraphEdge("score", "interview_prep"),
        GraphEdge("interview_prep", "schedule"),
        GraphEdge("schedule", "review"),
        GraphEdge("review", "__end__"),
    ])


def crewai_data_analysis() -> AgentGraph:
    """CrewAI: Hierarchical data analysis — DEFECT: TOOL node missing tool declaration."""
    return _g("crewai_data_analysis", "crewai", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("manager", NodeKind.ROUTER, label="analysis_manager"),
        GraphNode("collector", NodeKind.TOOL, label="data_collector", tools=("sql_query", "api_fetch")),
        GraphNode("cleaner", NodeKind.TOOL, label="data_cleaner", tools=()),  # DEFECT: no tools
        GraphNode("analyst", NodeKind.LLM, label="data_analyst"),
        GraphNode("visualizer", NodeKind.TOOL, label="chart_generator", tools=("matplotlib_render",)),
        GraphNode("reporter", NodeKind.LLM, label="report_writer"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "manager"),
        GraphEdge("manager", "collector", EdgeKind.CONDITIONAL, "collect"),
        GraphEdge("manager", "cleaner", EdgeKind.CONDITIONAL, "clean"),
        GraphEdge("manager", "analyst", EdgeKind.CONDITIONAL, "analyze"),
        GraphEdge("manager", "visualizer", EdgeKind.CONDITIONAL, "visualize"),
        GraphEdge("collector", "reporter"),
        GraphEdge("cleaner", "reporter"),
        GraphEdge("analyst", "reporter"),
        GraphEdge("visualizer", "reporter"),
        GraphEdge("reporter", "__end__"),
    ])


# ---------------------------------------------------------------------------
# AutoGen workflows
# ---------------------------------------------------------------------------

def autogen_software_team() -> AgentGraph:
    """AutoGen: Software development team (PM, dev, tester, reviewer)."""
    return _g("autogen_software_team", "autogen", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("pm", NodeKind.LLM, label="product_manager"),
        GraphNode("developer", NodeKind.LLM, label="developer"),
        GraphNode("tester", NodeKind.LLM, label="qa_tester"),
        GraphNode("reviewer", NodeKind.LLM, label="code_reviewer"),
        GraphNode("user", NodeKind.HUMAN, label="user_proxy"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "pm"),
        GraphEdge("pm", "developer"),
        GraphEdge("developer", "tester"),
        GraphEdge("tester", "reviewer"),
        GraphEdge("reviewer", "developer", EdgeKind.CONDITIONAL, "needs_fix"),
        GraphEdge("reviewer", "user", EdgeKind.CONDITIONAL, "approved"),
        GraphEdge("user", "__end__"),
    ])


def autogen_debate() -> AgentGraph:
    """AutoGen: Debate topology with moderator — DEFECT: router with non-conditional edges."""
    return _g("autogen_debate", "autogen", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("moderator", NodeKind.ROUTER, label="debate_moderator"),
        GraphNode("pro", NodeKind.LLM, label="pro_debater"),
        GraphNode("con", NodeKind.LLM, label="con_debater"),
        GraphNode("judge", NodeKind.LLM, label="judge"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "moderator"),
        GraphEdge("moderator", "pro", EdgeKind.DIRECT),  # DEFECT: should be CONDITIONAL
        GraphEdge("moderator", "con", EdgeKind.DIRECT),  # DEFECT: should be CONDITIONAL
        GraphEdge("pro", "moderator"),
        GraphEdge("con", "moderator"),
        GraphEdge("moderator", "judge", EdgeKind.CONDITIONAL, "debate_complete"),
        GraphEdge("judge", "__end__"),
    ])


def autogen_investment_team() -> AgentGraph:
    """AutoGen: Investment analysis team (analyst, risk, compliance, approver)."""
    return _g("autogen_investment_team", "autogen", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("analyst", NodeKind.LLM, label="financial_analyst"),
        GraphNode("risk", NodeKind.LLM, label="risk_assessor"),
        GraphNode("compliance", NodeKind.LLM, label="compliance_officer"),
        GraphNode("market_data", NodeKind.TOOL, label="market_data", tools=("yahoo_finance", "bloomberg_api")),
        GraphNode("approver", NodeKind.HUMAN, label="investment_committee"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "analyst"),
        GraphEdge("analyst", "market_data"),
        GraphEdge("market_data", "risk"),
        GraphEdge("risk", "compliance"),
        GraphEdge("compliance", "approver"),
        GraphEdge("approver", "__end__"),
    ])


def autogen_round_robin_brainstorm() -> AgentGraph:
    """AutoGen: Round-robin brainstorming — DEFECT: unreachable exit."""
    return _g("autogen_round_robin_brainstorm", "autogen", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("idea_gen", NodeKind.LLM, label="idea_generator"),
        GraphNode("critic", NodeKind.LLM, label="critic"),
        GraphNode("refiner", NodeKind.LLM, label="refiner"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "idea_gen"),
        GraphEdge("idea_gen", "critic"),
        GraphEdge("critic", "refiner"),
        GraphEdge("refiner", "idea_gen"),  # Loop — no exit path! DEFECT
    ])


# ---------------------------------------------------------------------------
# Google ADK workflows
# ---------------------------------------------------------------------------

def adk_document_processing() -> AgentGraph:
    """ADK: Document processing pipeline (OCR, extract, classify, store)."""
    return _g("adk_document_processing", "adk", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("pipeline", NodeKind.SUBGRAPH, label="doc_pipeline"),
        GraphNode("ocr", NodeKind.TOOL, label="ocr_engine", tools=("tesseract", "cloud_vision")),
        GraphNode("extract", NodeKind.LLM, label="entity_extractor"),
        GraphNode("classify", NodeKind.LLM, label="document_classifier"),
        GraphNode("store", NodeKind.TOOL, label="database_writer", tools=("postgres_insert",)),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "pipeline"),
        GraphEdge("pipeline", "ocr"),
        GraphEdge("ocr", "extract"),
        GraphEdge("extract", "classify"),
        GraphEdge("classify", "store"),
        GraphEdge("store", "__end__"),
    ])


def adk_compliance_review() -> AgentGraph:
    """ADK: Compliance review with parallel checks and loop for remediation."""
    return _g("adk_compliance_review", "adk", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("collector", NodeKind.TOOL, label="evidence_collector", tools=("s3_fetch", "api_call")),
        GraphNode("parallel_check", NodeKind.SUBGRAPH, label="parallel_checks"),
        GraphNode("legal_check", NodeKind.LLM, label="legal_compliance"),
        GraphNode("financial_check", NodeKind.LLM, label="financial_compliance"),
        GraphNode("security_check", NodeKind.TOOL, label="security_scan", tools=("vulnerability_scanner",)),
        GraphNode("aggregator", NodeKind.LLM, label="findings_aggregator"),
        GraphNode("remediation_loop", NodeKind.SUBGRAPH, label="remediation"),
        GraphNode("fix", NodeKind.LLM, label="remediation_agent"),
        GraphNode("recheck", NodeKind.TOOL, label="recheck", tools=("compliance_validator",)),
        GraphNode("signoff", NodeKind.HUMAN, label="compliance_officer_signoff"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "collector"),
        GraphEdge("collector", "parallel_check"),
        GraphEdge("parallel_check", "legal_check", EdgeKind.PARALLEL),
        GraphEdge("parallel_check", "financial_check", EdgeKind.PARALLEL),
        GraphEdge("parallel_check", "security_check", EdgeKind.PARALLEL),
        GraphEdge("legal_check", "aggregator"),
        GraphEdge("financial_check", "aggregator"),
        GraphEdge("security_check", "aggregator"),
        GraphEdge("aggregator", "remediation_loop"),
        GraphEdge("remediation_loop", "fix"),
        GraphEdge("fix", "recheck"),
        GraphEdge("recheck", "fix", EdgeKind.LOOP),
        GraphEdge("recheck", "signoff"),
        GraphEdge("signoff", "__end__"),
    ])


def adk_customer_onboarding() -> AgentGraph:
    """ADK: Customer onboarding — DEFECT: missing human gate for KYC."""
    return _g("adk_customer_onboarding", "adk", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("kyc_check", NodeKind.TOOL, label="kyc_verification", tools=("id_verify_api",)),
        GraphNode("credit_check", NodeKind.TOOL, label="credit_score", tools=("credit_bureau_api",)),
        GraphNode("risk_assess", NodeKind.LLM, label="risk_assessment"),
        GraphNode("account_create", NodeKind.TOOL, label="create_account", tools=("core_banking_api",)),
        GraphNode("welcome", NodeKind.LLM, label="welcome_email_generator"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "kyc_check"),
        GraphEdge("kyc_check", "credit_check"),
        GraphEdge("credit_check", "risk_assess"),
        GraphEdge("risk_assess", "account_create"),  # No human approval! DEFECT
        GraphEdge("account_create", "welcome"),
        GraphEdge("welcome", "__end__"),
    ])


def adk_incident_response() -> AgentGraph:
    """ADK: Incident response with triage, parallel investigation, and resolution."""
    return _g("adk_incident_response", "adk", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("triage", NodeKind.LLM, label="incident_triage"),
        GraphNode("severity_router", NodeKind.ROUTER, label="severity_router"),
        GraphNode("parallel_investigation", NodeKind.SUBGRAPH, label="investigation"),
        GraphNode("log_analysis", NodeKind.TOOL, label="log_analyzer", tools=("elk_query", "splunk_search")),
        GraphNode("metric_check", NodeKind.TOOL, label="metric_checker", tools=("prometheus_query",)),
        GraphNode("trace_analysis", NodeKind.TOOL, label="trace_analyzer", tools=("jaeger_query",)),
        GraphNode("diagnose", NodeKind.LLM, label="root_cause_analysis"),
        GraphNode("auto_remediate", NodeKind.TOOL, label="auto_fix", tools=("kubectl_restart", "config_rollback")),
        GraphNode("human_escalation", NodeKind.HUMAN, label="oncall_engineer"),
        GraphNode("postmortem", NodeKind.LLM, label="postmortem_generator"),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "triage"),
        GraphEdge("triage", "severity_router"),
        GraphEdge("severity_router", "parallel_investigation", EdgeKind.CONDITIONAL, "sev1_or_sev2"),
        GraphEdge("severity_router", "log_analysis", EdgeKind.CONDITIONAL, "sev3"),
        GraphEdge("parallel_investigation", "log_analysis", EdgeKind.PARALLEL),
        GraphEdge("parallel_investigation", "metric_check", EdgeKind.PARALLEL),
        GraphEdge("parallel_investigation", "trace_analysis", EdgeKind.PARALLEL),
        GraphEdge("log_analysis", "diagnose"),
        GraphEdge("metric_check", "diagnose"),
        GraphEdge("trace_analysis", "diagnose"),
        GraphEdge("diagnose", "auto_remediate"),
        GraphEdge("auto_remediate", "postmortem"),
        GraphEdge("human_escalation", "postmortem"),
        GraphEdge("postmortem", "__end__"),
    ])


# ---------------------------------------------------------------------------
# Mixed / cross-framework patterns
# ---------------------------------------------------------------------------

def lg_financial_advisor() -> AgentGraph:
    """LangGraph: Financial advisor with portfolio analysis and compliance."""
    return _g("lg_financial_advisor", "langgraph", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("intake", NodeKind.LLM, label="client_intake"),
        GraphNode("portfolio_fetch", NodeKind.TOOL, label="portfolio_fetch", tools=("brokerage_api",)),
        GraphNode("market_analysis", NodeKind.TOOL, label="market_analysis", tools=("market_data_api",)),
        GraphNode("risk_model", NodeKind.LLM, label="risk_modeler"),
        GraphNode("recommendation", NodeKind.LLM, label="recommendation_engine"),
        GraphNode("compliance_check", NodeKind.LLM, label="compliance_checker"),
        GraphNode("compliance_router", NodeKind.ROUTER, label="compliance_decision"),
        GraphNode("advisor_review", NodeKind.HUMAN, label="human_advisor"),
        GraphNode("execute_trades", NodeKind.TOOL, label="trade_executor", tools=("trading_api",)),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "intake"),
        GraphEdge("intake", "portfolio_fetch"),
        GraphEdge("portfolio_fetch", "market_analysis"),
        GraphEdge("market_analysis", "risk_model"),
        GraphEdge("risk_model", "recommendation"),
        GraphEdge("recommendation", "compliance_check"),
        GraphEdge("compliance_check", "compliance_router"),
        GraphEdge("compliance_router", "advisor_review", EdgeKind.CONDITIONAL, "needs_review"),
        GraphEdge("compliance_router", "execute_trades", EdgeKind.CONDITIONAL, "auto_approved"),
        GraphEdge("advisor_review", "execute_trades"),
        GraphEdge("execute_trades", "__end__"),
    ])


def crewai_marketing_campaign() -> AgentGraph:
    """CrewAI: Marketing campaign — DEFECT: unreachable exit (publish has no edge to exit)."""
    return _g("crewai_marketing_campaign", "crewai", [
        GraphNode("__start__", NodeKind.ENTRY),
        GraphNode("research", NodeKind.TOOL, label="market_researcher", tools=("survey_tool", "competitor_analysis")),
        GraphNode("strategist", NodeKind.LLM, label="campaign_strategist"),
        GraphNode("copywriter", NodeKind.LLM, label="copywriter"),
        GraphNode("designer", NodeKind.TOOL, label="designer", tools=("dall_e", "canva_api")),
        GraphNode("publish", NodeKind.TOOL, label="publisher", tools=("social_media_api",)),
        GraphNode("analytics", NodeKind.TOOL, label="analytics", tools=("google_analytics",)),
        GraphNode("__end__", NodeKind.EXIT),
    ], [
        GraphEdge("__start__", "research"),
        GraphEdge("research", "strategist"),
        GraphEdge("strategist", "copywriter"),
        GraphEdge("copywriter", "designer"),
        GraphEdge("designer", "publish"),
        # Missing: GraphEdge("publish", "analytics"),  <-- DEFECT: analytics unreachable
        # Missing: GraphEdge("analytics", "__end__"),  <-- DEFECT: no exit path
        GraphEdge("publish", "__end__"),
        # analytics is a dead-end with no incoming edges from the main flow
    ])


# ---------------------------------------------------------------------------
# Corpus builder
# ---------------------------------------------------------------------------

ALL_WORKFLOWS = [
    lg_customer_support,
    lg_rag_pipeline,
    lg_multi_agent_research,
    lg_code_assistant,
    lg_email_triage,
    lg_financial_advisor,
    crewai_content_pipeline,
    crewai_hiring_pipeline,
    crewai_data_analysis,
    crewai_marketing_campaign,
    autogen_software_team,
    autogen_debate,
    autogen_investment_team,
    autogen_round_robin_brainstorm,
    adk_document_processing,
    adk_compliance_review,
    adk_customer_onboarding,
    adk_incident_response,
]


def main():
    output_dir = Path("corpus/curated")
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = []
    for wf_fn in ALL_WORKFLOWS:
        graph = wf_fn()
        data = graph_to_dict(graph)
        path = output_dir / f"{graph.name}.json"
        path.write_text(json.dumps(data, indent=2))
        print(f"  {graph.name}: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        sources.append({
            "name": graph.name,
            "framework": graph.framework,
            "description": wf_fn.__doc__.strip() if wf_fn.__doc__ else "",
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        })

    sources_path = Path("corpus/sources.json")
    sources_path.write_text(json.dumps(sources, indent=2))
    print(f"\nBuilt {len(sources)} workflows → {output_dir}/")
    print(f"Sources written to {sources_path}")


if __name__ == "__main__":
    main()
