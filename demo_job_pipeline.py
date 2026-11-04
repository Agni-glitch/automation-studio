"""End-to-end demo: Fetch jobs -> Python clean-up -> AI CV analysis -> If -> Email.

Offline (default): the job API and the LLM are served by an in-process fake, and the
email is a dry run. No keys, no network.

    python demo_job_pipeline.py

Live: real Remotive job API and real Anthropic call, using credentials stored in the
encrypted database (see `python main.py cred set --help`). Email stays a dry run unless --send.

    python main.py cred set anthropic api_key
    python main.py cred set smtp host port username password      # only for --send
    python demo_job_pipeline.py --live
    python demo_job_pipeline.py --live --send --to you@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from engine import ExecutionStatus, InMemoryCredentialProvider, WorkflowEngine
from main import print_event

WORKFLOW = Path(__file__).parent / "examples" / "job_pipeline.json"

FAKE_JOBS = [
    {"title": "Senior Python Backend Engineer", "company_name": "Ledgerly", "url": "https://example.com/jobs/1",
     "candidate_required_location": "Worldwide",
     "description": "<p>Build <b>FastAPI</b> services on AWS. PostgreSQL, Docker, async Python.</p>"},
    {"title": "Data Engineer", "company_name": "Streamwise", "url": "https://example.com/jobs/2",
     "candidate_required_location": "Europe",
     "description": "<ul><li>Airflow &amp; Spark pipelines</li><li>Python, SQL</li></ul>"},
    {"title": "iOS Developer", "company_name": "Appfield", "url": "https://example.com/jobs/3",
     "candidate_required_location": "USA", "description": "<p>Swift, SwiftUI, 4+ years iOS.</p>"},
]

FAKE_ANALYSIS = {
    "best_score": 86,
    "summary": "Strong backend fit; data engineering is plausible with some upskilling; iOS is a mismatch.",
    "matches": [
        {"title": "Senior Python Backend Engineer", "company": "Ledgerly", "url": "https://example.com/jobs/1",
         "score": 86, "strengths": ["FastAPI and asyncio", "AWS + Docker", "fintech background"],
         "gaps": ["seniority level unclear"]},
        {"title": "Data Engineer", "company": "Streamwise", "url": "https://example.com/jobs/2",
         "score": 64, "strengths": ["ETL pipelines", "Python + SQL"], "gaps": ["no Airflow", "no Spark"]},
        {"title": "iOS Developer", "company": "Appfield", "url": "https://example.com/jobs/3",
         "score": 8, "strengths": [], "gaps": ["no Swift", "no mobile experience"]},
    ],
}


def fake_internet(request: httpx.Request) -> httpx.Response:
    if request.url.host == "remotive.com":
        return httpx.Response(200, json={"job-count": len(FAKE_JOBS), "jobs": FAKE_JOBS})
    if request.url.host == "api.anthropic.com":
        body = json.loads(request.content)
        assert body["tool_choice"]["name"] == "submit_result"  # structured output was requested
        return httpx.Response(200, json={
            "model": body["model"], "stop_reason": "tool_use",
            "usage": {"input_tokens": len(body["messages"][0]["content"]) // 4, "output_tokens": 310},
            "content": [{"type": "tool_use", "id": "toolu_demo", "name": "submit_result", "input": FAKE_ANALYSIS}],
        })
    return httpx.Response(404, text=f"offline demo has no route for {request.url}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="use real APIs and stored credentials")
    parser.add_argument("--send", action="store_true", help="actually send the email (needs --live)")
    parser.add_argument("--to", help="email recipient")
    parser.add_argument("--keywords", default="python")
    parser.add_argument("--model", help="override the LLM model")
    args = parser.parse_args()

    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8-sig"))
    workflow["variables"]["dry_run"] = not (args.live and args.send)
    if args.to:
        workflow["variables"]["recipient"] = args.to
    if args.model:
        workflow["nodes"][3]["parameters"]["model"] = args.model
    trigger = dict(workflow["nodes"][0]["parameters"]["sample_data"], keywords=args.keywords)

    db = None
    if args.live:
        from database import Database

        db = Database.open_default()
        http = httpx.AsyncClient()
        credentials = db
    else:
        http = httpx.AsyncClient(transport=httpx.MockTransport(fake_internet))
        credentials = InMemoryCredentialProvider({"anthropic": {"api_key": "offline-demo-key"}})

    engine = WorkflowEngine(credentials=credentials, services={"http_client": http})
    engine.events.subscribe(print_event)
    try:
        result = await engine.run(workflow, trigger_data=trigger)
    finally:
        await http.aclose()
    if db is not None:
        db.save_workflow(engine.parse(workflow))
        db.save_execution(result)
        db.close()

    print()
    if result.nodes["send_email"].output:
        email = result.nodes["send_email"].output
        print(f"{'SENT' if email['sent'] else 'DRY RUN'} -> {', '.join(email['to'])}")
        print(f"Subject: {email['subject']}\n")
        print(email.get("body") or result.nodes["compose"].output["body"])
    elif result.nodes["no_match"].output:
        print(result.nodes["no_match"].output["message"])
    return 0 if result.status is ExecutionStatus.SUCCESS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
