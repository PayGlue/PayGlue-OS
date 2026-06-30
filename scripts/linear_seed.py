#!/usr/bin/env python3

import json
import os
import sys
import urllib.error
import urllib.request


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


def create_issue(
    token: str,
    team_id: str,
    project_id: str,
    title: str,
    description: str,
    priority: int,
    label_ids: list[str],
) -> str:
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          identifier
          title
        }
      }
    }
    """
    variables = {
        "input": {
            "teamId": team_id,
            "projectId": project_id,
            "title": title,
            "description": description,
            "priority": priority,
            "labelIds": label_ids,
        }
    }
    result = gql(token, mutation, variables)
    issue = result["issueCreate"]["issue"]
    return issue["identifier"]


def get_labels(token: str, team_id: str) -> dict[str, str]:
    query = """
    query TeamLabels($teamId: ID!) {
      issueLabels(filter: { team: { id: { eq: $teamId }}}) {
        nodes {
          id
          name
        }
      }
    }
    """
    data = gql(token, query, {"teamId": team_id})
    return {n["name"]: n["id"] for n in data["issueLabels"]["nodes"]}


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


def main() -> int:
    token = os.environ.get("LINEAR_API_TOKEN")
    team_id = os.environ.get("LINEAR_TEAM_ID")
    project_id = os.environ.get("LINEAR_PROJECT_ID")
    team_name = os.environ.get("LINEAR_TEAM_NAME")
    project_name = os.environ.get("LINEAR_PROJECT_NAME")
    dry_run = os.environ.get("LINEAR_DRY_RUN", "0") == "1"

    if not token:
        print(
            "Missing required env var: LINEAR_API_TOKEN",
            file=sys.stderr,
        )
        return 1

    if not team_id:
        if team_name:
            team_id = resolve_team_id(token, team_name)
            print(f"Resolved team '{team_name}' -> {team_id}")
        else:
            print(
                "Missing LINEAR_TEAM_ID. Set LINEAR_TEAM_ID or LINEAR_TEAM_NAME.",
                file=sys.stderr,
            )
            return 1

    if not project_id:
        if project_name:
            project_id = resolve_project_id(token, project_name)
            print(f"Resolved project '{project_name}' -> {project_id}")
        else:
            print(
                "Missing LINEAR_PROJECT_ID. Set LINEAR_PROJECT_ID or LINEAR_PROJECT_NAME.",
                file=sys.stderr,
            )
            return 1

    seed_path = os.path.join(os.path.dirname(__file__), "linear_seed_data.json")
    with open(seed_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    labels_by_name = get_labels(token, team_id)

    for item in items:
        title = item["title"]
        description = item["description"]
        priority = item["priority"]
        label_names = item.get("labels", [])
        label_ids = [labels_by_name[name] for name in label_names if name in labels_by_name]

        if dry_run:
            print(f"[DRY RUN] {title} | priority={priority} | labels={label_names}")
            continue

        identifier = create_issue(
            token=token,
            team_id=team_id,
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            label_ids=label_ids,
        )
        print(f"Created {identifier}: {title}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
