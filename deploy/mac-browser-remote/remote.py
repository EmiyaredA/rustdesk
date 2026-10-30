#!/usr/bin/env python3
"""Manage the isolated Mac remote desktop deployment (Python standard library only)."""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
DEFAULT_ADMIN_HASH = "CA458A7D494E3BE824F5E1E175A1556C0F8EEF2C2D7DF3633BEC4A29C4411960"


class DeploymentError(Exception):
    pass


def run(args, *, data=None, output=None, env=None):
    result = subprocess.run(
        args, input=data, stdout=output or subprocess.PIPE,
        stderr=subprocess.PIPE, env=env,
    )
    if result.returncode:
        # SQL and container errors can include credentials or restored data.
        raise DeploymentError(f"Command failed ({result.returncode}): {' '.join(map(str, args))}")
    return result.stdout if output is None else b""


def sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def password_hash(password, salt):
    return hashlib.sha256((password + salt.upper()).encode("utf-8")).hexdigest()


def ask_password(prompt, *, minimum=1):
    if not sys.stdin.isatty():
        raise DeploymentError("Password entry requires an interactive terminal; do not pass passwords as arguments.")
    first = getpass.getpass(prompt)
    if len(first) < minimum:
        raise DeploymentError(f"Password must contain at least {minimum} characters.")
    if first != getpass.getpass("Confirm password: "):
        raise DeploymentError("Passwords do not match.")
    return first


