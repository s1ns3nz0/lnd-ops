"""Render host service definitions without changing host state."""
import json
import pathlib
import plistlib
import re

LABEL = "org.lndops.router-monitor"
UNIT = "lnd-ops-router-monitor.service"
MARKER = "Managed by lnd-ops router-service"


def absolute(value):
    value = str(value)
    if not pathlib.Path(value).is_absolute() or any(ord(c) < 32 for c in value):
        raise ValueError("서비스 경로는 제어 문자가 없는 절대 경로여야 합니다")
    return value


def configuration(repo, python, home, state, kubeconfig, path, user):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.-]*\$?", user) or user == "root":
        raise ValueError("서비스는 일반 사용자로 실행해야 합니다")
    directories = path.split(":")
    for directory in directories:
        absolute(directory)
    return {"repo": absolute(repo), "python": absolute(python), "user": user,
            "environment": {"HOME": absolute(home), "XDG_STATE_HOME": absolute(state),
                            "KUBECONFIG": absolute(kubeconfig), "PATH": ":".join(directories)}}


def systemd_quote(value, executable=False):
    # systemd unit specifiers and ExecStart environment expansion are distinct
    # from shell quoting; these services never invoke a shell.
    value = value.replace("%", "%%")
    if executable:
        value = value.replace("$", "$$")
    return json.dumps(value, ensure_ascii=False)


def render_linux(config):
    command = [config["python"], config["repo"] + "/ops/router-monitor"]
    env = "\n".join("Environment=" + systemd_quote(f"{key}={value}")
                    for key, value in config["environment"].items())
    return (f"# {MARKER}\n[Unit]\nDescription=LND Ops Router monitoring\n"
            "After=network-online.target k3s.service\nWants=network-online.target\n"
            "StartLimitIntervalSec=300\nStartLimitBurst=5\n\n[Service]\nType=exec\n"
            f"User={config['user']}\n{env}\n"
            f"ExecStart={' '.join(systemd_quote(arg, True) for arg in command)}\n"
            "Restart=on-failure\nRestartSec=30\nTimeoutStopSec=10\nKillMode=control-group\n"
            "UMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\n\n"
            "[Install]\nWantedBy=multi-user.target\n")


def render_macos(config):
    helper = "router-vm-start" if config.get("start_vm") else "router-monitor"
    return plistlib.dumps({"Label": LABEL, "Comment": MARKER,
                          "ProgramArguments": [config["python"], config["repo"] + "/ops/" + helper],
                          "EnvironmentVariables": config["environment"],
                          "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
                          "ExitTimeOut": 10, "Umask": 0o077}).decode()
