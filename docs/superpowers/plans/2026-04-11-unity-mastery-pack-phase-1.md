# Unity Mastery Pack Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class Unity expert layer to the CLI with project-brain context, specialist lenses, quality scoring, expert audit workflows, and a bounded safe-fix surface.

**Architecture:** Build a shared expert-context bundle on top of the existing project scan and Unity bridge data, evaluate that context through specialist lens modules, and expose the results through new `workflow` commands plus richer developer profiles.

**Tech Stack:** Python 3.11+, Click CLI, existing Unity MCP backend and workflow modules, `unittest`, Unity File IPC / plugin bridge compatibility.

---

## File Map

- Create: `cli_anything/unity_mcp/core/expert_context.py`
- Create: `cli_anything/unity_mcp/core/expert_lenses.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/__init__.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/director.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/animation.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/tech_art.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/ui.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/level_art.py`
- Create: `cli_anything/unity_mcp/core/expert_fixes.py`
- Modify: `cli_anything/unity_mcp/core/developer_profiles.py`
- Modify: `cli_anything/unity_mcp/commands/workflow.py`
- Modify: `cli_anything/unity_mcp/commands/_shared.py`
- Modify: `cli_anything/unity_mcp/tests/test_core.py`
- Modify: `cli_anything/unity_mcp/tests/test_full_e2e.py`
- Modify: `README.md`, `AGENTS.md`, `TODO.md`, `CHANGELOG.md`

### Shipping Scope

Ship these first:
- `workflow expert-audit --lens <lens>`
- `workflow scene-critique`
- `workflow quality-score`
- `workflow quality-fix` for `guidance`, `sandbox-scene`, and `ui-canvas-scaler`

Defer `quality-fix --fix anchors` until a follow-up plan adds stronger RectTransform mutation support.

---

### Task 1: Expert Profiles, Lens Registry, And Context Builder

**Files:**
- Create: `cli_anything/unity_mcp/core/expert_lenses.py`
- Create: `cli_anything/unity_mcp/core/expert_context.py`
- Modify: `cli_anything/unity_mcp/core/developer_profiles.py`
- Test: `cli_anything/unity_mcp/tests/test_core.py`

- [ ] **Step 1: Write the failing tests**

```python
class UnityExpertFoundationTests(unittest.TestCase):
    def test_developer_profiles_include_unity_expert_profiles(self) -> None:
        store = DeveloperProfileStore(path=Path("test-developer-profiles.json"))
        names = {profile.name for profile in store.list_profiles().profiles}
        self.assertTrue({"director", "animator", "tech-artist", "ui-designer", "level-designer"} <= names)

    def test_build_expert_context_merges_audit_and_inspect(self) -> None:
        inspect_payload = {"summary": {"projectName": "DemoGame", "projectPath": "C:/Projects/DemoGame", "activeScene": "Arena", "renderPipeline": "URP"}, "state": {"isPlaying": False}, "scene": {"activeScene": "Arena"}}
        audit_report = {"summary": {"projectName": "DemoGame", "renderPipeline": "URP", "materialCount": 8, "modelCount": 2, "animationCount": 1, "testScriptCount": 0}, "topRecommendations": [{"title": "Add tests", "detail": "No tests found."}]}
        context = build_expert_context(inspect_payload=inspect_payload, audit_report=audit_report, lens_name="director")
        self.assertEqual(context["project"]["name"], "DemoGame")
        self.assertEqual(context["assets"]["materialCount"], 8)
        self.assertEqual(context["lens"]["name"], "director")
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertFoundationTests -v
```

Expected: missing profile names and `build_expert_context` / lens registry symbols.

- [ ] **Step 3: Implement the registry, profiles, and context builder**

`cli_anything/unity_mcp/core/expert_lenses.py`

