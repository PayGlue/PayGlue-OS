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
    return {node["name"]: node["id"] for node in data["issueLabels"]["nodes"]}


def create_label(token: str, team_id: str, label_name: str) -> str:
    mutation = """
    mutation CreateLabel($input: IssueLabelCreateInput!) {
      issueLabelCreate(input: $input) {
        success
        issueLabel {
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
                "teamId": team_id,
                "name": label_name,
            }
        },
    )
    label = data["issueLabelCreate"]["issueLabel"]
    return label["id"]


def get_issue_by_identifier(token: str, team_id: str, identifier: str) -> tuple[str, list[str]]:
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
          labels {
            nodes {
              name
            }
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
    existing = [n["name"] for n in issue.get("labels", {}).get("nodes", [])]
    return issue["id"], existing


def update_issue_labels(token: str, issue_id: str, label_ids: list[str]) -> None:
    mutation = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
      }
    }
    """
    gql(token, mutation, {"id": issue_id, "input": {"labelIds": label_ids}})


def main() -> int:
    token = os.environ.get("LINEAR_API_TOKEN")
    team_id = os.environ.get("LINEAR_TEAM_ID")
    team_name = os.environ.get("LINEAR_TEAM_NAME", "PayGlue")
    dry_run = os.environ.get("LINEAR_DRY_RUN", "0") == "1"

    if not token:
        print("Missing required env var: LINEAR_API_TOKEN", file=sys.stderr)
        return 1

    if not team_id:
        team_id = resolve_team_id(token, team_name)
        print(f"Resolved team '{team_name}' -> {team_id}")

    mapping_path = os.path.join(os.path.dirname(__file__), "linear_issue_labels.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    labels_by_name = get_labels(token, team_id)
    required_labels = set()
    for issue_labels in mapping.values():
        for label in issue_labels:
            required_labels.add(label)

    for label_name in sorted(required_labels):
        if label_name in labels_by_name:
            continue
        if dry_run:
            print(f"[DRY RUN] create label: {label_name}")
            continue
        label_id = create_label(token, team_id, label_name)
        labels_by_name[label_name] = label_id
        print(f"Created label {label_name} ({label_id})")

    if dry_run:
        labels_by_name = get_labels(token, team_id)

    for identifier, target_labels in mapping.items():
        issue_id, existing_labels = get_issue_by_identifier(token, team_id, identifier)
        merged_names = sorted(set(existing_labels) | set(target_labels))
        missing = [label for label in merged_names if label not in labels_by_name]
        if missing:
            raise RuntimeError(
                f"Cannot set labels for {identifier}. Missing IDs for labels: {', '.join(missing)}"
            )
        merged_ids = [labels_by_name[name] for name in merged_names]

        if dry_run:
            print(
                f"[DRY RUN] {identifier}: existing={existing_labels} -> target={merged_names}"
            )
            continue

        update_issue_labels(token, issue_id, merged_ids)
        print(f"Updated {identifier}: {', '.join(merged_names)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
