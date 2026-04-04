"""
ADOConnector — Azure DevOps REST API connector.

Phase 4A — provides work item and test case access through the
BaseConnector interface, keeping all ADO-specific logic isolated
from pipeline agents.

Supported fetch types:
  - ``work_items``  — WIQL query or by ID
  - ``test_cases``  — test case work items with steps

Supported push types:
  - ``work_item``   — create or update a work item
  - ``test_result`` — publish test result

Example::

    ado = ADOConnector(
        organization="my-org",
        project="my-project",
        pat="<personal-access-token>",
    )
    ado.connect()

    result = ado.fetch({
        "type": "work_items",
        "query": "SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'Active'"
    })

    result = ado.fetch({
        "type": "work_items",
        "ids": [123, 456],
    })
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
from urllib.parse import quote

from pipeline.connectors.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

# ADO REST API version
_API_VERSION = "7.1"


class ADOConnector(BaseConnector):
    """Azure DevOps REST API connector.

    Credentials can be provided explicitly or via environment variables:
      - ``ADO_ORGANIZATION`` / ``ADO_ORG``
      - ``ADO_PROJECT``
      - ``ADO_PAT`` (Personal Access Token)
      - ``ADO_BASE_URL`` (optional, defaults to ``dev.azure.com``)
    """

    name = "ado"
    description = "Azure DevOps REST API connector"

    def __init__(
        self,
        organization: str | None = None,
        project: str | None = None,
        pat: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._organization = organization or os.environ.get("ADO_ORGANIZATION") or os.environ.get("ADO_ORG", "")
        self._project = project or os.environ.get("ADO_PROJECT", "")
        self._pat = pat or os.environ.get("ADO_PAT", "")
        self._base_url = (
            base_url
            or os.environ.get("ADO_BASE_URL", "")
            or f"https://dev.azure.com/{self._organization}"
        )
        self._connected = False
        self._auth_header: dict[str, str] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def connect(self) -> ConnectorResult:
        """Validate credentials and prepare auth headers."""
        if not self._organization:
            return ConnectorResult(ok=False, error="ADO organization not configured")
        if not self._pat:
            return ConnectorResult(ok=False, error="ADO PAT not configured")

        # Build Basic auth header (ADO uses empty username + PAT)
        token = base64.b64encode(f":{self._pat}".encode()).decode()
        self._auth_header = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self._connected = True

        logger.info(
            "[ADO] Connected to %s (project: %s)",
            self._organization, self._project or "<default>",
        )
        return ConnectorResult(
            ok=True,
            data={"organization": self._organization, "project": self._project},
        )

    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        """Fetch data from Azure DevOps.

        Supported query types:
          - ``{"type": "work_items", "query": "<WIQL>"}``
          - ``{"type": "work_items", "ids": [123, 456]}``
          - ``{"type": "work_items", "ids": [123], "project": "OtherProject"}``
          - ``{"type": "test_cases", "plan_id": 1, "suite_id": 2}``
          - ``{"type": "test_cases", "query": "<WIQL>"}``
        """
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected. Call connect() first.")

        fetch_type = query.get("type", "")
        project = query.get("project") or self._project

        if fetch_type == "work_items":
            return self._fetch_work_items(query, project)
        elif fetch_type == "test_cases":
            return self._fetch_test_cases(query, project)
        else:
            return ConnectorResult(
                ok=False,
                error=f"Unknown fetch type: {fetch_type!r}. Supported: work_items, test_cases",
            )

    def push(self, data: dict[str, Any]) -> ConnectorResult:
        """Push data to Azure DevOps.

        Supported push types:
          - ``{"type": "work_item", "work_item_type": "Task", "fields": {...}}``
          - ``{"type": "test_result", "run_id": 1, "results": [...]}``
        """
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected. Call connect() first.")

        push_type = data.get("type", "")
        project = data.get("project") or self._project

        if push_type == "work_item":
            return self._push_work_item(data, project)
        elif push_type == "test_result":
            return self._push_test_result(data, project)
        else:
            return ConnectorResult(
                ok=False,
                error=f"Unknown push type: {push_type!r}. Supported: work_item, test_result",
            )

    def health_check(self) -> ConnectorResult:
        """Check ADO connectivity by hitting the projects API."""
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected")

        try:
            url = f"{self._base_url}/_apis/projects?api-version={_API_VERSION}&$top=1"
            status, body = self._request("GET", url)
            if status == 200:
                return ConnectorResult(ok=True, data={"status": "healthy"}, status_code=status)
            else:
                return ConnectorResult(
                    ok=False,
                    error=f"ADO health check failed (HTTP {status})",
                    status_code=status,
                )
        except Exception as exc:
            return ConnectorResult(ok=False, error=f"ADO health check error: {exc}")

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        body: dict | list | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict | list | str]:
        """Make an HTTP request to the ADO REST API.

        Uses ``urllib`` to avoid adding ``requests`` as a dependency.
        Returns (status_code, parsed_response).
        """
        import urllib.request
        import urllib.error

        headers = dict(self._auth_header)
        if content_type:
            headers["Content-Type"] = content_type

        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw
        except urllib.error.URLError as exc:
            raise ConnectionError(f"ADO request failed: {exc.reason}") from exc

    # ------------------------------------------------------------------
    # Fetch implementations
    # ------------------------------------------------------------------

    def _fetch_work_items(self, query: dict, project: str) -> ConnectorResult:
        """Fetch work items by WIQL query or by IDs."""
        ids = query.get("ids")
        wiql = query.get("query")

        if ids:
            return self._fetch_work_items_by_ids(ids, project)
        elif wiql:
            return self._fetch_work_items_by_wiql(wiql, project)
        else:
            return ConnectorResult(
                ok=False,
                error="work_items fetch requires 'ids' (list) or 'query' (WIQL string)",
            )

    def _fetch_work_items_by_wiql(self, wiql: str, project: str) -> ConnectorResult:
        """Execute a WIQL query and return the matching work items."""
        try:
            # Step 1: Execute WIQL to get IDs
            wiql_url = f"{self._base_url}/{quote(project)}/_apis/wit/wiql?api-version={_API_VERSION}"
            status, body = self._request("POST", wiql_url, {"query": wiql})

            if status != 200:
                return ConnectorResult(
                    ok=False, error=f"WIQL query failed (HTTP {status})", status_code=status,
                    data={"response": body},
                )

            work_item_refs = body.get("workItems", []) if isinstance(body, dict) else []
            if not work_item_refs:
                return ConnectorResult(ok=True, data={"work_items": [], "count": 0})

            # Step 2: Fetch full details for the IDs
            ids = [ref["id"] for ref in work_item_refs[:200]]  # cap at 200
            return self._fetch_work_items_by_ids(ids, project)

        except Exception as exc:
            logger.error("[ADO] WIQL fetch failed: %s", exc)
            return ConnectorResult(ok=False, error=str(exc))

    def _fetch_work_items_by_ids(self, ids: list[int], project: str) -> ConnectorResult:
        """Fetch work items by their IDs (batched)."""
        try:
            ids_str = ",".join(str(i) for i in ids[:200])
            url = (
                f"{self._base_url}/{quote(project)}/_apis/wit/workitems"
                f"?ids={ids_str}&$expand=all&api-version={_API_VERSION}"
            )
            status, body = self._request("GET", url)

            if status != 200:
                return ConnectorResult(
                    ok=False, error=f"Work item fetch failed (HTTP {status})",
                    status_code=status, data={"response": body},
                )

            items = body.get("value", []) if isinstance(body, dict) else []
            return ConnectorResult(
                ok=True,
                data={"work_items": items, "count": len(items)},
                status_code=status,
            )

        except Exception as exc:
            logger.error("[ADO] Work item fetch failed: %s", exc)
            return ConnectorResult(ok=False, error=str(exc))

    def _fetch_test_cases(self, query: dict, project: str) -> ConnectorResult:
        """Fetch test cases — via test plan/suite or WIQL query."""
        plan_id = query.get("plan_id")
        suite_id = query.get("suite_id")
        wiql = query.get("query")

        if plan_id and suite_id:
            try:
                url = (
                    f"{self._base_url}/{quote(project)}/_apis/test/Plans/{plan_id}"
                    f"/Suites/{suite_id}/TestCase?api-version={_API_VERSION}"
                )
                status, body = self._request("GET", url)

                if status != 200:
                    return ConnectorResult(
                        ok=False, error=f"Test case fetch failed (HTTP {status})",
                        status_code=status,
                    )

                cases = body.get("value", []) if isinstance(body, dict) else []
                return ConnectorResult(
                    ok=True,
                    data={"test_cases": cases, "count": len(cases)},
                    status_code=status,
                )
            except Exception as exc:
                return ConnectorResult(ok=False, error=str(exc))

        elif wiql:
            # Fetch test case work items via WIQL
            if "WorkItemType" not in wiql:
                wiql = wiql.replace(
                    "FROM WorkItems",
                    "FROM WorkItems WHERE [System.WorkItemType] = 'Test Case' AND",
                )
            return self._fetch_work_items_by_wiql(wiql, project)
        else:
            return ConnectorResult(
                ok=False,
                error="test_cases fetch requires 'plan_id' + 'suite_id' or 'query' (WIQL)",
            )

    # ------------------------------------------------------------------
    # Push implementations
    # ------------------------------------------------------------------

    def _push_work_item(self, data: dict, project: str) -> ConnectorResult:
        """Create a work item via JSON Patch."""
        work_item_type = data.get("work_item_type", "Task")
        fields = data.get("fields", {})

        if not fields:
            return ConnectorResult(ok=False, error="No fields provided for work item creation")

        try:
            # ADO uses JSON Patch format for work item creation
            patch_doc = [
                {"op": "add", "path": f"/fields/{key}", "value": value}
                for key, value in fields.items()
            ]

            url = (
                f"{self._base_url}/{quote(project)}/_apis/wit/workitems"
                f"/${quote(work_item_type)}?api-version={_API_VERSION}"
            )
            status, body = self._request(
                "POST", url, patch_doc,
                content_type="application/json-patch+json",
            )

            if status in (200, 201):
                return ConnectorResult(
                    ok=True,
                    data={"work_item": body, "id": body.get("id") if isinstance(body, dict) else None},
                    status_code=status,
                )
            else:
                return ConnectorResult(
                    ok=False, error=f"Work item creation failed (HTTP {status})",
                    status_code=status, data={"response": body},
                )
        except Exception as exc:
            return ConnectorResult(ok=False, error=str(exc))

    def _push_test_result(self, data: dict, project: str) -> ConnectorResult:
        """Publish test results to a test run."""
        run_id = data.get("run_id")
        results = data.get("results", [])

        if not run_id:
            return ConnectorResult(ok=False, error="run_id required for test_result push")
        if not results:
            return ConnectorResult(ok=False, error="No results provided")

        try:
            url = (
                f"{self._base_url}/{quote(project)}/_apis/test/Runs/{run_id}"
                f"/results?api-version={_API_VERSION}"
            )
            status, body = self._request("POST", url, results)

            if status in (200, 201):
                return ConnectorResult(
                    ok=True,
                    data={"published_count": len(results)},
                    status_code=status,
                )
            else:
                return ConnectorResult(
                    ok=False, error=f"Test result publish failed (HTTP {status})",
                    status_code=status,
                )
        except Exception as exc:
            return ConnectorResult(ok=False, error=str(exc))