```python
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class ExpertLens:
    name: str
    description: str
    focus: str
    audit: Callable[[dict[str, Any]], dict[str, Any]]
    supported_fix_types: tuple[str, ...] = field(default_factory=tuple)

def grade_score(score: int) -> str:
    if score < 40: return "poor"
    if score < 60: return "weak"
    if score < 75: return "workable"
    if score < 90: return "strong"
    return "excellent"
```

`cli_anything/unity_mcp/core/expert_context.py`

```python
def build_expert_context(*, inspect_payload: dict | None, audit_report: dict | None, lens_name: str, capture_summary: dict | None = None) -> dict:
    inspect_payload = dict(inspect_payload or {})
    audit_report = dict(audit_report or {})
    inspect_summary = dict(inspect_payload.get("summary") or {})
    audit_summary = dict(audit_report.get("summary") or {})
    return {
        "lens": {"name": lens_name},
        "project": {
            "name": inspect_summary.get("projectName") or audit_summary.get("projectName"),
            "path": inspect_summary.get("projectPath") or audit_report.get("projectRoot"),
            "renderPipeline": inspect_summary.get("renderPipeline") or audit_summary.get("renderPipeline"),
            "activeScene": inspect_summary.get("activeScene") or audit_summary.get("activeScene"),
        },
        "state": dict(inspect_payload.get("state") or {}),
        "scene": dict(inspect_payload.get("scene") or {}),
        "assets": {
            "materialCount": int(audit_summary.get("materialCount") or 0),
            "modelCount": int(audit_summary.get("modelCount") or 0),
            "animationCount": int(audit_summary.get("animationCount") or 0),
            "testScriptCount": int(audit_summary.get("testScriptCount") or 0),
        },
        "recommendations": list(audit_report.get("topRecommendations") or []),
        "raw": {"inspect": inspect_payload, "audit": audit_report, "captures": dict(capture_summary or {})},
    }
```

- [ ] **Step 4: Run the tests again and verify they pass**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertFoundationTests -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add cli_anything/unity_mcp/core/expert_lenses.py cli_anything/unity_mcp/core/expert_context.py cli_anything/unity_mcp/core/developer_profiles.py cli_anything/unity_mcp/tests/test_core.py
git commit -m "feat: add Unity expert foundations"
```

---

### Task 2: Implement The Specialist Lens Rules

**Files:**
- Create: `cli_anything/unity_mcp/core/expert_rules/__init__.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/director.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/animation.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/tech_art.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/ui.py`
- Create: `cli_anything/unity_mcp/core/expert_rules/level_art.py`
- Test: `cli_anything/unity_mcp/tests/test_core.py`

- [ ] **Step 1: Write the failing lens tests**

```python
class UnityExpertLensTests(unittest.TestCase):
    def test_director_lens_flags_missing_guidance_and_tests(self) -> None:
        context = {"assets": {"testScriptCount": 0}, "raw": {"audit": {"guidance": {"hasAgentsMd": False, "hasContextFolder": False}}}}
        result = audit_director_lens(context)
        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Missing project guidance", titles)
        self.assertIn("No test coverage detected", titles)

    def test_animation_lens_flags_models_without_animation(self) -> None:
        result = audit_animation_lens({"assets": {"modelCount": 3, "animationCount": 0}})
        self.assertIn("Models found without animation evidence", {item["title"] for item in result["findings"]})

    def test_tech_art_lens_flags_importer_mismatches(self) -> None:
        context = {"raw": {"audit": {"assetScan": {"importerAudit": {"potentialNormalMapMisconfiguredCount": 1, "potentialSpriteMisconfiguredCount": 1}}}}}
        result = audit_tech_art_lens(context)
        self.assertIn("Texture importer mismatches detected", {item["title"] for item in result["findings"]})

    def test_ui_lens_flags_canvas_without_scaler(self) -> None:
        context = {"raw": {"inspect": {"hierarchy": {"nodes": [{"name": "HUD", "components": ["Canvas", "GraphicRaycaster"]}]}}}}
        result = audit_ui_lens(context)
        self.assertIn("Canvas without CanvasScaler", {item["title"] for item in result["findings"]})
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertLensTests -v
```

Expected: missing imports and missing audit functions.

- [ ] **Step 3: Implement the lens modules**

`cli_anything/unity_mcp/core/expert_rules/director.py`

```python
from ..expert_lenses import grade_score

