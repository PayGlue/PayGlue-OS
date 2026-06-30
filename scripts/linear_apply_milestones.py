#!/usr/bin/env python3

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional


LINEAR_URL = "https://api.linear.app/graphql"


def gql(token: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise RuntimeError(f"Linear API HTTP {exc.code}: {body}") from exc

    data = json.loads(raw)
    if data.get("errors"):
        raise RuntimeError(f"Linear API errors: {data['errors']}")
    return data.get("data", {})


def resolve_team_id(token: str, team_name: str) -> str:
    query = """
    query Teams {
      teams {
        nodes {
          id
          name
        }
      }
    }
    """
    data = gql(token, query, {})
    nodes = data.get("teams", {}).get("nodes", [])
    exact = [n for n in nodes if n.get("name") == team_name]
    if len(exact) == 1:
        return exact[0]["id"]
    ci = [n for n in nodes if str(n.get("name", "")).lower() == team_name.lower()]
    if len(ci) == 1:
        return ci[0]["id"]
    if not ci:
        raise RuntimeError(f"Could not find Linear team named '{team_name}'.")
    raise RuntimeError(
        f"Multiple Linear teams matched '{team_name}'. Set LINEAR_TEAM_ID explicitly."
    )


def resolve_project_id(token: str, project_name: str) -> str:
    query = """
    query Projects {
      projects {
        nodes {
          id
          name
        }
      }
    }
    """
    data = gql(token, query, {})
    nodes = data.get("projects", {}).get("nodes", [])
    exact = [n for n in nodes if n.get("name") == project_name]
    if len(exact) == 1:
        return exact[0]["id"]
    ci = [n for n in nodes if str(n.get("name", "")).lower() == project_name.lower()]
    if len(ci) == 1:
        return ci[0]["id"]
    if not ci:
        raise RuntimeError(f"Could not find Linear project named '{project_name}'.")
    raise RuntimeError(
        f"Multiple Linear projects matched '{project_name}'. Set LINEAR_PROJECT_ID explicitly."
    )


def get_project_milestones(token: str, project_id: str) -> dict[str, str]:
    query = """
    query Milestones($projectId: ID!) {
      projectMilestones(filter: { project: { id: { eq: $projectId }}}) {
        nodes {
          id
          name
        }
      }
    }
    """
    data = gql(token, query, {"projectId": project_id})
    return {node["name"]: node["id"] for node in data["projectMilestones"]["nodes"]}


def create_project_milestone(
    token: str, project_id: str, name: str, description: str
) -> str:
    mutation = """
    mutation CreateMilestone($input: ProjectMilestoneCreateInput!) {
      projectMilestoneCreate(input: $input) {
        success
        projectMilestone {
          id
          name
        }
      }
    }
    """
    data = gql(
        token,
        mutation,
        {
            "input": {
                "projectId": project_id,
                "name": name,
                "description": description,
            }
        },
    )
    milestone = data["projectMilestoneCreate"]["projectMilestone"]
    return milestone["id"]


def get_issue_by_identifier(
    token: str, team_id: str, identifier: str
) -> tuple[str, Optional[str], Optional[str]]:
    _, _, raw_number = identifier.partition("-")
    try:
        issue_number = int(raw_number)
    except ValueError as exc:
        raise RuntimeError(
            f"Issue '{identifier}' is not in expected KEY-NUMBER format."
        ) from exc

    query = """
    query IssueByNumber($teamId: ID!, $issueNumber: Float!) {
      issues(filter: { team: { id: { eq: $teamId }}, number: { eq: $issueNumber }}) {
        nodes {
          id
          project {
            id
          }
          projectMilestone {
            id
          }
        }
      }
    }
    """
    data = gql(token, query, {"teamId": team_id, "issueNumber": issue_number})
    nodes = data.get("issues", {}).get("nodes", [])
    if not nodes:
        raise RuntimeError(f"Issue '{identifier}' was not found.")
    issue = nodes[0]
    current = issue.get("projectMilestone")
    current_id = current.get("id") if isinstance(current, dict) else None
    project = issue.get("project")
    project_id = project.get("id") if isinstance(project, dict) else None
    return issue["id"], current_id, project_id


def set_issue_milestone(token: str, issue_id: str, milestone_id: str) -> None:
    mutation = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
      }
    }
    """
    gql(
        token,
        mutation,
        {
            "id": issue_id,
            "input": {"projectMilestoneId": milestone_id},
        },
    )


def main() -> int:
    token = os.environ.get("LINEAR_API_TOKEN")
    team_id = os.environ.get("LINEAR_TEAM_ID")
    project_id = os.environ.get("LINEAR_PROJECT_ID")
    team_name = os.environ.get("LINEAR_TEAM_NAME", "PayGlue")
    project_name = os.environ.get("LINEAR_PROJECT_NAME", "PayGlue")
    dry_run = os.environ.get("LINEAR_DRY_RUN", "0") == "1"

    if not token:
        print("Missing required env var: LINEAR_API_TOKEN", file=sys.stderr)
        return 1

    if not team_id:
        team_id = resolve_team_id(token, team_name)
        print(f"Resolved team '{team_name}' -> {team_id}")

    if not project_id:
        project_id = resolve_project_id(token, project_name)
        print(f"Resolved project '{project_name}' -> {project_id}")

    config_path = os.path.join(os.path.dirname(__file__), "linear_milestones.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    milestones = config.get("milestones")
    if not isinstance(milestones, list):
        raise RuntimeError("Invalid milestone config: milestones must be a list.")

    milestones_by_name = get_project_milestones(token, project_id)
    simulated_created_names: set[str] = set()

    for milestone in milestones:
        name = str(milestone["name"])
        description = str(milestone.get("description", ""))
        if name in milestones_by_name:
            continue
        if dry_run:
            print(f"[DRY RUN] create milestone: {name}")
            simulated_created_names.add(name)
            continue
        milestone_id = create_project_milestone(token, project_id, name, description)
        milestones_by_name[name] = milestone_id
        print(f"Created milestone {name} ({milestone_id})")

    if dry_run:
        milestones_by_name = get_project_milestones(token, project_id)

    for milestone in milestones:
        name = str(milestone["name"])
        issues = milestone.get("issues", [])
        if not isinstance(issues, list):
            raise RuntimeError(f"Milestone '{name}' has invalid issues list.")

        milestone_id = milestones_by_name.get(name)
        if milestone_id is None and dry_run and name in simulated_created_names:
            milestone_id = f"dry-run:{name}"
        if milestone_id is None:
            raise RuntimeError(f"Milestone '{name}' missing id after create/fetch.")

        for identifier in issues:
            issue_id, current_milestone_id, issue_project_id = get_issue_by_identifier(
                token, team_id, str(identifier)
            )

            if issue_project_id != project_id:
                note = (
                    f"skip {identifier}: issue belongs to different project "
                    f"({issue_project_id})"
                )
                if dry_run:
                    print(f"[DRY RUN] {note}")
                else:
                    print(note)
                continue

            if current_milestone_id == milestone_id:
                if dry_run:
                    print(f"[DRY RUN] {identifier} already set to {name}")
                continue

            if dry_run:
                print(f"[DRY RUN] set {identifier} -> {name}")
                continue

            set_issue_milestone(token, issue_id, milestone_id)
            print(f"Updated {identifier} -> {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
