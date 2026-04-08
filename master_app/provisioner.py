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

import paramiko

from agent_client import AgentClient


class ProvisionError(Exception):
    pass


class SSHProvisioner:
    def __init__(self, project_root: str | Path, timeout: int = 30):
        self.project_root = Path(project_root)
        self.timeout = timeout

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
        api_url = f"http://{host}:{agent_listen_port}"
        allowed_sources = self._detect_allowed_source_for_host(host, ssh_port)

        ssh = self._connect(host, ssh_port, ssh_username, ssh_password)
        try:
            if ssh_username != 'root':
                self._ensure_sudo_ready(ssh, ssh_password)
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

            # best-effort cleanup
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

        client = AgentClient(api_url, agent_token, timeout=self.timeout)
        health = self._wait_for_health(client)
        return api_url, agent_token, health

    def _build_bundle(self) -> str:
        tmp = tempfile.NamedTemporaryFile(prefix='sahar-agent-', suffix='.tar.gz', delete=False)
        tmp.close()
        with tarfile.open(tmp.name, 'w:gz') as tar:
            tar.add(self.project_root / 'install_agent.sh', arcname='install_agent.sh')
            tar.add(self.project_root / 'agent_app', arcname='agent_app')
        return tmp.name

    def _connect(self, host: str, port: int, username: str, password: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
        except (socket.error, paramiko.SSHException) as exc:
            raise ProvisionError(f'SSH connection failed: {exc}') from exc
        return client

    def _run(self, ssh: paramiko.SSHClient, command: str, password: str, use_sudo: bool = False, timeout: int | None = None) -> str:
        timeout = timeout or self.timeout
        if use_sudo:
            wrapped = f"sudo -S -p '' bash -lc {shlex.quote(command)}"
        else:
            wrapped = f"bash -lc {shlex.quote(command)}"
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


    def _deploy_cloudflared_tunnel(self, ssh: paramiko.SSHClient, tunnel_token: str, password: str, *, use_sudo: bool, timeout: int) -> None:
        script = f'''set -e
arch=$(uname -m)
case "$arch" in
  x86_64|amd64|x64) suffix="amd64" ;;
  i386|i686) suffix="386" ;;
  aarch64|arm64|armv8) suffix="arm64" ;;
  armv7l|armv6l|arm) suffix="arm" ;;
  *) echo "unsupported arch for cloudflared: $arch" >&2; exit 1 ;;
esac
curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$suffix" -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
if command -v systemctl >/dev/null 2>&1; then
cat >/etc/systemd/system/sahar-cloudflared.service <<'SERVICE'
[Unit]
Description=Sahar Cloudflare Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token {tunnel_token}
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
command="/usr/local/bin/cloudflared"
command_args="tunnel --no-autoupdate run --token {tunnel_token}"
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
/usr/local/bin/cloudflared tunnel --no-autoupdate run --token {tunnel_token} >/tmp/sahar-cloudflared.log 2>&1 &
fi
'''
        self._run(ssh, script, password, use_sudo=use_sudo, timeout=timeout)

    def _wait_for_health(self, client: AgentClient) -> Dict[str, Any]:
        deadline = time.time() + 180
        last_error = 'agent did not become healthy in time'
        while time.time() < deadline:
            try:
                return client.health().get('data', {})
            except Exception as exc:
                last_error = str(exc)
                time.sleep(5)
        raise ProvisionError(last_error)

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