def audit_director_lens(context: dict) -> dict:
    findings: list[dict] = []
    guidance = dict(((context.get("raw") or {}).get("audit") or {}).get("guidance") or {})
    assets = dict(context.get("assets") or {})
    if not guidance.get("hasAgentsMd") or not guidance.get("hasContextFolder"):
        findings.append({"severity": "high", "title": "Missing project guidance", "detail": "The project is missing AGENTS.md or Assets/MCP/Context guidance."})
    if int(assets.get("testScriptCount") or 0) == 0:
        findings.append({"severity": "medium", "title": "No test coverage detected", "detail": "The project audit found no test scripts."})
    score = max(35, 92 - (len(findings) * 18))
    return {"lens": "director", "score": score, "grade": grade_score(score), "confidence": 0.78, "findings": findings}
```

`cli_anything/unity_mcp/core/expert_rules/animation.py`

```python
from ..expert_lenses import grade_score

def audit_animation_lens(context: dict) -> dict:
    findings: list[dict] = []
    assets = dict(context.get("assets") or {})
    if int(assets.get("modelCount") or 0) > 0 and int(assets.get("animationCount") or 0) == 0:
        findings.append({"severity": "medium", "title": "Models found without animation evidence", "detail": "Models exist, but the audit did not find clips or controller coverage."})
    score = max(40, 90 - (len(findings) * 20))
    return {"lens": "animation", "score": score, "grade": grade_score(score), "confidence": 0.70, "findings": findings}
```

`cli_anything/unity_mcp/core/expert_rules/tech_art.py`

```python
from ..expert_lenses import grade_score

def audit_tech_art_lens(context: dict) -> dict:
    findings: list[dict] = []
    importer_audit = dict((((context.get("raw") or {}).get("audit") or {}).get("assetScan") or {}).get("importerAudit") or {})
    if int(importer_audit.get("potentialNormalMapMisconfiguredCount") or 0) > 0 or int(importer_audit.get("potentialSpriteMisconfiguredCount") or 0) > 0:
        findings.append({"severity": "medium", "title": "Texture importer mismatches detected", "detail": "Likely normal-map or sprite-import mismatches were found."})
    score = max(45, 92 - (len(findings) * 16))
    return {"lens": "tech-art", "score": score, "grade": grade_score(score), "confidence": 0.82, "findings": findings}
```

`cli_anything/unity_mcp/core/expert_rules/ui.py`

```python
from ..expert_lenses import grade_score

def audit_ui_lens(context: dict) -> dict:
    findings: list[dict] = []
    nodes = list((((context.get("raw") or {}).get("inspect") or {}).get("hierarchy") or {}).get("nodes") or [])
    for node in nodes:
        components = set(node.get("components") or [])
        if "Canvas" in components and "CanvasScaler" not in components:
            findings.append({"severity": "high", "title": "Canvas without CanvasScaler", "detail": f"Canvas `{node.get('name')}` has no CanvasScaler."})
    score = max(40, 90 - (len(findings) * 20))
    return {"lens": "ui", "score": score, "grade": grade_score(score), "confidence": 0.76, "findings": findings}
```

`cli_anything/unity_mcp/core/expert_rules/level_art.py`

```python
from ..expert_lenses import grade_score

def audit_level_art_lens(context: dict) -> dict:
    findings: list[dict] = []
    scene_stats = dict(((context.get("raw") or {}).get("inspect") or {}).get("sceneStats") or {})
    if int(scene_stats.get("totalMeshes") or 0) < 5:
        findings.append({"severity": "medium", "title": "Sparse scene composition", "detail": "The active scene has very low mesh density."})
    score = max(45, 91 - (len(findings) * 18))
    return {"lens": "level-art", "score": score, "grade": grade_score(score), "confidence": 0.68, "findings": findings}