def private_file(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


class Deployment:
    def __init__(self, server=False):
        self.server = server
        self.env = os.environ.copy()
        env_file = ROOT / ".env"
        if env_file.exists():
            if env_file.stat().st_mode & 0o077:
                raise DeploymentError(".env must be private: chmod 600 .env")
            for line in env_file.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    self.env[key.strip()] = value.strip()
        self.compose = [
            "docker", "compose", "--project-directory", str(ROOT),
            "-f", str(ROOT / "compose.yml"),
            "-f", str(ROOT / ("compose.server.yml" if server else "compose.local.yml")),
        ]

    def dc(self, *args, **kwargs):
        return run(self.compose + list(args), env=self.env, **kwargs)

    def engine(self):
        try:
            run(["docker", "info", "--format", "{{.Architecture}}"])
        except (FileNotFoundError, DeploymentError) as error:
            raise DeploymentError("Docker is unavailable. Start Docker Desktop on Mac, or Docker Engine on Linux.") from error

    def config(self):
        if not (ROOT / ".env").exists():
            raise DeploymentError("Run python3 remote.py init first.")
        if self.env.get("POSTGRES_PASSWORD", "").startswith("replace-"):
            raise DeploymentError("Replace the example database password; normally init generates .env for you.")
        if self.server:
            domain = self.env.get("PUBLIC_DOMAIN", "")
            if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", domain) or "." not in domain:
                raise DeploymentError("Set PUBLIC_DOMAIN to your DNS name in .env, without scheme or path.")
            try:
                ipaddress.ip_address(domain)
            except ValueError:
                pass
            else:
                raise DeploymentError("The server template requires a DNS name, not an IP address.")
            if domain.endswith("example.com"):
                raise DeploymentError("Replace the example domain with your own DNS name.")
        self.dc("config", "--quiet")

    def server_networks(self):
        if not self.server:
            return
        if not sys.platform.startswith("linux"):
            raise DeploymentError("--server is for a Linux host. Use the local deployment on Mac.")
        routes = json.loads(run(["ip", "-j", "route", "show", "table", "all"]))
        reserved = {"wg0": ipaddress.ip_network("10.66.0.0/24"),
                    "br-mac-remote": ipaddress.ip_network("172.30.66.0/24")}
        for route in routes:
            destination = route.get("dst", "default")
            if destination == "default":
                continue
            network = ipaddress.ip_network(destination, strict=False)
            for interface, subnet in reserved.items():
                if network.overlaps(subnet) and route.get("dev") != interface:
                    raise DeploymentError(f"Network conflict: {destination} via {route.get('dev')} overlaps {subnet}.")

    def sql(self, query, database="guacamole"):
        return self.dc(
            "exec", "-T", "postgres", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
            "-U", "guacamole", "-d", database, data=query.encode(),
        ).decode().strip()

    def initialized(self, database="guacamole"):
        exists = self.sql("SELECT to_regclass('public.guacamole_user') IS NOT NULL;", database)
        if exists != "t":
            return False
        safe = self.sql(
            "SELECT count(*) FROM guacamole_user u JOIN guacamole_entity e USING(entity_id) "
            "WHERE e.type='USER' AND e.name='guacadmin' AND NOT u.disabled "
            f"AND upper(encode(u.password_hash,'hex')) <> '{DEFAULT_ADMIN_HASH}';", database,
        )
        return safe == "1"

    def init(self):
        self.engine()
        self.server_networks()
        if not (ROOT / ".env").exists():
            project = self.env.get("COMPOSE_PROJECT_NAME", "mac-browser-remote")
            volumes = run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"])
            if volumes.strip():
                raise DeploymentError("Existing volumes found without .env. Recover the original .env instead of generating a new database password.")
            value = secrets.token_hex(32)
            domain = self.env.get("PUBLIC_DOMAIN", "")
            if "\n" in domain or "\r" in domain:
                raise DeploymentError("PUBLIC_DOMAIN must be a single DNS name.")
            with private_file(ROOT / ".env") as stream:
                stream.write(f"POSTGRES_PASSWORD={value}\nPUBLIC_DOMAIN={domain}\n".encode())
            self.env["POSTGRES_PASSWORD"] = value
        self.config()
        self.dc("up", "-d", "--wait", "postgres")
        if self.sql("SELECT to_regclass('public.guacamole_user') IS NOT NULL;") == "t":
            if not self.initialized():
                raise DeploymentError("Existing database has no safe bootstrap admin. Refusing to overwrite it; restore a trusted backup.")
            print("Already initialized; accounts, passwords and connections were preserved.")
            return

        admin = ask_password("New guacadmin password (at least 12 characters): ", minimum=12)
        vnc = ask_password("Existing Mac VNC password (not your macOS login password): ")
        salt = secrets.token_hex(32).upper()
        hashed = password_hash(admin, salt)
        schema = self.dc("run", "--rm", "--no-deps", "-T", "guacamole", "/opt/guacamole/bin/initdb.sh", "--postgresql")
        host = "10.66.0.2" if self.server else "host.docker.internal"
        parameters = {
            "hostname": host, "port": "5900", "password": vnc,
            "disable-display-resize": "true", "read-only": "false",
            "enable-audio": "false", "enable-sftp": "false", "clipboard-encoding": "UTF-8",
        }
        patch = (
            "\nUPDATE guacamole_user SET password_hash=decode('" + hashed + "','hex'), "
            "password_salt=decode('" + salt + "','hex'), password_date=CURRENT_TIMESTAMP "
            "WHERE entity_id=(SELECT entity_id FROM guacamole_entity WHERE name='guacadmin' AND type='USER');\n"
            "INSERT INTO guacamole_connection (connection_name,protocol,max_connections,max_connections_per_user) "
            "VALUES ('My Mac','vnc',1,1);\n"
        )
        for key, value in parameters.items():
            patch += (
                "INSERT INTO guacamole_connection_parameter SELECT connection_id, "
                f"{sql_string(key)}, {sql_string(value)} FROM guacamole_connection WHERE connection_name='My Mac';\n"
            )
        self.dc(
            "exec", "-T", "postgres", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction",
            "-U", "guacamole", "-d", "guacamole", data=schema + patch.encode(),
        )
        if not self.initialized():
            raise DeploymentError("Bootstrap verification failed; the website was not started.")
        print("Initialized guacadmin and My Mac. Run up, enroll TOTP, then create your daily-use account.")

    def up(self):
        self.config()
        self.server_networks()
        self.dc("up", "-d", "--wait", "postgres")
        if not self.initialized():
            raise DeploymentError("Database is not safely initialized. Run init; website was not started.")
        print("Building the VNC compatibility plugin (the first build may take a few minutes)...", flush=True)
        result = subprocess.run(self.compose + ["build", "guacd"], env=self.env)
        if result.returncode:
            raise DeploymentError("VNC compatibility build failed; existing containers and data were retained.")
        self.dc("up", "-d")
        url = f"https://{self.env['PUBLIC_DOMAIN']}" if self.server else "http://127.0.0.1:8080"
        print(f"Starting: {url}/guacamole/ (allow Tomcat time to start)")

    def check(self):
        self.engine()
        self.config()
        self.server_networks()
        print("Docker and Compose configuration: OK")
        config = json.loads(self.dc("config", "--format", "json"))
        for service in ("postgres", "guacd"):
            if config["services"][service].get("ports"):
                raise DeploymentError(f"{service} must not publish host ports.")
        if not self.server:
            for binding in config["services"]["guacamole"].get("ports", []):
                if binding.get("host_ip") != "127.0.0.1":
                    raise DeploymentError("Local web port must bind only to 127.0.0.1.")
            running = self.dc("ps", "--status", "running", "--services").decode().splitlines()
            if "guacamole" not in running:
                with socket.socket() as sock:
                    try:
                        sock.bind(("127.0.0.1", 8080))
                    except OSError as error:
                        raise DeploymentError("Local web port 8080 is already occupied.") from error
        print("Host port isolation: OK")
        if not self.initialized():
            raise DeploymentError("Database bootstrap is incomplete.")
        host = self.sql("SELECT parameter_value FROM guacamole_connection_parameter p JOIN guacamole_connection c USING(connection_id) WHERE c.connection_name='My Mac' AND p.parameter_name='hostname';")
        port = self.sql("SELECT parameter_value FROM guacamole_connection_parameter p JOIN guacamole_connection c USING(connection_id) WHERE c.connection_name='My Mac' AND p.parameter_name='port';")
        if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise DeploymentError("My Mac connection needs a hostname and valid port.")
        greeting = self.dc(
            "exec", "-T", "guacd", "/bin/sh", "-c",
            'nc -w 3 "$1" "$2" | head -c 12', "check-vnc", host, port,
        )
        if not greeting.startswith(b"RFB "):
            raise DeploymentError("VNC greeting not received from the guacd network. Check Mac Screen Sharing, routing and firewall; authentication is not yet tested.")
        print("VNC protocol greeting: OK (password, desktop and input still require browser verification)")

    def backup(self):
        folder = ROOT / "backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        folder.chmod(0o700)
        path = folder / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".dump")
        stream = private_file(path)
        try:
            with stream:
                self.dc("exec", "-T", "postgres", "pg_dump", "-U", "guacamole", "-d", "guacamole", "-Fc", "--no-owner", "--no-acl", output=stream)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        print(f"Private database backup: {path}")
        return path

    def restore(self, path):
        archive = Path(path).expanduser().resolve().read_bytes()
        self.dc("exec", "-T", "postgres", "pg_restore", "--list", data=archive)
        database = "guac_restore_" + secrets.token_hex(6)
        self.dc("exec", "-T", "postgres", "createdb", "-U", "guacamole", database)
        try:
            self.dc("exec", "-T", "postgres", "pg_restore", "-U", "guacamole", "-d", database, "--no-owner", "--no-acl", "--exit-on-error", data=archive)
            if not self.initialized(database):
                raise DeploymentError("Backup is not a safely initialized Guacamole database; live data was not changed.")
        finally:
            self.dc("exec", "-T", "postgres", "dropdb", "-U", "guacamole", database)
        self.dc("stop", "guacamole")
        self.backup()
        self.dc(
            "exec", "-T", "postgres", "pg_restore", "-U", "guacamole", "-d", "guacamole",
            "--clean", "--if-exists", "--single-transaction", "--no-owner", "--no-acl", data=archive,
        )
        print("Restored. Website remains stopped; run up when ready. Existing backup TOTP keys are restored too.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true", help="use Linux/Caddy deployment instead of local loopback HTTP")
    parser.add_argument("command", choices=["check", "init", "up", "down", "status", "logs", "backup", "restore"])
    parser.add_argument("archive", nargs="?", help="trusted .dump produced by backup; required for restore")
    args = parser.parse_args()
    if (args.command == "restore") != bool(args.archive):
        parser.error("Only restore accepts (and requires) an archive path.")
    try:
        deployment = Deployment(args.server)
        if args.command == "init":
            deployment.init()
        else:
            deployment.engine()
            deployment.config()
            if args.command in ("check", "up", "backup"):
                getattr(deployment, args.command)()
            elif args.command == "restore":
                deployment.restore(args.archive)
            elif args.command == "down":
                deployment.dc("down")
                print("Stopped; persistent data and certificates were retained.")
            elif args.command == "status":
                print(deployment.dc("ps").decode(), end="")
            else:
                print(deployment.dc("logs", "--no-color", "--tail", "100", "guacamole", "guacd").decode(), end="")
    except (DeploymentError, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
