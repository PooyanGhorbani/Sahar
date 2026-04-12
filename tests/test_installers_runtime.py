import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallerRuntimeTests(unittest.TestCase):
    def run_bash(self, script: str, *, env=None, cwd=None):
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(
            ["bash", "-lc", script],
            cwd=str(cwd or ROOT),
            env=merged_env,
            text=True,
            capture_output=True,
        )

    def start_python_tcp_server(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        server = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.4)
        return server, port

    def test_master_wait_for_tcp_listener_accepts_local_socket(self):
        server, port = self.start_python_tcp_server()
        try:
            result = self.run_bash(
                textwrap.dedent(
                    f"""
                    source ./install_master.sh
                    status_note() {{ :; }}
                    wait_for_tcp_listener 127.0.0.1 {port} 5 0.1
                    """
                )
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_agent_wait_for_tcp_listener_normalizes_wildcard_host(self):
        server, port = self.start_python_tcp_server()
        try:
            result = self.run_bash(
                textwrap.dedent(
                    f"""
                    source ./install_agent.sh
                    status_note() {{ :; }}
                    wait_for_tcp_listener 0.0.0.0 {port} 5 0.1
                    """
                )
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_assert_runtime_tools_reports_missing_gunicorn(self):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp) / "bin"
            bindir.mkdir(parents=True)
            for name in ("python", "pip"):
                path = bindir / name
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
            result = self.run_bash(
                textwrap.dedent(
                    f"""
                    source ./install_master.sh
                    VENV_DIR={tmp!r}
                    if assert_runtime_tools; then
                      echo unexpected-success
                      exit 1
                    fi
                    printf '%s' "$FAIL_HINT"
                    """
                )
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("missing gunicorn", result.stdout)

    def test_busybox_timeout_detection_falls_back_without_foreground(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_timeout = Path(tmp) / "timeout"
            fake_timeout.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--help\" ]; then\n"
                "  echo 'BusyBox v1.36.1 timeout'\n"
                "  exit 0\n"
                "fi\n"
                "shift\n"
                "exec \"$@\"\n",
                encoding="utf-8",
            )
            fake_timeout.chmod(0o755)
            result = self.run_bash(
                textwrap.dedent(
                    f"""
                    export PATH={tmp!r}:$PATH
                    source ./install_master.sh
                    timeout_supports_foreground && exit 9 || true
                    run_with_timeout 2 bash -lc 'exit 0'
                    """
                )
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_init_config_defaults_auto_enables_cloudflare_when_token_and_domain_are_provided(self):
        result = self.run_bash(
            textwrap.dedent(
                """
                source ./install_master.sh
                CLOUDFLARE_ENABLED=
                CLOUDFLARE_API_TOKEN=token-123
                CLOUDFLARE_DOMAIN_NAME=example.com
                init_config_defaults
                printf '%s|%s|%s' "$CLOUDFLARE_ENABLED" "$CLOUDFLARE_DOMAIN_NAME" "$CLOUDFLARE_BASE_SUBDOMAIN"
                """
            )
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertEqual(result.stdout.strip(), 'true|example.com|vpn')

    def test_install_master_enables_tunnel_flags_in_written_config(self):
        text = (ROOT / 'install_master.sh').read_text(encoding='utf-8')
        self.assertIn("'cloudflare_dns_proxied': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true'", text)
        self.assertIn("'cloudflare_tunnel_enabled': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true'", text)
        self.assertIn("'cloudflare_argo_enabled': os.environ.get('CLOUDFLARE_ENABLED', 'false').lower() == 'true'", text)
        self.assertIn('Cloudflare API token', text)
        self.assertIn('Domain for subdomains', text)
        self.assertIn('Input is visible while typing', text)
        self.assertNotIn("read -rsp ' 🤖 Telegram BOT_TOKEN: '", text)
        self.assertNotIn("read -rsp ' ☁️  Cloudflare API token: '", text)
        self.assertIn('Telegram bot token (visible', text)
        self.assertIn('Cloudflare API token (visible)', text)


if __name__ == "__main__":
    unittest.main()
