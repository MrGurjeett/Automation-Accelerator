"""Bridge between Automation-Accelerator and NeuraSan Studio.

Sends requests to the NeuraSan server so that:
  1. The Pipeline Intelligence agent network executes on the server
  2. Conversation appears in NSFlow UI thread list
  3. Results stream back to the caller

Architecture
------------
    Strategy 1 — WebSocket + CRUSE persistence (default):
        AA → WebSocket ws://localhost:4173/api/v1/ws/chat/{agent}/{session}
           → NSFlow backend → NeuraSan server (port 8080)
           → Agent executes, response streams back
           → CRUSE thread created → conversation visible in UI sidebar

    Strategy 2 — HTTP streaming (fallback):
        AA → HTTP POST http://localhost:8080/api/v1/{agent}/streaming_chat
           → Agent executes, response returned

    Strategy 3 — Open browser (for live animation):
        AA → Opens http://localhost:4173 with agent pre-selected
           → User types prompt in UI → sees yellow-to-green animation

Usage
-----
    from pipeline.integration.neurasan_bridge import run_neurasan_agent

    result = run_neurasan_agent("Run the decision pipeline")

    # Open NSFlow UI in browser for live animation
    from pipeline.integration.neurasan_bridge import open_in_browser
    open_in_browser()

Requirements
------------
- NeuraSan server running on port 8080 (`python -m run` from neuro-san-studio)
- NSFlow UI running on port 4173 (started automatically with server)
- ``requests`` library installed (``pip install requests``)
- For WebSocket mode: ``websocket-client`` installed (``pip install websocket-client``)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
import webbrowser
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults — override via env vars or function parameters
# ---------------------------------------------------------------------------
_DEFAULT_NSFLOW_HOST = "localhost"
_DEFAULT_NSFLOW_PORT = 4173       # NSFlow frontend
_DEFAULT_BACKEND_PORT = 8080      # NeuraSan backend
_DEFAULT_AGENT = "automation/pipeline_intelligence"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_neurasan_agent(
    prompt: str,
    *,
    config_name: Optional[str] = None,
    excel_path: Optional[str] = None,
    agent_name: Optional[str] = None,
    nsflow_host: Optional[str] = None,
    nsflow_port: Optional[int] = None,
    backend_port: Optional[int] = None,
    timeout: int = 120,
    prefer_websocket: bool = True,
) -> Dict[str, Any]:
    """Invoke the Pipeline Intelligence agent network via NeuraSan server.

    This sends the prompt **through** the NeuraSan server (not locally).
    The conversation is persisted to a CRUSE thread so it appears in the
    NSFlow UI sidebar under the agent's thread list.

    Parameters
    ----------
    prompt : str
        Natural language instruction (e.g. "Run the retry pipeline").
    config_name : str, optional
        Pipeline config hint appended to the prompt.
    excel_path : str, optional
        Excel input path appended to the prompt.
    agent_name : str, optional
        Agent network name.  Default: ``automation/pipeline_intelligence``.
    nsflow_host : str, optional
        NSFlow host.  Default: ``localhost``.
    nsflow_port : int, optional
        NSFlow port (UI + WebSocket).  Default: ``4173``.
    backend_port : int, optional
        NeuraSan backend port (HTTP fallback).  Default: ``8080``.
    timeout : int
        Seconds to wait for a response.  Default: 120.
    prefer_websocket : bool
        If True, try WebSocket first.
        Falls back to HTTP streaming_chat if websocket-client is missing.

    Returns
    -------
    dict
        ``{"ok": True, "response": "...", "agent": "...", "method": "...",
           "thread_id": "...", "ui_url": "..."}``
        on success, or ``{"ok": False, "error": "..."}`` on failure.
    """
    agent_name = agent_name or _DEFAULT_AGENT
    nsflow_host = nsflow_host or os.environ.get("NSFLOW_HOST", _DEFAULT_NSFLOW_HOST)
    nsflow_port = int(nsflow_port or os.environ.get("NSFLOW_PORT", _DEFAULT_NSFLOW_PORT))
    backend_port = int(backend_port or os.environ.get("NEURO_SAN_SERVER_HTTP_PORT", _DEFAULT_BACKEND_PORT))

    # Build enriched prompt
    parts = [prompt]
    if config_name:
        parts.append(f"Use pipeline config: {config_name}")
    if excel_path:
        parts.append(f"Excel input: {excel_path}")
    full_prompt = ". ".join(parts)

    logger.info(
        "NeuraSan bridge: agent=%s, nsflow=%s:%d, backend=:%d, ws=%s",
        agent_name, nsflow_host, nsflow_port, backend_port, prefer_websocket,
    )
    logger.info("NeuraSan bridge: prompt=%s", full_prompt)

    result: Dict[str, Any] = {}

    # --- Strategy 1: WebSocket through NSFlow --------------------------------
    if prefer_websocket:
        try:
            result = _invoke_via_websocket(
                full_prompt, agent_name, nsflow_host, nsflow_port, timeout,
            )
        except ImportError:
            logger.warning(
                "websocket-client not installed — falling back to HTTP. "
                "Install with: pip install websocket-client"
            )
        except Exception as exc:
            logger.warning("WebSocket failed (%s) — falling back to HTTP", exc)

    # --- Strategy 2: HTTP POST to NeuraSan backend (fallback) ----------------
    if not result:
        result = _invoke_via_http(
            full_prompt, agent_name, nsflow_host, backend_port, timeout,
        )

    # --- Persist to CRUSE thread so conversation shows in UI sidebar ---------
    if result.get("ok"):
        try:
            thread_info = _persist_to_cruse_thread(
                agent_name=agent_name,
                user_prompt=full_prompt,
                ai_response=result.get("response", ""),
                host=nsflow_host,
                port=nsflow_port,
            )
            result["thread_id"] = thread_info.get("thread_id")
            result["ui_url"] = (
                f"http://{nsflow_host}:{nsflow_port}"
                f"?agent={agent_name}"
            )
            logger.info(
                "NeuraSan bridge: conversation saved to thread %s",
                thread_info.get("thread_id"),
            )
        except Exception as exc:
            logger.warning("NeuraSan bridge: failed to persist CRUSE thread: %s", exc)

    return result


def open_in_browser(
    agent_name: Optional[str] = None,
    nsflow_host: str = _DEFAULT_NSFLOW_HOST,
    nsflow_port: int = _DEFAULT_NSFLOW_PORT,
    prompt: Optional[str] = None,
) -> str:
    """Open NSFlow UI in the default browser with the agent pre-selected.

    This is the ONLY way to see live yellow-to-green node animation —
    the animation is rendered client-side by the React app and only
    appears for the active browser session.

    Parameters
    ----------
    agent_name : str, optional
        Agent to pre-select.  Default: ``automation/pipeline_intelligence``.
    nsflow_host : str
        NSFlow host.
    nsflow_port : int
        NSFlow port.
    prompt : str, optional
        If provided, printed as a suggested prompt the user can paste into chat.

    Returns
    -------
    str
        The URL that was opened.
    """
    agent_name = agent_name or _DEFAULT_AGENT
    url = f"http://{nsflow_host}:{nsflow_port}"
    webbrowser.open(url)
    logger.info("NeuraSan bridge: opened %s in browser", url)
    if prompt:
        logger.info("NeuraSan bridge: paste this into the chat box: %s", prompt)
    return url


def check_server(
    nsflow_host: str = _DEFAULT_NSFLOW_HOST,
    nsflow_port: int = _DEFAULT_NSFLOW_PORT,
    backend_port: int = _DEFAULT_BACKEND_PORT,
) -> Dict[str, Any]:
    """Quick health check — verifies both NSFlow and NeuraSan backend are up."""
    import requests

    status: Dict[str, Any] = {}

    # Check NSFlow (try multiple health endpoints)
    nsflow_ok = False
    for path in ("/api/v1/ping", "/api/v1/list"):
        try:
            r = requests.get(
                f"http://{nsflow_host}:{nsflow_port}{path}", timeout=5,
            )
            if r.status_code == 200:
                nsflow_ok = True
                break
        except requests.ConnectionError:
            pass
    status["nsflow"] = {"ok": nsflow_ok, "port": nsflow_port}
    if not nsflow_ok:
        status["nsflow"]["error"] = "Connection refused"

    # Check NeuraSan backend (health at root /healthz, not /api/v1/healthz)
    backend_ok = False
    for path in ("/healthz", "/api/v1/healthz", "/"):
        try:
            r = requests.get(
                f"http://{nsflow_host}:{backend_port}{path}", timeout=5,
            )
            if r.status_code == 200:
                backend_ok = True
                break
        except requests.ConnectionError:
            pass
    status["backend"] = {"ok": backend_ok, "port": backend_port}
    if not backend_ok:
        status["backend"]["error"] = "Connection refused"

    # Check if pipeline_intelligence agent is registered
    try:
        r = requests.get(
            f"http://{nsflow_host}:{backend_port}/api/v1/list", timeout=10,
        )
        if r.status_code == 200:
            agents_data = r.json()
            agent_names = [
                a.get("agent_name", a.get("name", ""))
                for a in agents_data.get("agents", [])
            ]
            found = (
                "pipeline_intelligence" in agent_names
                or "automation/pipeline_intelligence" in agent_names
            )
            status["agent_registered"] = {"ok": found, "agents_found": len(agent_names)}
            if not found:
                status["agent_registered"]["available"] = agent_names[:10]
            else:
                for name in agent_names:
                    if "pipeline_intelligence" in name:
                        status["agent_registered"]["agent_name"] = name
                        break
    except Exception as exc:
        status["agent_registered"] = {"ok": False, "error": str(exc)}

    status["all_ok"] = all(
        v.get("ok", False) for v in status.values() if isinstance(v, dict)
    )
    return status


# ---------------------------------------------------------------------------
# CRUSE Thread Persistence  (makes conversation visible in NSFlow UI)
# ---------------------------------------------------------------------------

def _persist_to_cruse_thread(
    agent_name: str,
    user_prompt: str,
    ai_response: str,
    host: str,
    port: int,
) -> Dict[str, Any]:
    """Create a CRUSE thread and save the conversation to NSFlow's DB.

    After this, the thread appears in the NSFlow UI sidebar under the
    agent's thread list.  The user can click it to view the full
    conversation (though not replay the live animation).
    """
    import requests

    base = f"http://{host}:{port}/api/v1"

    # 1. Create thread
    r = requests.post(
        f"{base}/cruse/threads",
        json={
            "title": f"AA Bridge: {user_prompt[:50]}",
            "agent_name": agent_name,
        },
        timeout=10,
    )
    r.raise_for_status()
    thread = r.json()
    thread_id = thread["id"]

    origin = [{"tool": "PipelineOrchestrator", "instantiation_index": 0}]

    # 2. Save user message
    requests.post(
        f"{base}/cruse/threads/{thread_id}/messages",
        json={
            "sender": "user",
            "text": user_prompt,
            "origin": origin,
        },
        timeout=10,
    ).raise_for_status()

    # 3. Save AI response
    requests.post(
        f"{base}/cruse/threads/{thread_id}/messages",
        json={
            "sender": "assistant",
            "text": ai_response,
            "origin": origin,
        },
        timeout=10,
    ).raise_for_status()

    return {"thread_id": thread_id, "agent_name": agent_name}


# ---------------------------------------------------------------------------
# Strategy 1: WebSocket through NSFlow
# ---------------------------------------------------------------------------

def _invoke_via_websocket(
    prompt: str,
    agent_name: str,
    host: str,
    port: int,
    timeout: int,
) -> Dict[str, Any]:
    """Connect to NSFlow WebSocket and send a chat message.

    Executes the agent on the NeuraSan server via the NSFlow WebSocket
    relay.  The server-side agent runs identically to how it runs when
    triggered from the browser UI.
    """
    import websocket  # websocket-client package

    session_id = str(uuid.uuid4())
    ws_url = f"ws://{host}:{port}/api/v1/ws/chat/{agent_name}/{session_id}"

    logger.info("NeuraSan bridge [WS]: connecting to %s", ws_url)

    responses: List[str] = []
    errors: List[str] = []

    ws = websocket.create_connection(ws_url, timeout=timeout)
    logger.info("NeuraSan bridge [WS]: connected — sending prompt")

    try:
        # NSFlow WebSocket expects: {"message": "text", "sly_data": {}, "chat_context": {}}
        message_payload = json.dumps({
            "message": prompt,
            "sly_data": {},
            "chat_context": {},
        })
        ws.send(message_payload)
        logger.info("NeuraSan bridge [WS]: prompt sent, waiting for response stream...")

        # Two-phase timeout: long initial wait (agent may call tools),
        # then short idle timeout after first chunk to detect completion.
        _IDLE_TIMEOUT = 5  # seconds of silence after last chunk = done
        got_first = False

        while True:
            try:
                raw = ws.recv()
                if not raw:
                    break

                logger.debug("NeuraSan bridge [WS]: chunk: %s", raw[:200])

                if not got_first:
                    got_first = True
                    ws.settimeout(_IDLE_TIMEOUT)

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    responses.append(raw)
                    continue

                # NSFlow sends: {"message": {"type": "AI", "text": "..."}}
                if isinstance(data, dict):
                    msg = data.get("message", {})
                    if isinstance(msg, dict):
                        text = msg.get("text", "")
                        if text:
                            responses.append(text)
                    elif isinstance(msg, str) and msg:
                        responses.append(msg)

                    # Backend direct format
                    resp = data.get("response", {})
                    if isinstance(resp, dict) and resp.get("text"):
                        responses.append(resp["text"])

                    if "error" in data:
                        errors.append(str(data["error"]))

            except websocket.WebSocketTimeoutException:
                if got_first:
                    logger.info("NeuraSan bridge [WS]: idle timeout — response complete")
                else:
                    logger.warning("NeuraSan bridge [WS]: no response after %ds", timeout)
                    errors.append(f"No response within {timeout}s")
                break
            except websocket.WebSocketConnectionClosedException:
                logger.info("NeuraSan bridge [WS]: connection closed by server (done)")
                break

    finally:
        ws.close()

    full_text = "\n".join(responses) if responses else "(no response text)"

    if errors:
        logger.error("NeuraSan bridge [WS]: errors: %s", errors)
        return {
            "ok": False,
            "error": "; ".join(errors),
            "partial_response": full_text,
            "agent": agent_name,
            "method": "websocket",
            "session_id": session_id,
        }

    logger.info("NeuraSan bridge [WS]: success — %d response chunks", len(responses))
    return {
        "ok": True,
        "response": full_text,
        "agent": agent_name,
        "method": "websocket",
        "session_id": session_id,
        "prompt": prompt,
    }


# ---------------------------------------------------------------------------
# Strategy 2: HTTP POST to NeuraSan backend
# ---------------------------------------------------------------------------

def _invoke_via_http(
    prompt: str,
    agent_name: str,
    host: str,
    port: int,
    timeout: int,
) -> Dict[str, Any]:
    """POST to the NeuraSan streaming_chat HTTP endpoint."""
    import requests

    url = f"http://{host}:{port}/api/v1/{agent_name}/streaming_chat"
    payload = {
        "user_message": {
            "text": prompt,
        },
    }

    logger.info("NeuraSan bridge [HTTP]: POST %s", url)

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
            stream=True,
        )

        logger.info("NeuraSan bridge [HTTP]: status=%d", resp.status_code)

        if resp.status_code != 200:
            error_text = resp.text[:500]
            logger.error("NeuraSan bridge [HTTP]: error: %s", error_text)
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}: {error_text}",
                "agent": agent_name,
                "method": "http",
            }

        responses: List[str] = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    r = data.get("response", data)
                    text = r.get("text", "") if isinstance(r, dict) else str(r)
                    if text:
                        responses.append(text)
            except json.JSONDecodeError:
                responses.append(line)

        full_text = "\n".join(responses) if responses else "(no response text)"
        logger.info("NeuraSan bridge [HTTP]: success — %d chunks", len(responses))

        return {
            "ok": True,
            "response": full_text,
            "agent": agent_name,
            "method": "http",
            "prompt": prompt,
        }

    except Exception as exc:
        import requests as _req
        if isinstance(exc, _req.ConnectionError):
            msg = (
                f"Cannot connect to NeuraSan server at {host}:{port}. "
                f"Is the server running? Start with: cd neuro-san-studio && python -m run"
            )
        elif isinstance(exc, _req.Timeout):
            msg = f"Request timed out after {timeout}s"
        else:
            msg = str(exc)
        logger.error("NeuraSan bridge [HTTP]: %s", msg)
        return {"ok": False, "error": msg, "agent": agent_name, "method": "http"}
