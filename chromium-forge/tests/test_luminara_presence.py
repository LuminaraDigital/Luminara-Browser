"""Presence shield, refuse-once-after-takeover guard and goal-loop takeover (`tests/test_luminara_presence.py`)."""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from forge.agent_server import LuminaraAgentRuntime
from forge.cdp_client import CDPBridge, CDPError, PersonControlError, TabLeaseManager, terminate_browser_process
from forge.models import ForkProfile
from forge.presence import PresenceShield
from forge.verifier_agentic import find_chromium_binary

FORGE_ROOT = Path(__file__).resolve().parent.parent


class TestTakeoverGuard(unittest.TestCase):
    def test_interrupted_agent_is_refused_exactly_once_and_others_are_not(self) -> None:
        leases = TabLeaseManager()
        leases.acquire("t1", "agent-a")
        leases.force_human_override("t1")
        leases.check_allowed("t1", "agent-b")  # was not working here: unaffected
        with self.assertRaises(PersonControlError):
            leases.check_allowed("t1", "agent-a")
        leases.check_allowed("t1", "agent-a")  # told once, may continue
        leases.acquire("t1", "agent-a")

    def test_takeover_of_an_idle_tab_refuses_nobody_and_acquire_is_guarded_too(self) -> None:
        leases = TabLeaseManager()
        leases.force_human_override("t1")
        leases.check_allowed("t1", "agent-a")
        leases.acquire("t2", "agent-a")
        leases.force_human_override("t2")
        with self.assertRaises(PersonControlError):
            leases.acquire("t2", "agent-a")

    def test_hold_runs_before_allowed_actions_and_in_page_takeover_stops_the_agent(self) -> None:
        cdp = MagicMock(spec=CDPBridge)
        leases = TabLeaseManager()
        shield = PresenceShield(cdp, leases)
        leases.on_action = shield.hold

        cdp.evaluate_js.return_value = {"taken_over": False}
        leases.check_allowed("t1", "agent-a")
        self.assertIn("'agent-a'", cdp.evaluate_js.call_args.args[1])

        # A hostile agent id cannot break out of the script's string literal.
        leases.check_allowed("t1", "x');alert(1);('")
        self.assertIn("('xalert1', ", cdp.evaluate_js.call_args.args[1])

        cdp.evaluate_js.return_value = {"taken_over": True}
        with self.assertRaises(PersonControlError):
            leases.check_allowed("t1", "agent-a")

        # A page that cannot host the shield never blocks the action.
        cdp.evaluate_js.side_effect = CDPError("cannot evaluate on chrome:// page")
        leases.check_allowed("t1", "agent-a")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TestPresenceLive(unittest.TestCase):
    def test_shield_blocks_person_passes_agent_and_escape_hands_back_control(self) -> None:
        chrome_exe = find_chromium_binary(FORGE_ROOT, ForkProfile())
        if chrome_exe is None:
            self.skipTest("Portable chrome.exe not yet built")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cdp_port = _free_port()
            rt = LuminaraAgentRuntime(Path(tmp) / "state", cdp_port=cdp_port)
            rt.goals.router.use_env_providers = False
            proc = subprocess.Popen(
                [
                    str(chrome_exe), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                    f"--user-data-dir={Path(tmp) / 'prof'}", f"--remote-debugging-port={cdp_port}",
                    "--remote-allow-origins=*", "--window-size=1280,900", "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 20.0
                while not rt.cdp.is_alive():
                    self.assertLess(time.monotonic(), deadline, "Chromium CDP endpoint never came up")
                    time.sleep(0.2)
                tid = rt.cdp.open_tab("about:blank", background=False)["target_id"]
                js = rt.cdp.evaluate_js
                js(tid, "document.body.innerHTML = '<button id=b style=\"margin:120px\" onclick=\"window.hits=(window.hits||0)+1\">Go</button>'; 1")
                box = js(tid, "(() => { const r = document.getElementById('b').getBoundingClientRect(); return {x: r.x + r.width / 2, y: r.y + r.height / 2}; })()")

                def person_or_agent_clicks() -> int:
                    rt.cdp.dispatch_mouse_click(tid, box["x"], box["y"])
                    return int(js(tid, "window.hits || 0"))

                # Agent acts: the banner appears and its own input passes.
                rt.cdp.leases.check_allowed(tid, "agent-a")
                self.assertIn("agent-a is working here", js(tid, "document.getElementById('__luminara_presence').textContent"))
                self.assertEqual(person_or_agent_clicks(), 1)

                # Between agent actions the person's clicks are held.
                js(tid, "window.__luminaraPresence.passUntil = 0; 1")
                self.assertEqual(person_or_agent_clicks(), 1)

                # Escape hands control back: banner gone, input flows, agent refused exactly once.
                rt.cdp.run_session(tid, [
                    ("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27}),
                    ("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27}),
                ])
                self.assertIsNone(js(tid, "document.getElementById('__luminara_presence')"))
                self.assertEqual(person_or_agent_clicks(), 2)
                with self.assertRaises(PersonControlError):
                    rt.cdp.leases.check_allowed(tid, "agent-a")
                rt.cdp.leases.check_allowed(tid, "agent-a")
                self.assertIsNotNone(js(tid, "document.getElementById('__luminara_presence')"))

                # The human_takeover tool clears the shield as well.
                rt.dispatch_tool("browser_act", {"action": "human_takeover", "target_id": tid})
                self.assertIsNone(js(tid, "document.getElementById('__luminara_presence')"))

                # Goal loop: a click step settles on the real page, then a takeover mid-run stops the goal.
                decisions = iter([{"action": "click", "index": 1, "reason": "press Go"}])

                def planner(_provider: str, _prompt: str) -> dict:
                    step = next(decisions, None)
                    if step is None:
                        rt.cdp.leases.force_human_override(tid)
                        step = {"action": "scroll", "reason": "look further down"}
                    return step

                rt.goals.router.custom_caller = planner
                hits_before = int(js(tid, "window.hits || 0"))
                run = rt.goals.run_goal("press the Go button", target_id=tid, max_steps=4, agent_id="agent-g", show_badges=False)
                self.assertEqual(run["status"], "STOPPED_HUMAN_TAKEOVER")
                self.assertEqual(int(js(tid, "window.hits || 0")), hits_before + 1)
                self.assertIsNone(rt.cdp.leases.get_active(tid))
            finally:
                rt.close()
                terminate_browser_process(proc)


if __name__ == "__main__":
    unittest.main()