```

- [ ] **Step 4: Run the tests again and verify they pass**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertLensTests -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add cli_anything/unity_mcp/core/expert_rules cli_anything/unity_mcp/tests/test_core.py
git commit -m "feat: add Unity expert lens rules"
```

---

### Task 3: Add Safe Fix Planning And Workflow Commands

**Files:**
- Create: `cli_anything/unity_mcp/core/expert_fixes.py`
- Modify: `cli_anything/unity_mcp/commands/workflow.py`
- Modify: `cli_anything/unity_mcp/commands/_shared.py`
- Test: `cli_anything/unity_mcp/tests/test_core.py`
- Test: `cli_anything/unity_mcp/tests/test_full_e2e.py`

- [ ] **Step 1: Write the failing fix-planner and workflow tests**

```python
class UnityExpertWorkflowTests(unittest.TestCase):
    def test_build_quality_fix_plan_supports_guidance_and_sandbox(self) -> None:
        context = {"project": {"path": "C:/Projects/DemoGame"}}
        guidance_plan = build_quality_fix_plan(context=context, lens_name="director", fix_name="guidance")
        sandbox_plan = build_quality_fix_plan(context=context, lens_name="level-art", fix_name="sandbox-scene")
        self.assertEqual(guidance_plan["command"][0:2], ["workflow", "bootstrap-guidance"])
        self.assertEqual(sandbox_plan["command"][0:2], ["workflow", "create-sandbox-scene"])

    def test_workflow_expert_audit_returns_lens_result(self) -> None:
        options = EmbeddedCLIOptions()
        payload = run_cli_json(["workflow", "expert-audit", "--lens", "director", "C:/Projects/DemoGame"], options)
        self.assertEqual(payload["lens"]["name"], "director")
        self.assertIn("score", payload)
```

- [ ] **Step 2: Run the tests and verify they fail**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertWorkflowTests cli_anything.unity_mcp.tests.test_full_e2e.UnityExpertWorkflowTests -v
```

Expected: missing planner and no such command errors.

- [ ] **Step 3: Implement fix planning and commands**

`cli_anything/unity_mcp/core/expert_fixes.py`

```python
from .expert_lenses import iter_builtin_expert_lenses

def build_quality_fix_plan(*, context: dict, lens_name: str, fix_name: str) -> dict:
    lens_map = {lens.name: lens for lens in iter_builtin_expert_lenses()}
    lens = lens_map.get(lens_name)
    if lens is None:
        raise ValueError(f"Unknown lens: {lens_name}")
    if fix_name not in lens.supported_fix_types:
        raise ValueError(f"Fix `{fix_name}` is not supported for lens `{lens_name}`.")
    project_path = ((context.get("project") or {}).get("path")) or ""
    if fix_name == "guidance":
        return {"mode": "workflow", "command": ["workflow", "bootstrap-guidance", project_path, "--write"]}
    if fix_name == "sandbox-scene":
        return {"mode": "workflow", "command": ["workflow", "create-sandbox-scene", "--open"]}
    if fix_name == "ui-canvas-scaler":
        return {"mode": "preview", "message": "Add CanvasScaler normalization route before auto-applying this fix."}
    raise ValueError(f"Unhandled fix: {fix_name}")
```

`cli_anything/unity_mcp/commands/workflow.py`

```python
@workflow_group.command("expert-audit")
@click.argument("project_root", required=False, type=click.Path(file_okay=False, path_type=Path))
@click.option("--lens", "lens_name", required=True, type=click.Choice(["director", "animation", "tech-art", "ui", "level-art"]))
@click.option("--port", type=int, default=None)
@click.pass_context
def workflow_expert_audit_command(ctx: click.Context, project_root: Path | None, lens_name: str, port: int | None) -> None:
    def _callback() -> dict[str, Any]:
        inspect_payload = None
        if project_root is None:
            inspect_payload = require_workflow_success(ctx.obj.backend.call_route_with_recovery("workflow/inspect", port=port))
        target_root = project_root or Path((inspect_payload.get("summary") or {}).get("projectPath"))
        audit_report = build_asset_audit_report(target_root, inspect_payload=inspect_payload)
        context = build_expert_context(inspect_payload=inspect_payload, audit_report=audit_report, lens_name=lens_name)
        result = run_expert_lens_audit(lens_name, context)
        return {"available": True, "lens": {"name": lens_name}, **result, "contextSummary": context["project"]}
    _run_and_emit(ctx, _callback)
