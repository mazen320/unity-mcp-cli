"""Tests for core/tool_coverage.py — evidence buckets, summary, handoff plans, live pass profiles."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_live_mcp_pass import (
    _build_profile_plan,
    _default_report_file,
    _format_live_pass_summary,
    _summarize_live_pass_report,
)
from cli_anything.unity_mcp.core.mcp_tools import get_mcp_tool, iter_mcp_tools
from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix


class CoverageTests(unittest.TestCase):

    def test_tool_coverage_matrix_marks_live_tested_and_deferred_tools(self) -> None:
        payload = build_tool_coverage_matrix(category="terrain")

        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertEqual(tools["unity_terrain_create"]["coverageStatus"], "live-tested")
        self.assertEqual(tools["unity_terrain_info"]["coverageStatus"], "live-tested")
        # terrain/create-grid is now mock-only (promoted from deferred in this session).
        self.assertEqual(tools["unity_terrain_create_grid"]["coverageStatus"], "mock-only")
        self.assertIn("mock Unity bridge", tools["unity_terrain_create_grid"]["coverageNote"])
        self.assertGreaterEqual(payload["summary"]["countsByStatus"]["live-tested"], 1)
        evidence = payload["summary"]["evidenceSummary"]
        self.assertEqual(evidence["liveVerifiedCount"], payload["summary"]["countsByStatus"]["live-tested"])
        self.assertEqual(evidence["automatedCoveredCount"], payload["summary"]["countsByStatus"]["covered"])
        self.assertEqual(evidence["mockOnlyCount"], payload["summary"]["countsByStatus"]["mock-only"])
        self.assertEqual(
            evidence["remainingCount"],
            payload["summary"]["countsByStatus"]["deferred"] + payload["summary"]["countsByStatus"]["unsupported"],
        )
        self.assertEqual(
            evidence["remainingByStatus"],
            {
                "deferred": payload["summary"]["countsByStatus"]["deferred"],
                "unsupported": payload["summary"]["countsByStatus"]["unsupported"],
            },
        )
        self.assertIn("Do not blend", evidence["note"])
        self.assertIn("live-verified", evidence["headline"])

        full_payload = build_tool_coverage_matrix()
        all_tools = {tool["name"]: tool for tool in full_payload["tools"]}
        for name in (
            "unity_animation_add_parameter",
            "unity_animation_add_state",
            "unity_animation_set_default_state",
            "unity_animation_add_transition",
            "unity_animation_assign_controller",
            "unity_animation_clip_info",
            "unity_animation_controller_info",
            "unity_asset_create_prefab",
            "unity_asset_instantiate_prefab",
            "unity_graphics_material_info",
            "unity_graphics_renderer_info",
            "unity_material_create",
            "unity_prefab_info",
            "unity_renderer_set_material",
        ):
            self.assertEqual(all_tools[name]["coverageStatus"], "live-tested", name)
            self.assertEqual(all_tools[name]["coverageBlocker"], "verified-live", name)
            if name.startswith("unity_animation_"):
                self.assertIn("standalone File IPC", all_tools[name]["coverageNote"], name)
            else:
                self.assertIn("standalone File IPC prefab/material/renderer parity probe", all_tools[name]["coverageNote"], name)
        for name in (
            "unity_agents_list",
            "unity_advanced_tool",
            "unity_console_log",
            "unity_list_advanced_tools",
            "unity_list_instances",
            "unity_select_instance",
        ):
            self.assertEqual(all_tools[name]["coverageStatus"], "covered", name)
            self.assertEqual(all_tools[name]["coverageBlocker"], "verified-automated", name)

    def test_file_ipc_bridge_owns_public_prefab_material_renderer_routes(self) -> None:
        bridge_path = (
            Path(__file__).resolve().parents[3]
            / "unity-scripts"
            / "Editor"
            / "FileIPCBridge.cs"
        )
        source = bridge_path.read_text(encoding="utf-8")

        for route in (
            "asset/create-material",
            "asset/create-prefab",
            "asset/instantiate-prefab",
            "renderer/set-material",
            "graphics/material-info",
            "graphics/renderer-info",
        ):
            self.assertIn(f'"{route}"', source)

    def test_tool_coverage_matrix_marks_mock_only_focused_routes(self) -> None:
        payload = build_tool_coverage_matrix()

        tools = {tool["name"]: tool for tool in payload["tools"]}
        for name in (
            "unity_ui_create_element",
            "unity_ui_set_text",
            "unity_ui_set_image",
            "unity_lighting_create_light_probe_group",
            "unity_lighting_create_reflection_probe",
            "unity_lighting_set_environment",
            "unity_animation_add_event",
            "unity_animation_get_curve_keyframes",
            "unity_animation_get_events",
            "unity_terrain_get_heights_region",
            "unity_terrain_get_steepness",
            "unity_terrain_get_tree_instances",
            "unity_terrain_list",
            "unity_playerprefs_get",
            "unity_playerprefs_set",
            "unity_playerprefs_delete",
            "unity_playerprefs_delete_all",
            "unity_input_add_action",
            "unity_input_add_binding",
            "unity_input_add_composite_binding",
            "unity_input_add_map",
            "unity_input_remove_action",
            "unity_input_remove_map",
            "unity_spriteatlas_add",
            "unity_spriteatlas_create",
            "unity_spriteatlas_delete",
            "unity_spriteatlas_info",
            "unity_spriteatlas_list",
            "unity_spriteatlas_remove",
            "unity_spriteatlas_settings",
            "unity_mppm_activate_scenario",
            "unity_mppm_info",
            "unity_mppm_list_scenarios",
            "unity_mppm_start",
            "unity_mppm_status",
            "unity_mppm_stop",
        ):
            self.assertEqual(tools[name]["coverageStatus"], "mock-only", name)
            self.assertEqual(tools[name]["coverageBlocker"], "verified-mock", name)
            self.assertIn("mock Unity bridge", tools[name]["coverageNote"], name)

    def test_tool_coverage_matrix_can_build_next_agent_batch(self) -> None:
        # Use "amplify" category — package-dependent, stays deferred long-term.
        payload = build_tool_coverage_matrix(
            category="amplify",
            status="deferred",
            summary_only=True,
            next_batch_limit=3,
        )

        self.assertNotIn("tools", payload)
        self.assertEqual(payload["summary"]["filters"]["nextBatchLimit"], 3)
        self.assertGreaterEqual(len(payload["nextBatch"]), 1)
        self.assertLessEqual(len(payload["nextBatch"]), 3)
        candidate = payload["nextBatch"][0]
        self.assertEqual(candidate["coverageStatus"], "deferred")
        self.assertEqual(candidate["category"], "amplify")
        self.assertEqual(candidate["coverageBlocker"], "package-dependent-live-audit")
        self.assertEqual(candidate["fixtureHint"]["package"], "Amplify Shader Editor")
        self.assertIn("Assets/CLIAnythingFixtures/Amplify", candidate["fixtureHint"]["fixtureRoot"])
        self.assertIn(candidate["risk"], {"read-only", "safe-mutation", "stateful-mutation", "destructive"})
        self.assertIn("cli-anything-unity-mcp --json tool-info", candidate["recommendedCommands"][0])
        self.assertIn("cli-anything-unity-mcp --json tool-template", candidate["recommendedCommands"][1])
        self.assertIn("disposable Unity project", candidate["handoffPrompt"])
        self.assertIn("preflight", candidate["handoffPrompt"])

    def test_tool_coverage_matrix_can_build_package_fixture_plans(self) -> None:
        payload = build_tool_coverage_matrix(
            status="deferred",
            summary_only=True,
            fixture_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["fixturePlan"])
        plans = {plan["category"]: plan for plan in payload["fixturePlans"]}
        self.assertEqual(sorted(plans), ["amplify", "uma"])
        self.assertEqual(plans["amplify"]["package"], "Amplify Shader Editor")
        self.assertEqual(plans["amplify"]["deferredToolCount"], 23)
        self.assertEqual(plans["uma"]["package"], "UMA / UMA DCS")
        self.assertEqual(plans["uma"]["deferredToolCount"], 15)
        self.assertIn("Assets/CLIAnythingFixtures/Amplify", plans["amplify"]["fixtureRoot"])
        self.assertIn("unity_amplify_status", plans["amplify"]["preflight"])
        self.assertIn("--next-batch 10", plans["amplify"]["recommendedCommands"][0])
        self.assertIn("preflight commands first", plans["amplify"]["handoffPrompt"])
        self.assertIn("readOnlyFirst", plans["amplify"])
        self.assertIn("safeMutationNext", plans["amplify"])
        self.assertIn("statefulMutationLater", plans["amplify"])
        self.assertIn("destructiveLast", plans["amplify"])

    def test_tool_coverage_matrix_can_build_unsupported_support_plans(self) -> None:
        payload = build_tool_coverage_matrix(
            status="unsupported",
            summary_only=True,
            support_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["supportPlan"])
        support_plans = {plan["category"]: plan for plan in payload["supportPlans"]}
        self.assertEqual(sorted(support_plans), ["hub"])
        hub_plan = support_plans["hub"]
        self.assertEqual(hub_plan["coverageBlocker"], "unity-hub-integration")
        self.assertEqual(hub_plan["toolCount"], 6)
        self.assertIn("unity_hub_list_editors", {tool["name"] for tool in hub_plan["tools"]})
        self.assertIn("read-only editor discovery", hub_plan["handoffPrompt"])
        self.assertIn("cli-anything-unity-mcp --json tool-info unity_hub_list_editors", hub_plan["recommendedCommands"])
        self.assertGreaterEqual(len(hub_plan["safeImplementationOrder"]), 3)

    def test_tool_coverage_matrix_can_build_cross_track_handoff_plan(self) -> None:
        payload = build_tool_coverage_matrix(
            summary_only=True,
            handoff_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["handoffPlan"])
        handoff = payload["handoffPlan"]
        self.assertEqual(handoff["remainingToolCount"], 44)
        self.assertEqual(handoff["deferredToolCount"], 38)
        self.assertEqual(handoff["unsupportedToolCount"], 6)
        self.assertEqual(handoff["deferredByBlocker"], {"package-dependent-live-audit": 38})
        self.assertEqual(handoff["unsupportedByBlocker"], {"unity-hub-integration": 6})
        tracks = {track["name"]: track for track in handoff["tracks"]}
        self.assertEqual(sorted(tracks), ["optional-package-live-audits", "unity-hub-backend"])
        self.assertEqual(tracks["optional-package-live-audits"]["categories"], ["amplify", "uma"])
        self.assertEqual(tracks["optional-package-live-audits"]["toolCount"], 38)
        self.assertEqual(tracks["unity-hub-backend"]["categories"], ["hub"])
        self.assertEqual(tracks["unity-hub-backend"]["toolCount"], 6)
        self.assertIn("--fixture-plan", tracks["optional-package-live-audits"]["nextCommand"])
        self.assertIn("--support-plan", tracks["unity-hub-backend"]["nextCommand"])
        self.assertIn("coverage work", handoff["handoffPrompt"])

    def test_tool_coverage_matrix_explains_hub_tools_as_unity_hub_integration_gap(self) -> None:
        payload = build_tool_coverage_matrix(category="hub")

        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertEqual(tools["unity_hub_list_editors"]["coverageStatus"], "unsupported")
        self.assertEqual(tools["unity_hub_list_editors"]["coverageBlocker"], "unity-hub-integration")
        self.assertIn("Unity Hub integration", tools["unity_hub_list_editors"]["coverageNote"])

    def test_live_pass_profile_plan_supports_focused_profiles_and_heavy_overlay(self) -> None:
        terrain_plan = _build_profile_plan("terrain")
        self.assertEqual(terrain_plan["advancedCategory"], "terrain")
        self.assertEqual(terrain_plan["toolInfoTool"], "unity_terrain_info")
        self.assertEqual(terrain_plan["toolCallTool"], "unity_terrain_info")
        self.assertEqual(terrain_plan["auditCategories"], ["terrain", "lighting", "navmesh"])

        ui_heavy_plan = _build_profile_plan("ui", include_heavy=True)
        self.assertEqual(ui_heavy_plan["advancedCategory"], "ui")
        self.assertIn("terrain", ui_heavy_plan["auditCategories"])
        self.assertIn("shadergraph", ui_heavy_plan["auditCategories"])
        self.assertGreaterEqual(
            len(ui_heavy_plan["auditCategories"]),
            len(terrain_plan["auditCategories"]),
        )

    def test_live_pass_default_report_file_uses_profile_name(self) -> None:
        report_file = _default_report_file(
            Path("C:/Temp/.cli-anything-unity-mcp"),
            "lighting",
            timestamp="20260409-120000",
        )
        self.assertEqual(
            str(report_file).replace("\\", "/"),
            "C:/Temp/.cli-anything-unity-mcp/live-pass-lighting-20260409-120000.json",
        )

    def test_live_pass_summary_highlights_failures_timeouts_and_port_hops(self) -> None:
        report = {
            "steps": [
                {
                    "name": "unity_select_instance",
                    "status": "passed",
                    "durationMs": 12.0,
                    "result": {"selectedPort": 7891},
                },
                {
                    "name": "unity_inspect",
                    "status": "passed",
                    "durationMs": 130.25,
                    "result": {"summary": {"port": 7892}},
                },
                {
                    "name": "unity_play(play)",
                    "status": "failed",
                    "durationMs": 20000.0,
                    "result": {"timedOut": True, "error": "play mode did not settle"},
                    "consoleSnapshot": {
                        "status": "passed",
                        "result": {
                            "entries": [
                                {
                                    "type": "error",
                                    "message": "Input exception during play mode",
                                }
                            ]
                        },
                    },
                },
            ],
            "summary": {
                "port": 7891,
                "passed": 2,
                "failed": 1,
                "profile": "ui",
                "reportFile": "C:/Temp/live-pass-ui.json",
            },
        }

        summary = _summarize_live_pass_report(report)

        self.assertEqual(summary["totalSteps"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["timedOut"], 1)
        failed_step = summary["failedSteps"][0]
        self.assertEqual(failed_step["name"], "unity_play(play)")
        self.assertEqual(failed_step["status"], "timed-out")
        self.assertEqual(failed_step["durationMs"], 20000.0)
        self.assertEqual(failed_step["detail"], "play mode did not settle")
        self.assertEqual(failed_step["consoleSummary"], "error: Input exception during play mode")
        self.assertIn(
            "cli-anything-unity-mcp --json play stop --port 7891",
            failed_step["recommendedCommands"],
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port 7891",
            summary["recommendedCommands"],
        )
        self.assertEqual(
            summary["portHops"],
            [{"step": "unity_inspect", "from": 7891, "to": 7892}],
        )

        report["liveSummary"] = summary
        text = _format_live_pass_summary(report, failures_only=True)

        self.assertIn("Unity MCP Live Pass", text)
        self.assertIn("Failures And Timeouts", text)
        self.assertIn("unity_play(play) [timed-out] in 20000.0ms: play mode did not settle", text)
        self.assertIn("console: error: Input exception during play mode", text)
        self.assertIn("next: cli-anything-unity-mcp --json play stop --port 7891", text)
        self.assertIn("Port Hops", text)
        self.assertIn("7891 -> 7892 during unity_inspect", text)
        self.assertNotIn("Slowest Steps", text)

    def test_mcp_tool_registry_is_curated_and_has_fast_defaults(self) -> None:
        names = [tool["name"] for tool in iter_mcp_tools()]

        self.assertIn("unity_tool_call", names)
        self.assertIn("unity_validate_scene", names)
        self.assertNotIn("unity_build_sample", names)
        self.assertNotIn("unity_build_fps_sample", names)

        audit_tool = get_mcp_tool("unity_audit_advanced")
        self.assertIsNotNone(audit_tool)
        self.assertEqual(
            audit_tool.input_schema["properties"]["probeBacked"]["default"],
            True,
        )
