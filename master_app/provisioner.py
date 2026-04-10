from __future__ import annotations

import ipaddress
import os
import secrets
import shlex
import socket
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Tuple

DEFAULT_REALITY_SERVER_NAME = 'www.cloudflare.com'
CLOUDFLARED_VERSION = '2026.2.0'

import paramiko

from agent_client import AgentClient


class ProvisionError(Exception):
    pass


class SSHProvisioner:
    def __init__(self, project_root: str | Path, timeout: int = 30):
        self.project_root = Path(project_root)
        self.timeout = timeout
        self.known_hosts_path = self.project_root / 'data' / 'ssh_known_hosts'

    def provision_agent(
        self,
        *,
        server_name: str,
        host: str,
        ssh_port: int,
        ssh_username: str,
        ssh_password: str,
        transport_mode: str = 'ws',
        agent_listen_port: int = 8787,
        xray_port: int = 443,
        xray_api_port: int = 10085,
        cloudflared_tunnel_token: str = '',
    ) -> Tuple[str, str, Dict[str, Any]]:
        host_mode = self._infer_host_mode(host)
        agent_token = secrets.token_urlsafe(32)
        bundle_path = self._build_bundle()
        remote_dir = f"/tmp/sahar-bootstrap-{int(time.time())}"
        allowed_sources = self._detect_allowed_source_for_host(host, ssh_port)
        if not allowed_sources:
            raise ProvisionError('failed to detect the master source IP for agent allowlisting; refusing to expose the agent API without a source restriction')

        ssh = self._connect(host, ssh_port, ssh_username, ssh_password)
        try:
            if ssh_username != 'root':
                self._ensure_sudo_ready(ssh, ssh_password)
            self._ensure_remote_shell_runtime(ssh, ssh_password, use_sudo=ssh_username != 'root')
            self._run(ssh, f"mkdir -p {shlex.quote(remote_dir)}", ssh_password, use_sudo=ssh_username != 'root')
            remote_bundle = f"{remote_dir}/sahar-agent-bundle.tar.gz"
            sftp = ssh.open_sftp()
            try:
                sftp.put(bundle_path, remote_bundle)
            finally:
                sftp.close()
            self._run(
                ssh,
                f"tar -xzf {shlex.quote(remote_bundle)} -C {shlex.quote(remote_dir)}",
                ssh_password,
                use_sudo=ssh_username != 'root',
            )
            reality_server_name = host if host_mode == 'domain' else DEFAULT_REALITY_SERVER_NAME
            env = {
                'NONINTERACTIVE': '1',
                'PUBLIC_HOST': host,
                'HOST_MODE': host_mode,
                'TRANSPORT_MODE': transport_mode,
                'AGENT_NAME': server_name,
                'XRAY_PORT': str(xray_port),
                'REALITY_PORT': '8443',
                'XRAY_API_PORT': str(xray_api_port),
                'AGENT_LISTEN_HOST': '0.0.0.0',
                'AGENT_LISTEN_PORT': str(agent_listen_port),
                'ALLOWED_SOURCES': allowed_sources,
                'AGENT_TOKEN': agent_token,
                'FINGERPRINT': 'chrome',
                'REALITY_SERVER_NAME': reality_server_name,
                'REALITY_DEST': f'{reality_server_name}:443',
                'AGENT_TLS_ENABLED': 'true',
            }
            env_prefix = ' '.join(f"{k}={shlex.quote(v)}" for k, v in env.items())
            install_cmd = f"cd {shlex.quote(remote_dir)} && {env_prefix} bash ./install_agent.sh"
            self._run(ssh, install_cmd, ssh_password, use_sudo=ssh_username != 'root', timeout=1800)
            if cloudflared_tunnel_token:
                self._deploy_cloudflared_tunnel(
                    ssh,
                    cloudflared_tunnel_token,
                    ssh_password,
                    use_sudo=ssh_username != 'root',
                    timeout=1800,
                )
            tls_fingerprint = self._read_agent_tls_fingerprint(ssh, ssh_password, use_sudo=ssh_username != 'root')
            try:
                self._run(ssh, f"rm -rf {shlex.quote(remote_dir)}", ssh_password, use_sudo=ssh_username != 'root')
            except Exception:
                pass
        finally:
            ssh.close()
            try:
                os.remove(bundle_path)
            except OSError:
                pass

        api_url = f"https://{host}:{agent_listen_port}"
        client = AgentClient(api_url, agent_token, timeout=self.timeout, tls_fingerprint=tls_fingerprint)
        health = self._wait_for_health(client)
        health['api_tls_fingerprint'] = tls_fingerprint
        return api_url, agent_token, health

    def _build_bundle(self) -> str:
        tmp = tempfile.NamedTemporaryFile(prefix='sahar-agent-', suffix='.tar.gz', delete=False)
        tmp.close()
        with tarfile.open(tmp.name, 'w:gz') as tar:
            tar.add(self.project_root / 'install_agent.sh', arcname='install_agent.sh')
            tar.add(self.project_root / 'agent_app', arcname='agent_app')
        return tmp.name

    def _load_known_hosts(self) -> paramiko.HostKeys:
        host_keys = paramiko.HostKeys()
        if self.known_hosts_path.exists():
            host_keys.load(str(self.known_hosts_path))
        return host_keys

    def _persist_known_host(self, host: str, key: paramiko.PKey) -> None:
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        host_keys = self._load_known_hosts()
        host_keys.add(host, key.get_name(), key)
        host_keys.save(str(self.known_hosts_path))

    def _fetch_remote_host_key(self, host: str, port: int) -> paramiko.PKey:
        sock = socket.create_connection((host, port), timeout=self.timeout)
        transport = None
        try:
            transport = paramiko.Transport(sock)
            transport.start_client(timeout=self.timeout)
            return transport.get_remote_server_key()
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            sock.close()

    def _connect(self, host: str, port: int, username: str, password: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.known_hosts_path.exists():
            client.load_host_keys(str(self.known_hosts_path))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=self.timeout,
                auth_timeout=self.timeout,
                banner_timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            return client
        except paramiko.BadHostKeyException as exc:
            raise ProvisionError(f'SSH host key mismatch for {host}: {exc}') from exc
        except paramiko.SSHException as exc:
            message = str(exc).lower()
            if 'not found in known_hosts' not in message and 'server' not in message:
                raise ProvisionError(f'SSH connection failed: {exc}') from exc
        except socket.error as exc:
            raise ProvisionError(f'SSH connection failed: {exc}') from exc
        try:
            remote_key = self._fetch_remote_host_key(host, port)
            self._persist_known_host(host, remote_key)
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.load_host_keys(str(self.known_hosts_path))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=self.timeout,
                auth_timeout=self.timeout,
                banner_timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            return client
        except (socket.error, paramiko.SSHException) as exc:
            raise ProvisionError(f'SSH connection failed: {exc}') from exc

    def _run(self, ssh: paramiko.SSHClient, command: str, password: str, use_sudo: bool = False, timeout: int | None = None) -> str:
        timeout = timeout or self.timeout
        wrapped = f"sudo -S -p '' sh -lc {shlex.quote(command)}" if use_sudo else f"sh -lc {shlex.quote(command)}"
        stdin, stdout, stderr = ssh.exec_command(wrapped, timeout=timeout, get_pty=True)
        if use_sudo:
            stdin.write(password + '\n')
            stdin.flush()
        out = stdout.read().decode('utf-8', 'ignore')
        err = stderr.read().decode('utf-8', 'ignore')
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            msg = (err or out or f'command failed with exit status {rc}').strip()
            raise ProvisionError(msg)
        return out.strip()

    def _ensure_sudo_ready(self, ssh: paramiko.SSHClient, password: str) -> None:
        try:
            self._run(ssh, 'true', password, use_sudo=True, timeout=20)
        except ProvisionError as exc:
            message = str(exc).lower()
            if 'sudo' in message and ('not found' in message or 'command not found' in message):
                raise ProvisionError('remote user is not root and sudo is not installed on the target server') from exc
            raise ProvisionError('remote user needs working sudo privileges or you must connect as root') from exc

    def _ensure_remote_shell_runtime(self, ssh: paramiko.SSHClient, password: str, *, use_sudo: bool) -> None:
        try:
            self._run(ssh, 'command -v bash >/dev/null 2>&1', password, use_sudo=use_sudo, timeout=30)
            return
        except ProvisionError:
            pass
        bootstrap = '''
set -e
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y bash
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache bash
else
  echo "bash is required on the target host and no supported package manager was found" >&2
  exit 1
fi
command -v bash >/dev/null 2>&1
'''
        self._run(ssh, bootstrap, password, use_sudo=use_sudo, timeout=600)

    def _deploy_cloudflared_tunnel(self, ssh: paramiko.SSHClient, tunnel_token: str, password: str, *, use_sudo: bool, timeout: int) -> None:
        script = f'''set -e
arch=$(uname -m)
case "$arch" in
  x86_64|amd64|x64) asset_name="cloudflared-linux-amd64" ;;
  i386|i686) asset_name="cloudflared-linux-386" ;;
  aarch64|arm64|armv8) asset_name="cloudflared-linux-arm64" ;;
  armv7l|armv6l|arm) asset_name="cloudflared-linux-arm" ;;
  *) echo "unsupported arch for cloudflared: $arch" >&2; exit 1 ;;
esac
release_json=$(curl -fsSL -H 'Accept: application/vnd.github+json' -H 'User-Agent: Sahar/0.1.58' "https://api.github.com/repos/cloudflare/cloudflared/releases/tags/{CLOUDFLARED_VERSION}")
download_url=$(printf '%s' "$release_json" | jq -r --arg name "$asset_name" '.assets[] | select(.name == $name) | .browser_download_url' | head -n1)
expected_digest=$(printf '%s' "$release_json" | jq -r --arg name "$asset_name" '.assets[] | select(.name == $name) | .digest // empty' | head -n1 | sed 's/^sha256://')
[ -n "$download_url" ] || {{ echo 'failed to resolve cloudflared download URL' >&2; exit 1; }}
tmp_path=$(mktemp)
curl -fsSL "$download_url" -o "$tmp_path"
if [ -n "$expected_digest" ]; then
  actual_digest=$(sha256sum "$tmp_path" | awk '{{print $1}}')
  [ "$actual_digest" = "$expected_digest" ] || {{ echo 'cloudflared checksum verification failed' >&2; rm -f "$tmp_path"; exit 1; }}
fi
install -m 0755 "$tmp_path" /usr/local/bin/cloudflared
rm -f "$tmp_path"
mkdir -p /etc/sahar /usr/local/libexec
cat >/etc/sahar/cloudflared.env <<'ENVFILE'
TUNNEL_TOKEN='{tunnel_token}'
ENVFILE
chmod 600 /etc/sahar/cloudflared.env
cat >/usr/local/libexec/sahar-cloudflared.sh <<'WRAPPER'
#!/bin/sh
set -eu
. /etc/sahar/cloudflared.env
exec /usr/local/bin/cloudflared tunnel --no-autoupdate run --token "$TUNNEL_TOKEN"
WRAPPER
chmod 700 /usr/local/libexec/sahar-cloudflared.sh
if command -v systemctl >/dev/null 2>&1; then
cat >/etc/systemd/system/sahar-cloudflared.service <<'SERVICE'
[Unit]
Description=Sahar Cloudflare Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/libexec/sahar-cloudflared.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable sahar-cloudflared >/dev/null 2>&1 || true
systemctl restart sahar-cloudflared
elif command -v rc-service >/dev/null 2>&1; then
cat >/etc/init.d/sahar-cloudflared <<'SERVICE'
#!/sbin/openrc-run
name="sahar-cloudflared"
command="/usr/local/libexec/sahar-cloudflared.sh"
command_background=true
pidfile="/run/sahar-cloudflared.pid"
output_log="/var/log/sahar-cloudflared.log"
error_log="/var/log/sahar-cloudflared.err"

depend() {{
    need net
}}
SERVICE
chmod +x /etc/init.d/sahar-cloudflared
rc-update add sahar-cloudflared default >/dev/null 2>&1 || true
rc-service sahar-cloudflared restart >/dev/null 2>&1 || rc-service sahar-cloudflared start
else
/usr/local/libexec/sahar-cloudflared.sh >/tmp/sahar-cloudflared.log 2>&1 &
fi
'''
        self._run(ssh, script, password, use_sudo=use_sudo, timeout=timeout)

    def _read_agent_tls_fingerprint(self, ssh: paramiko.SSHClient, password: str, *, use_sudo: bool) -> str:
        cmd = """python3 - <<'PY'
import json
from pathlib import Path
path = Path('/opt/sahar-agent/data/config.json')
with path.open('r', encoding='utf-8') as fh:
    data = json.load(fh)
print(data.get('agent_tls_fingerprint', ''))
PY"""
        value = self._run(ssh, cmd, password, use_sudo=use_sudo, timeout=30).strip()
        if not value:
            raise ProvisionError('agent TLS fingerprint was not generated during installation')
        return value
    def _wait_for_health(self, client: AgentClient, timeout: int = 120) -> Dict[str, Any]:
        deadline = time.time() + timeout
        last_error = ''
        while time.time() < deadline:
            try:
                return client.health()['data']
            except Exception as exc:
                last_error = str(exc)
                time.sleep(3)
        raise ProvisionError(f'agent health check timed out: {last_error or "unknown error"}')

    @staticmethod
    def _detect_allowed_source_for_host(host: str, port: int) -> str:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return ''
        for family, _socktype, _proto, _canonname, sockaddr in infos:
            try:
                with socket.socket(family, socket.SOCK_DGRAM) as sock:
                    sock.connect(sockaddr)
                    local_ip = sock.getsockname()[0]
                if ':' in local_ip:
                    return f'{local_ip}/128'
                return f'{local_ip}/32'
            except OSError:
                continue
        return ''

    @staticmethod
    def _infer_host_mode(host: str) -> str:
        try:
            ipaddress.ip_address(host)
            return 'ip'
        except ValueError:
            return 'domain'
