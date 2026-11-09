"""Local-deployment safety contract (stdlib unittest, no user database)."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
START = ROOT / "scripts" / "dev-start.sh"
STOP = ROOT / "scripts" / "dev-stop.sh"
SMOKE = ROOT / "scripts" / "smoke-test.sh"
COMMON = ROOT / "scripts" / "dev-common.sh"


def run(command: list[str], **overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(overrides)
    return subprocess.run(command, cwd=ROOT, env=env, text=True,
                          capture_output=True, timeout=20)


class DeploymentSafetyTests(unittest.TestCase):
    def test_start_fails_closed_on_unsafe_host_and_bad_ports(self):
        with tempfile.TemporaryDirectory(prefix="tracemap-contract-") as tmp:
            base = {"TRACEMAP_RUNTIME_DIR": tmp}
            matrix = [
                ({"TRACEMAP_API_HOST": "0.0.0.0"}, "DEV_BIND_UNSAFE"),
                ({"TRACEMAP_WEB_HOST": "::"}, "DEV_BIND_UNSAFE"),
                ({"TRACEMAP_API_PORT": "8000; touch /tmp/bad"}, "Invalid port"),
                ({"TRACEMAP_API_PORT": "0"}, "Port out of range"),
                ({"TRACEMAP_WEB_PORT": "70000"}, "Port out of range"),
                ({"TRACEMAP_WEB_PORT": "8000"}, "must differ"),
                ({"TRACEMAP_DATABASE_URL": "sqlite:///./wrong.db"}, "absolute SQLite URL"),
            ]
            for changes, message in matrix:
                with self.subTest(changes=changes):
                    result = run(["bash", str(START)], **base, **changes)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertFalse((Path(tmp) / "data" / "tracemap-dev.db").exists())

    def test_existing_runtime_directory_permissions_are_restricted(self):
        import stat
        with tempfile.TemporaryDirectory(prefix="tracemap-permissions-") as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            runtime.chmod(0o755)
            r = run(["bash", "-c", f'source "{COMMON}"; validate_dev_configuration; ensure_dirs'],
                    TRACEMAP_RUNTIME_DIR=str(runtime))
            self.assertEqual(r.returncode, 0, r.stderr)
            for folder in [runtime, runtime / "data", runtime / "pids", runtime / "logs"]:
                self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700, str(folder))

    def test_runtime_directory_must_be_absolute(self):
        r = run(["bash", str(START)], TRACEMAP_RUNTIME_DIR="relative-runtime")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Runtime directory", r.stderr)

    def test_ss_listener_without_visible_pid_is_not_free(self):
        script = f"""
        source "{COMMON}"
        ss() {{ printf 'LISTEN 0 128 127.0.0.1:44971 0.0.0.0:*\\n'; }}
        port_state 44971
        """
        r = run(["bash", "-c", script])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "other")

    def test_process_generation_record_rejects_pid_reuse(self):
        proc = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory(prefix="tracemap-identity-") as tmp:
                pidfile = Path(tmp) / "foreign.pid"
                script = f"""
                source "{COMMON}"
                ticks="$(pid_start_ticks {proc.pid})"
                printf '%s %s\\n' "{proc.pid}" "$ticks" > "{pidfile}"
                pid_owned "{pidfile}" "{proc.pid}" sleep || exit 11
                printf '%s %s\\n' "{proc.pid}" "$((ticks + 1))" > "{pidfile}"
                if pid_owned "{pidfile}" "{proc.pid}" sleep; then exit 12; fi
                """
                r = run(["bash", "-c", script])
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_stop_refuses_to_kill_foreign_process(self):
        if not shutil.which("ss") or not shutil.which("flock"):
            self.skipTest("Linux ss/flock not installed")
        proc = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory(prefix="tracemap-stop-") as tmp:
                pids = Path(tmp) / "pids"
                pids.mkdir()
                tick = run(["bash", "-c", f'source "{COMMON}"; pid_start_ticks {proc.pid}'])
                self.assertEqual(tick.returncode, 0, tick.stderr)
                (pids / "api.pid").write_text(f"{proc.pid} {tick.stdout.strip()}\n")
                r = run(["bash", str(STOP)], TRACEMAP_RUNTIME_DIR=tmp,
                        TRACEMAP_API_PORT="44972", TRACEMAP_WEB_PORT="44973")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("refusing to signal", r.stderr)
                self.assertIsNone(proc.poll(), "An unrelated process was killed")
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    def test_live_smoke_never_succeeds_when_services_are_absent(self):
        if not shutil.which("ss"):
            self.skipTest("Linux ss not installed")
        with tempfile.TemporaryDirectory(prefix="tracemap-live-") as tmp:
            r = run(["bash", str(SMOKE), "--live-only"],
                    TRACEMAP_RUNTIME_DIR=tmp,
                    TRACEMAP_API_PORT="44974", TRACEMAP_WEB_PORT="44975")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("api not owned", r.stdout)
            self.assertIn("web not owned", r.stdout)


if __name__ == "__main__":
    unittest.main()
