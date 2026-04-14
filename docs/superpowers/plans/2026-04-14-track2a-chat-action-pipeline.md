# Track 2A — Chat → Action Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Unity chat agent operate in all three modes — reactive (ask → act → show proof), watchdog (proactively surfaces issues), and autonomous (goal → plan → execute → verify) — with visual feedback after every scene action.

**Architecture:** All changes are in `core/agent_chat.py`. `_OfflineUnityAssistant` gains: visual capture helper, player prototype flow, script create+attach flow, richer intent dispatch, and autonomous goal handler. `ChatBridge` gains a watchdog background thread. No new files needed.

**Tech Stack:** Python, File IPC (`core/file_ipc.py`), embedded CLI (`core/embedded_cli.py`), Click commands via `_run_embedded_cli`

---

## File Structure

```
core/agent_chat.py          # MODIFIED — all changes go here
tests/test_chat_e2e.py      # MODIFIED — new tests for each new capability
```

---

## Task 1: Visual capture helper — screenshot after every scene action

**Files:**
- Modify: `cli_anything/unity_mcp/core/agent_chat.py`
- Test: `cli_anything/unity_mcp/tests/test_chat_e2e.py` (or `test_core.py` if chat_e2e doesn't exist yet)

- [ ] **Step 1: Write the failing test**

In `tests/test_chat_e2e.py` (or `test_core.py`), add to the appropriate test class:

```python
def test_capture_after_action_returns_paths_when_live(self):
    """_capture_after_action returns a non-empty dict when file client responds."""
    from unittest.mock import MagicMock, patch
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant, ChatBridge
    from cli_anything.unity_mcp.core.file_ipc import FileIPCClient
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmp:
        client = MagicMock(spec=FileIPCClient)
        client.call_route.return_value = {
            "gamePath": "/tmp/game.png",
            "scenePath": "/tmp/scene.png",
        }
        bridge = MagicMock()
        bridge.client = client
        bridge.project_path = tmp
        assistant = _OfflineUnityAssistant(bridge)
        result = assistant._capture_after_action()
        assert result.get("gamePath") == "/tmp/game.png"
        assert result.get("scenePath") == "/tmp/scene.png"

def test_capture_after_action_returns_empty_on_error(self):
    """_capture_after_action returns empty dict when capture fails."""
    from unittest.mock import MagicMock
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant
    from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

    client = MagicMock(spec=FileIPCClient)
    client.call_route.side_effect = RuntimeError("no unity")
    bridge = MagicMock()
    bridge.client = client
    assistant = _OfflineUnityAssistant(bridge)
    result = assistant._capture_after_action()
    assert result == {}
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py::ChatE2ETests::test_capture_after_action_returns_paths_when_live -v 2>&1 | tail -5
```

Expected: `AttributeError: '_OfflineUnityAssistant' object has no attribute '_capture_after_action'`

- [ ] **Step 3: Add `_capture_after_action` to `_OfflineUnityAssistant`**

In `core/agent_chat.py`, add this method to `_OfflineUnityAssistant` after `_has_live_unity` (around L876):

```python
def _capture_after_action(self) -> dict[str, Any]:
    """Take a Game View + Scene View screenshot after a scene-modifying action.

    Returns a dict with ``gamePath`` and ``scenePath`` keys, or empty dict on failure.
    Used to provide visual proof after any action that changes the scene.
    """
    try:
        result = self.bridge.client.call_route(
            "graphics/capture",
            {"kind": "both"},
        )
        return dict(result or {})
    except Exception:
        return {}

def _capture_lines(self, capture: dict[str, Any]) -> list[str]:
    """Format capture paths as display lines for a reply message."""
    lines: list[str] = []
    game_path = capture.get("gamePath") or capture.get("game_path")
    scene_path = capture.get("scenePath") or capture.get("scene_path")
    if game_path:
        lines.append(f"📷 Game view: `{game_path}`")
    if scene_path:
        lines.append(f"📷 Scene view: `{scene_path}`")
    return lines
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "capture" -v 2>&1 | tail -8
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add cli_anything/unity_mcp/core/agent_chat.py cli_anything/unity_mcp/tests/test_chat_e2e.py
git commit -m "feat(chat): add visual capture helper for scene-action proof"
```

---

## Task 2: Player prototype flow — build a player from a single chat message

**Files:**
- Modify: `cli_anything/unity_mcp/core/agent_chat.py`
- Test: `cli_anything/unity_mcp/tests/test_chat_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
def test_player_prototype_reply_creates_go_and_returns_steps(self):
    """_build_player_prototype_reply calls create GO, add CharacterController, create script."""
    from unittest.mock import MagicMock, patch, call
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        client = MagicMock()
        client.call_route.return_value = {"name": "Player", "id": "abc123"}
        bridge = MagicMock()
        bridge.client = client
        bridge.project_path = tmp
        assistant = _OfflineUnityAssistant(bridge)

        # Mock _run_embedded_cli to avoid needing full CLI
        assistant._run_embedded_cli = MagicMock(return_value={"success": True, "path": "/Assets/Scripts/PlayerMovement.cs"})
        assistant._capture_after_action = MagicMock(return_value={"gamePath": "/tmp/game.png"})

        result = assistant._build_player_prototype_reply()

        # Should have called gameobject/create
        create_calls = [c for c in client.call_route.call_args_list if c[0][0] == "gameobject/create"]
        assert len(create_calls) >= 1
        # Should have called component/add for CharacterController
        cc_calls = [c for c in client.call_route.call_args_list
                    if c[0][0] == "component/add" and "CharacterController" in str(c)]
        assert len(cc_calls) >= 1
        # Should have tried to capture
        assistant._capture_after_action.assert_called_once()
        # Reply should mention Player
        assert "Player" in result or "player" in result.lower()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py::ChatE2ETests::test_player_prototype_reply_creates_go_and_returns_steps -v 2>&1 | tail -5
```

Expected: `AttributeError: '_OfflineUnityAssistant' object has no attribute '_build_player_prototype_reply'`

- [ ] **Step 3: Add `_MOVEMENT_SCRIPT_TEMPLATE` class constant and `_build_player_prototype_reply`**

Add the class constant near the top of `_OfflineUnityAssistant` (after `_PLAYER_TOKENS`):

```python
_MOVEMENT_SCRIPT_TEMPLATE: str = """\
using UnityEngine;

[RequireComponent(typeof(CharacterController))]
public class PlayerMovement : MonoBehaviour
{{
    [SerializeField] private float speed = 5f;
    [SerializeField] private float jumpHeight = 1.5f;
    [SerializeField] private float gravity = -9.81f;

    private CharacterController _controller;
    private Vector3 _velocity;
    private bool _isGrounded;

    private void Awake() => _controller = GetComponent<CharacterController>();

    private void Update()
    {{
        _isGrounded = _controller.isGrounded;
        if (_isGrounded && _velocity.y < 0) _velocity.y = -2f;

        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        Vector3 move = transform.right * h + transform.forward * v;
        _controller.Move(move * speed * Time.deltaTime);

        if (Input.GetButtonDown("Jump") && _isGrounded)
            _velocity.y = Mathf.Sqrt(jumpHeight * -2f * gravity);

        _velocity.y += gravity * Time.deltaTime;
        _controller.Move(_velocity * Time.deltaTime);
    }}
}}
"""
```

Add the method to `_OfflineUnityAssistant` after `_create_primitive_reply`:

```python
def _build_player_prototype_reply(self, name: str = "Player") -> str:
    """Build a player GO with CharacterController + movement script in one flow.

    Steps:
    1. Create empty GameObject named `name`
    2. Add CharacterController component
    3. Create PlayerMovement.cs script
    4. Add script component to the GO
    5. Capture scene screenshot for visual proof
    """
    self._set_status("Creating player GameObject")
    steps_done: list[str] = []
    errors: list[str] = []

    # Step 1 — create GO
    try:
        self.bridge.client.call_route("gameobject/create", {"name": name})
        steps_done.append(f"✅ Created GameObject `{name}`")
    except Exception as exc:
        errors.append(f"❌ Could not create GameObject: {exc}")
        return "\n".join(errors) + "\n\nMake sure a Unity editor is connected."

    # Step 2 — add CharacterController
    self._set_status("Adding CharacterController")
    try:
        self.bridge.client.call_route(
            "component/add",
            {"gameObjectName": name, "componentType": "UnityEngine.CharacterController"},
        )
        steps_done.append("✅ Added `CharacterController`")
    except Exception as exc:
        errors.append(f"⚠️  CharacterController: {exc}")

    # Step 3 — create movement script
    self._set_status("Creating PlayerMovement script")
    script_path = "Assets/Scripts/PlayerMovement.cs"
    try:
        result = self._run_embedded_cli([
            "script", "create",
            "--name", "PlayerMovement",
            "--path", script_path,
            "--content", self._MOVEMENT_SCRIPT_TEMPLATE,
        ])
        actual_path = (result or {}).get("path") or script_path
        steps_done.append(f"✅ Created `{actual_path}`")
    except Exception as exc:
        errors.append(f"⚠️  Script creation: {exc}")
        actual_path = script_path

    # Step 4 — attach script component
    self._set_status("Attaching PlayerMovement to GameObject")
    try:
        self.bridge.client.call_route(
            "component/add",
            {"gameObjectName": name, "componentType": "PlayerMovement"},
        )
        steps_done.append("✅ Attached `PlayerMovement` to GameObject")
    except Exception as exc:
        errors.append(f"⚠️  Script attach: {exc}")

    # Step 5 — visual proof
    self._set_status("Capturing scene")
    capture = self._capture_after_action()
    capture_lines = self._capture_lines(capture)

    lines = [f"Built player prototype `{name}`:", ""] + steps_done
    if errors:
        lines += [""] + errors
    if capture_lines:
        lines += [""] + capture_lines
    lines += [
        "",
        "Next: press Play and test movement with WASD + Space.",
        "Ask me to adjust speed, add a camera follow, or write tests for the controller.",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Wire `_build_player_prototype_reply` into `_dispatch`**

In `_dispatch`, add before the `create_match` line (around L112):

```python
if any(phrase in lowered for phrase in (
    "build a player", "create a player", "add a player",
    "player controller", "player prototype", "make a player",
    "build player", "create player",
)):
    player_name = "Player"
    # extract custom name if given: "build a player called Hero"
    import re as _re
    name_match = _re.search(r"(?:called|named|name[d]?)\s+([A-Za-z_]\w*)", normalized)
    if name_match:
        player_name = name_match.group(1)
    return self._build_player_prototype_reply(player_name)
```

- [ ] **Step 5: Run tests**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "player" -v 2>&1 | tail -8
```

Expected: test passes.

- [ ] **Step 6: Run full suite**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add cli_anything/unity_mcp/core/agent_chat.py cli_anything/unity_mcp/tests/test_chat_e2e.py
git commit -m "feat(chat): add player prototype flow with visual proof"
```

---

## Task 3: Script create + attach flow

**Files:**
- Modify: `cli_anything/unity_mcp/core/agent_chat.py`
- Test: `cli_anything/unity_mcp/tests/test_chat_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_script_attach_reply_creates_and_attaches(self):
    """_build_script_attach_reply creates a script and attaches it to a named GO."""
    from unittest.mock import MagicMock
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

    client = MagicMock()
    client.call_route.return_value = {"success": True}
    bridge = MagicMock()
    bridge.client = client
    assistant = _OfflineUnityAssistant(bridge)
    assistant._run_embedded_cli = MagicMock(return_value={"path": "Assets/Scripts/Rotate.cs"})
    assistant._capture_after_action = MagicMock(return_value={})

    result = assistant._build_script_attach_reply("Rotate", "Cube", "rotates the object on Y axis")

    assert "Rotate" in result
    assert "Cube" in result
    assistant._run_embedded_cli.assert_called_once()
    cc_calls = [c for c in client.call_route.call_args_list if "component/add" in str(c)]
    assert len(cc_calls) >= 1
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py::ChatE2ETests::test_build_script_attach_reply_creates_and_attaches -v 2>&1 | tail -5
```

Expected: `AttributeError`

- [ ] **Step 3: Add `_build_script_attach_reply`**

Add to `_OfflineUnityAssistant` after `_build_player_prototype_reply`:

```python
def _build_script_attach_reply(
    self,
    script_name: str,
    go_name: str,
    description: str = "",
) -> str:
    """Create a C# script and attach it to a named GameObject.

    Args:
        script_name: PascalCase class name (e.g. ``Rotate``)
        go_name: Name of the target GameObject in the scene
        description: One-line intent used to generate minimal script body
    """
    self._set_status(f"Creating {script_name}.cs")
    steps_done: list[str] = []
    errors: list[str] = []
    script_path = f"Assets/Scripts/{script_name}.cs"

    # Build minimal script body from description
    comment = f"// {description}" if description else "// TODO: implement"
    script_content = (
        f"using UnityEngine;\n\n"
        f"public class {script_name} : MonoBehaviour\n{{\n"
        f"    {comment}\n"
        f"    private void Start() {{ }}\n"
        f"    private void Update() {{ }}\n"
        f"}}\n"
    )

    try:
        result = self._run_embedded_cli([
            "script", "create",
            "--name", script_name,
            "--path", script_path,
            "--content", script_content,
        ])
        actual_path = (result or {}).get("path") or script_path
        steps_done.append(f"✅ Created `{actual_path}`")
    except Exception as exc:
        errors.append(f"❌ Script creation failed: {exc}")
        return "\n".join(errors)

    self._set_status(f"Attaching {script_name} to {go_name}")
    try:
        self.bridge.client.call_route(
            "component/add",
            {"gameObjectName": go_name, "componentType": script_name},
        )
        steps_done.append(f"✅ Attached `{script_name}` to `{go_name}`")
    except Exception as exc:
        errors.append(f"⚠️  Attach failed: {exc}")

    capture = self._capture_after_action()
    capture_lines = self._capture_lines(capture)

    lines = [f"Created and attached `{script_name}` to `{go_name}`:", ""] + steps_done
    if errors:
        lines += [""] + errors
    if capture_lines:
        lines += [""] + capture_lines
    lines += ["", f"Open `{script_path}` to implement the logic."]
    return "\n".join(lines)
```

- [ ] **Step 4: Wire into `_dispatch`**

Add to `_dispatch` before the `create_match` check:

```python
# "create a Rotate script and attach it to Cube"
_script_attach_re = re.compile(
    r"(?:create|add|write|make)\s+(?:a\s+)?([A-Za-z_]\w*)\s+script"
    r"(?:\s+(?:and\s+)?(?:attach|add)\s+(?:it\s+)?(?:to\s+)?([A-Za-z_]\w*))?",
    re.IGNORECASE,
)
script_match = _script_attach_re.search(normalized)
if script_match:
    sname = script_match.group(1)
    go = script_match.group(2) or "GameObject"
    return self._build_script_attach_reply(sname, go, normalized)
```

- [ ] **Step 5: Run tests**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "script_attach" -v 2>&1 | tail -5
```

Expected: passes.

- [ ] **Step 6: Run full suite + commit**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
git add cli_anything/unity_mcp/core/agent_chat.py cli_anything/unity_mcp/tests/test_chat_e2e.py
git commit -m "feat(chat): add script create+attach flow with visual proof"
```

---

## Task 4: Watchdog mode — proactive project health monitoring

**Files:**
- Modify: `cli_anything/unity_mcp/core/agent_chat.py` (`ChatBridge` class)
- Test: `cli_anything/unity_mcp/tests/test_chat_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
def test_watchdog_thread_starts_and_stops(self):
    """ChatBridge watchdog thread starts on run() and stops on stop()."""
    import threading, tempfile, time
    from unittest.mock import MagicMock
    from cli_anything.unity_mcp.core.agent_chat import ChatBridge
    from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

    with tempfile.TemporaryDirectory() as tmp:
        client = MagicMock(spec=FileIPCClient)
        bridge = ChatBridge(tmp, client, poll_interval=0.05, watchdog_interval=0.1)
        bridge._ensure_ready()

        bridge._start_watchdog()
        time.sleep(0.05)
        assert bridge._watchdog_thread is not None
        assert bridge._watchdog_thread.is_alive()

        bridge._stop_watchdog()
        bridge._watchdog_thread.join(timeout=1.0)
        assert not bridge._watchdog_thread.is_alive()

def test_watchdog_does_not_post_duplicate_findings(self):
    """Watchdog suppresses findings already surfaced in this session."""
    import tempfile
    from unittest.mock import MagicMock, patch
    from cli_anything.unity_mcp.core.agent_chat import ChatBridge
    from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

    with tempfile.TemporaryDirectory() as tmp:
        client = MagicMock(spec=FileIPCClient)
        bridge = ChatBridge(tmp, client)
        bridge._ensure_ready()

        # Simulate that "No AudioListener in scene" was already surfaced
        bridge._watchdog_surfaced.add("No AudioListener in scene")

        findings = [{"title": "No AudioListener in scene", "severity": "warning"}]
        new_findings = bridge._watchdog_filter_new(findings)
        assert new_findings == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "watchdog" -v 2>&1 | tail -8
```

Expected: `AttributeError` — no watchdog methods yet.

- [ ] **Step 3: Add watchdog support to `ChatBridge.__init__`**

In `ChatBridge.__init__`, add after `self._last_status_write = 0.0`:

```python
self._watchdog_interval: float = watchdog_interval
self._watchdog_thread: "threading.Thread | None" = None
self._watchdog_running = False
self._watchdog_surfaced: set[str] = set()  # finding titles already shown this session
```

Update `ChatBridge.__init__` signature to accept `watchdog_interval`:

```python
def __init__(
    self,
    project_path: str | Path,
    file_client: FileIPCClient,
    handler: Optional[Callable[[str, "ChatBridge"], None]] = None,
    embedded_options: "EmbeddedCLIOptions | None" = None,
    poll_interval: float = 0.25,
    watchdog_interval: float = 60.0,  # check project health every 60 seconds
) -> None:
```

Add `import threading` at the top of the file if not already present.

- [ ] **Step 4: Add watchdog methods to `ChatBridge`**

Add after `write_status`:

```python
def _watchdog_filter_new(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only findings not already surfaced this session."""
    new: list[dict[str, Any]] = []
    for finding in findings:
        key = str(finding.get("title") or "")
        if key and key not in self._watchdog_surfaced:
            new.append(finding)
    return new

def _watchdog_surface_findings(self, findings: list[dict[str, Any]]) -> None:
    """Post proactive message for new findings, mark them as surfaced."""
    if not findings:
        return
    lines = ["👀 I noticed a few things while watching your project:", ""]
    for finding in findings[:3]:  # cap at 3 to avoid noise
        title = str(finding.get("title") or "Finding")
        detail = str(finding.get("detail") or "")
        severity = str(finding.get("severity") or "info")
        icon = "⚠️" if severity == "warning" else "🔴" if severity == "error" else "ℹ️"
        lines.append(f"{icon} **{title}**" + (f": {detail}" if detail else ""))
        self._watchdog_surfaced.add(title)
    lines += ["", "Ask me to fix any of these or run `inspect project` for the full picture."]
    self.append_message("ai", "\n".join(lines))

def _watchdog_loop(self) -> None:
    """Background thread: periodically run a lightweight project health check."""
    import time
    while self._watchdog_running:
        time.sleep(self._watchdog_interval)
        if not self._watchdog_running:
            break
        try:
            result = self._assistant._run_embedded_cli(["--json", "workflow", "quality-score"])
            findings = (result or {}).get("findings") or []
            new_findings = self._watchdog_filter_new(findings)
            self._watchdog_surface_findings(new_findings)
        except Exception:
            pass  # watchdog never crashes the bridge

def _start_watchdog(self) -> None:
    """Start the background watchdog thread."""
    import threading
    if self._watchdog_thread and self._watchdog_thread.is_alive():
        return
    self._watchdog_running = True
    self._watchdog_thread = threading.Thread(
        target=self._watchdog_loop,
        daemon=True,
        name="unity-mcp-watchdog",
    )
    self._watchdog_thread.start()

def _stop_watchdog(self) -> None:
    """Stop the watchdog thread."""
    self._watchdog_running = False
    if self._watchdog_thread:
        self._watchdog_thread.join(timeout=2.0)
        self._watchdog_thread = None
```

- [ ] **Step 5: Start watchdog in `run()` and stop in `stop()`**

In `ChatBridge.run()` (L1344), add after `self._running = True`:

```python
if self._watchdog_interval > 0:
    self._start_watchdog()
```

In `ChatBridge.stop()` (L1358), add:

```python
self._stop_watchdog()
```

- [ ] **Step 6: Run tests**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "watchdog" -v 2>&1 | tail -8
```

Expected: both watchdog tests pass.

- [ ] **Step 7: Run full suite + commit**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
git add cli_anything/unity_mcp/core/agent_chat.py cli_anything/unity_mcp/tests/test_chat_e2e.py
git commit -m "feat(chat): add watchdog background thread for proactive project health"
```

---

## Task 5: Autonomous goal mode — goal → plan → execute → verify

**Files:**
- Modify: `cli_anything/unity_mcp/core/agent_chat.py`
- Test: `cli_anything/unity_mcp/tests/test_chat_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
def test_autonomous_goal_reply_returns_plan_for_review(self):
    """_autonomous_goal_reply posts a plan and waits for user confirmation."""
    from unittest.mock import MagicMock, patch
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

    client = MagicMock()
    bridge = MagicMock()
    bridge.client = client
    assistant = _OfflineUnityAssistant(bridge)

    # Mock quality score to return some findings
    assistant._run_embedded_cli = MagicMock(return_value={
        "lensScores": [{"name": "systems", "score": 40, "findings": [
            {"title": "No EventSystem in scene", "severity": "error"},
            {"title": "No AudioListener in scene", "severity": "warning"},
        ]}]
    })

    result = assistant._autonomous_goal_reply("fix all the issues in my project")
    assert "plan" in result.lower() or "step" in result.lower() or "fix" in result.lower()
    assert "confirm" in result.lower() or "proceed" in result.lower() or "ready" in result.lower()

def test_autonomous_goal_detects_polish_intent(self):
    """_dispatch routes 'polish X' to autonomous goal handler."""
    from unittest.mock import MagicMock, patch
    from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

    bridge = MagicMock()
    assistant = _OfflineUnityAssistant(bridge)
    assistant._autonomous_goal_reply = MagicMock(return_value="here is my plan")

    result = assistant._dispatch("polish the combat feel")
    assistant._autonomous_goal_reply.assert_called_once_with("polish the combat feel")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "autonomous" -v 2>&1 | tail -5
```

Expected: `AttributeError`

- [ ] **Step 3: Add `_AUTONOMOUS_TRIGGERS` and `_autonomous_goal_reply`**

Add to `_OfflineUnityAssistant` class constants:

```python
_AUTONOMOUS_TRIGGERS: tuple[str, ...] = (
    "fix all", "fix everything", "fix the issues",
    "polish", "improve the", "clean up",
    "make it better", "optimize", "refactor",
    "do a pass", "run a pass",
)
```

Add method after `_best_effort_agent_reply`:

```python
def _autonomous_goal_reply(self, goal: str) -> str:
    """Autonomous mode: audit current state, build a plan, ask for confirmation.

    This is the entry point for open-ended goals like "polish the combat feel"
    or "fix all the issues in my project". It:
    1. Runs a quality score audit to understand current state
    2. Derives a prioritized list of bounded fix steps from the findings
    3. Presents the plan and asks the user to confirm before executing

    Execution happens in a follow-up message when the user replies "yes" / "go".
    """
    self._set_status("Auditing project for goal planning")

    # Get current quality score + findings
    try:
        score_result = self._run_embedded_cli(["--json", "workflow", "quality-score"])
    except Exception as exc:
        return f"I couldn't audit the project to build a plan: {exc}\n\nMake sure Unity is connected and try again."

    lens_scores = (score_result or {}).get("lensScores") or []
    all_findings: list[dict[str, Any]] = []
    for lens in lens_scores:
        for finding in (lens.get("findings") or []):
            all_findings.append({**finding, "_lens": lens.get("name", "")})

    if not all_findings:
        return (
            f"I ran an audit for goal: **{goal}**\n\n"
            "Good news — I couldn't find any actionable issues right now. "
            "The project looks healthy. Ask me to dig deeper into a specific area if you want a closer look."
        )

    # Sort by severity (errors first, then warnings)
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    all_findings.sort(key=lambda f: severity_rank.get(str(f.get("severity") or "info"), 2))

    # Build plan steps (cap at 5 for a first autonomous pass)
    plan_steps = all_findings[:5]

    lines = [
        f"Goal: **{goal}**",
        "",
        "Here's my plan based on the current audit:",
        "",
    ]
    for i, finding in enumerate(plan_steps, 1):
        title = str(finding.get("title") or "Fix")
        detail = str(finding.get("detail") or "")
        severity = str(finding.get("severity") or "info")
        icon = "🔴" if severity == "error" else "⚠️" if severity == "warning" else "ℹ️"
        lines.append(f"{i}. {icon} **{title}**" + (f" — {detail}" if detail else ""))

    lines += [
        "",
        "Reply **yes** or **go** and I'll execute these steps one by one with visual proof after each.",
        "Or tell me to skip any step and I'll adjust the plan.",
    ]

    # Store pending plan in bridge state for follow-up execution
    self.bridge._pending_autonomous_plan = plan_steps
    self.bridge._pending_autonomous_goal = goal

    return "\n".join(lines)
```

- [ ] **Step 4: Add pending plan execution to `_dispatch`**

Add to the start of `_dispatch`, before the greeting check:

```python
# Check for pending autonomous plan confirmation
pending_plan = getattr(self.bridge, "_pending_autonomous_plan", None)
if pending_plan and lowered in {"yes", "go", "proceed", "do it", "execute", "run it", "confirm"}:
    return self._execute_pending_autonomous_plan()
```

Add the execution method:

```python
def _execute_pending_autonomous_plan(self) -> str:
    """Execute the pending autonomous plan step by step."""
    plan = getattr(self.bridge, "_pending_autonomous_plan", [])
    goal = getattr(self.bridge, "_pending_autonomous_goal", "your goal")

    if not plan:
        return "No pending plan to execute. Try stating your goal again."

    # Clear pending plan
    self.bridge._pending_autonomous_plan = None
    self.bridge._pending_autonomous_goal = None

    self._set_status("Executing plan")
    results_lines = [f"Executing plan for: **{goal}**", ""]

    for i, finding in enumerate(plan, 1):
        title = str(finding.get("title") or "Fix")
        lens = str(finding.get("_lens") or "systems")
        self._set_status(f"Step {i}: {title}")
        try:
            fix_result = self._run_embedded_cli([
                "--json", "workflow", "quality-fix",
                "--lens", lens,
                "--fix", title.lower().replace(" ", "-"),
                "--apply",
            ])
            success = (fix_result or {}).get("applied") or (fix_result or {}).get("success")
            if success:
                results_lines.append(f"✅ Step {i}: {title}")
            else:
                skip_reason = (fix_result or {}).get("skippedReason") or "not applicable"
                results_lines.append(f"⏭️  Step {i}: {title} — skipped ({skip_reason})")
        except Exception as exc:
            results_lines.append(f"⚠️  Step {i}: {title} — {exc}")

    capture = self._capture_after_action()
    capture_lines = self._capture_lines(capture)

    if capture_lines:
        results_lines += [""] + capture_lines
    results_lines += ["", "Done. Ask me to audit again to see the score delta."]

    return "\n".join(results_lines)
```

- [ ] **Step 5: Wire autonomous triggers into `_dispatch`**

Add near the end of `_dispatch`, just before `_best_effort_agent_reply`:

```python
if any(phrase in lowered for phrase in self._AUTONOMOUS_TRIGGERS):
    return self._autonomous_goal_reply(normalized)
```

- [ ] **Step 6: Run tests**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -k "autonomous" -v 2>&1 | tail -8
```

Expected: both tests pass.

- [ ] **Step 7: Run full suite + commit**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
git add cli_anything/unity_mcp/core/agent_chat.py cli_anything/unity_mcp/tests/test_chat_e2e.py
git commit -m "feat(chat): add autonomous goal mode with plan-then-execute flow"
```

---

## Verification

After all tasks:

```bash
# Full test suite
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5

# Confirm new capabilities visible
py -3.12 -c "
from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant, ChatBridge
print('_capture_after_action:', hasattr(_OfflineUnityAssistant, '_capture_after_action'))
print('_build_player_prototype_reply:', hasattr(_OfflineUnityAssistant, '_build_player_prototype_reply'))
print('_build_script_attach_reply:', hasattr(_OfflineUnityAssistant, '_build_script_attach_reply'))
print('_autonomous_goal_reply:', hasattr(_OfflineUnityAssistant, '_autonomous_goal_reply'))
print('_start_watchdog:', hasattr(ChatBridge, '_start_watchdog'))
print('_watchdog_loop:', hasattr(ChatBridge, '_watchdog_loop'))
"
```

Expected: all `True`.

**Exit gate:** from a single chat message:
- "build a player that can walk" → creates GO + CharacterController + script + screenshot
- "fix all the issues" → audits → plan → waits for confirmation → executes → screenshot
- Watchdog proactively messages when quality-score reveals new findings
