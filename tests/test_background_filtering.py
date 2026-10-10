"""
Test: Generic User-Intent vs Background System Process Filtering
Verifies that:
1. Background system components (such as SearchHost, shell helpers, indexers) that appear with zero user interactions are classified as Background System Activity and NEVER generate OPEN_APPLICATION actions.
2. Child helper processes (such as browser subprocesses, renderers, utility workers) are correlated to the parent application and do NOT generate separate OPEN_APPLICATION actions.
3. User-initiated application actions (where the user explicitly launches, clicks, types, or interacts with the app) generate verified OPEN_APPLICATION actions.
4. All filtering is 100% GENERIC with ZERO hardcoded application or process names.
"""

import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai

class TestUserIntentAndBackgroundFiltering(unittest.TestCase):

    def test_exclude_background_process_during_app_launch(self):
        """
        Recreates the exact real-world scenario:
        1. User clicks to launch browser/app
        2. OS internally wakes background system process (e.g., SearchHost.exe) with 0 user interaction
        3. Real app window gains focus with user interaction (typing / navigate)
        4. App spawns helper child processes
        Verify:
        - Only the user-intended application has OPEN_APPLICATION generated.
        - Background process is completely excluded.
        - Child subprocesses are completely excluded.
        """
        events = [
            # 1. User clicks launcher/taskbar
            {
                "event_type": "UI_CLICK",
                "app_name": "explorer.exe",
                "window_title": "Taskbar",
                "details": {"element": "Chrome Shortcut", "target": "Chrome", "x": 200, "y": 1050},
                "semantic_action": "CLICK"
            },
            # 2. Windows internal background component gains transient focus (0 user input, tool window style)
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "SearchHost.exe",
                "window_title": "Search",
                "details": {
                    "app": "SearchHost",
                    "exe": "C:\\Windows\\SystemApps\\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\\SearchHost.exe",
                    "pid": 1844,
                    "ppid": 892,
                    "parent_name": "services.exe",
                    "is_tool_window": True,
                    "is_app_window": False,
                    "has_owner": False,
                    "width": 600,
                    "height": 700,
                    "time_since_click": 0.15
                },
                "semantic_action": "WINDOW_FOCUS"
            },
            # 3. Target application window appears (visible top-level app window)
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "chrome.exe",
                "window_title": "New Tab - Google Chrome",
                "details": {
                    "app": "chrome",
                    "exe": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                    "pid": 4320,
                    "ppid": 1200,
                    "parent_name": "explorer.exe",
                    "is_tool_window": False,
                    "is_app_window": True,
                    "has_owner": False,
                    "width": 1280,
                    "height": 900,
                    "time_since_click": 0.45
                },
                "semantic_action": "WINDOW_FOCUS"
            },
            # 4. Chrome spawns helper child process (renderer/gpu)
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "chrome.exe",
                "window_title": "",
                "details": {
                    "app": "chrome",
                    "pid": 5880,
                    "ppid": 4320,  # Child of PID 4320
                    "parent_name": "chrome.exe",
                    "is_tool_window": True,
                    "width": 0,
                    "height": 0
                },
                "semantic_action": "WINDOW_FOCUS"
            },
            # 5. User clicks inside Chrome window
            {
                "event_type": "UI_CLICK",
                "app_name": "chrome.exe",
                "window_title": "New Tab - Google Chrome",
                "details": {"element": "Address Bar", "target": "Address Bar", "x": 400, "y": 80},
                "semantic_action": "CLICK"
            },
            # 6. User types target URL in Chrome
            {
                "event_type": "TEXT_INPUT",
                "app_name": "chrome.exe",
                "window_title": "New Tab - Google Chrome",
                "details": {"text": "https://google.com"},
                "semantic_action": "TYPE"
            },
            # 7. Navigation event
            {
                "event_type": "BROWSER_NAVIGATE",
                "app_name": "chrome.exe",
                "window_title": "Google - Google Chrome",
                "details": {"url": "https://google.com", "domain": "google.com"},
                "semantic_action": "BROWSER_NAVIGATE"
            }
        ]

        plan = ai.synthesize_workflow_from_events(events)
        actions = plan.get("actions", [])
        action_types = [a["type"] for a in actions]
        app_targets = [a.get("params", {}).get("app", "") for a in actions if a["type"] == ai.ACTION_OPEN_APP]

        print("\n--- Synthesized Plan Steps ---")
        for i, act in enumerate(actions, 1):
            print(f"[{i}] {act['type']} -> {act.get('label')}")

        # Assertions
        # 1. SearchHost must NOT be in app targets
        self.assertNotIn("SearchHost", app_targets, "SearchHost should NOT be emitted as an application launch!")
        self.assertNotIn("searchhost", [t.lower() for t in app_targets])

        # 2. chrome MUST be in app targets
        self.assertIn("chrome", [t.lower() for t in app_targets], "Chrome should be recognized as user-intended application launch")

        # 3. Only ONE launch action for chrome (no duplicate child subprocess launches)
        chrome_launches = [t for t in app_targets if t.lower() == "chrome"]
        self.assertEqual(len(chrome_launches), 1, "There should be exactly ONE launch action for Chrome")

        # 4. User actions must be present
        self.assertIn(ai.ACTION_TYPE, action_types)
        self.assertIn(ai.ACTION_BROWSER_NAVIGATE, action_types)

    def test_completely_generic_background_exclusion(self):
        """
        Verify that ANY unknown background process (DaemonXYZ, TelemetryHost, IndexerDaemon)
        with zero user interactions is filtered out, while user-engaged apps are kept.
        """
        events = [
            # Random background system process 1
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "BackgroundTelemetryDaemon.exe",
                "window_title": "Telemetry Host",
                "details": {"app": "BackgroundTelemetryDaemon", "is_tool_window": True},
                "semantic_action": "WINDOW_FOCUS"
            },
            # User opens custom novel app (e.g., CodeIDE)
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "CodeIDE.exe",
                "window_title": "CodeIDE - Project Main",
                "details": {
                    "app": "CodeIDE",
                    "width": 1400,
                    "height": 900,
                    "time_since_click": 0.5,
                    "is_app_window": True
                },
                "semantic_action": "WINDOW_FOCUS"
            },
            # Random background system process 2
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "SystemIndexerHelper.exe",
                "window_title": "Indexer Window",
                "details": {"app": "SystemIndexerHelper", "width": 0, "height": 0},
                "semantic_action": "WINDOW_FOCUS"
            },
            # User types in CodeIDE
            {
                "event_type": "TEXT_INPUT",
                "app_name": "CodeIDE.exe",
                "window_title": "CodeIDE - Project Main",
                "details": {"text": "print('hello world')"},
                "semantic_action": "TYPE"
            }
        ]

        plan = ai.synthesize_workflow_from_events(events)
        actions = plan.get("actions", [])
        app_targets = [a.get("params", {}).get("app", "") for a in actions if a["type"] == ai.ACTION_OPEN_APP]

        self.assertIn("CodeIDE", app_targets)
        self.assertNotIn("BackgroundTelemetryDaemon", app_targets)
        self.assertNotIn("SystemIndexerHelper", app_targets)
        self.assertEqual(len(app_targets), 1)

    def test_window_focus_switch_deduplication(self):
        """
        Verify that switching focus back and forth between already running apps
        does not generate duplicate OPEN_APPLICATION actions.
        """
        events = [
            {"event_type": "WINDOW_FOCUS", "app_name": "AppA.exe", "semantic_action": "WINDOW_FOCUS", "details": {"app": "AppA"}},
            {"event_type": "TEXT_INPUT", "app_name": "AppA.exe", "semantic_action": "TYPE", "details": {"text": "test"}},
            # Switch to AppB
            {"event_type": "WINDOW_FOCUS", "app_name": "AppB.exe", "semantic_action": "WINDOW_FOCUS", "details": {"app": "AppB"}},
            {"event_type": "TEXT_INPUT", "app_name": "AppB.exe", "semantic_action": "TYPE", "details": {"text": "notes"}},
            # Switch back to AppA
            {"event_type": "WINDOW_FOCUS", "app_name": "AppA.exe", "semantic_action": "WINDOW_FOCUS", "details": {"app": "AppA"}},
            {"event_type": "TEXT_INPUT", "app_name": "AppA.exe", "semantic_action": "TYPE", "details": {"text": "more text"}},
        ]

        plan = ai.synthesize_workflow_from_events(events)
        actions = plan.get("actions", [])
        app_launches = [a for a in actions if a["type"] == ai.ACTION_OPEN_APP]
        apps_launched = [a["params"]["app"] for a in app_launches]

        # AppA and AppB should each be launched exactly once
        self.assertEqual(apps_launched.count("AppA"), 1)
        self.assertEqual(apps_launched.count("AppB"), 1)
        self.assertEqual(len(app_launches), 2)


if __name__ == "__main__":
    unittest.main()