```

- [ ] **Step 4: Run the tests again and verify they pass**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core.UnityExpertWorkflowTests cli_anything.unity_mcp.tests.test_full_e2e.UnityExpertWorkflowTests -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add cli_anything/unity_mcp/core/expert_fixes.py cli_anything/unity_mcp/commands/workflow.py cli_anything/unity_mcp/commands/_shared.py cli_anything/unity_mcp/tests/test_core.py cli_anything/unity_mcp/tests/test_full_e2e.py
git commit -m "feat: add Unity expert audit workflows"
```

---

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `TODO.md`
- Modify: `CHANGELOG.md`
- Test: `cli_anything/unity_mcp/tests/test_core.py`
- Test: `cli_anything/unity_mcp/tests/test_full_e2e.py`

- [ ] **Step 1: Update the user-facing docs**

`README.md`

```md
## Unity Mastery Pack (Phase 1)

The CLI now has a first-class content-quality expert layer:

- `workflow expert-audit --lens director`
- `workflow expert-audit --lens animation`
- `workflow expert-audit --lens tech-art`
- `workflow expert-audit --lens ui`
- `workflow expert-audit --lens level-art`
- `workflow scene-critique`
- `workflow quality-score`
- `workflow quality-fix`

This layer is evidence-driven. It uses project scan data, live Unity bridge state, and bounded rules instead of pretending to be an all-knowing game model.
```

`AGENTS.md`

```md
- Use `workflow expert-audit --lens <lens>` when the user asks for stronger content direction, animation critique, UI/HUD review, or technical-art advice.
- Prefer `director` for overall direction, `animation` for rigs/controllers, `tech-art` for materials/textures, `ui` for canvases/HUDs, and `level-art` for scene readability.
```

- [ ] **Step 2: Run the full test suite**

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e
```

Expected: `OK`

- [ ] **Step 3: Smoke-test the expert workflows**

```powershell
python -m cli_anything.unity_mcp --json workflow expert-audit --lens director C:/Projects/DemoGame
python -m cli_anything.unity_mcp --json workflow quality-score C:/Projects/DemoGame
python -m cli_anything.unity_mcp --json developer list
```

Expected: JSON payloads return a score, grade, findings, and the new specialist profiles appear in `developer list`.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md TODO.md CHANGELOG.md cli_anything/unity_mcp/tests/test_core.py cli_anything/unity_mcp/tests/test_full_e2e.py
git commit -m "docs: document Unity mastery phase 1"
```

---

## Self-Review

### Spec Coverage

- `project brain` is covered by Task 1.
- `specialist lenses` are covered by Tasks 1 and 2.
- `quality scores` are covered by Tasks 1 and 2.
- `expert workflows` are covered by Task 3.
- `safe recommendation and bounded auto-fix workflows` are covered by Task 3.
- `documentation and developer-profile support` are covered by Tasks 1 and 4.
- `benchmark/eval fixtures` are intentionally deferred to the next plan after the expert layer ships.

### Placeholder Scan

No `TODO`, `TBD`, or “implement later” placeholders remain in the execution steps.

### Type Consistency

- Lens names are consistent:
  - `director`
  - `animation`
  - `tech-art`
  - `ui`
  - `level-art`
- Safe-fix names are consistent:
  - `guidance`
  - `sandbox-scene`
  - `ui-canvas-scaler`
