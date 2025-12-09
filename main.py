import asyncio
import os
import secrets
import socket
import subprocess
import traceback
from pathlib import Path
import sys

import decky_plugin

logger = decky_plugin.logger

std_out_file = open(Path(decky_plugin.DECKY_PLUGIN_LOG_DIR) / "std-out.log", "w")
std_err_file = open(Path(decky_plugin.DECKY_PLUGIN_LOG_DIR) / "std-err.log", "w")

COPYPARTY_PORT = 3923
ALPHANUM = "abcdefghijklmnopqrstuvwxyz0123456789"
SCRIPT_PATH = Path(decky_plugin.DECKY_PLUGIN_DIR) / "copyparty-sfx.py"


class Plugin:
    _enabled = False
    _password: str | None = None
    _proc: subprocess.Popen | None = None
    _runner_task: asyncio.Task | None = None

    @staticmethod
    def _get_local_ip():
        try:
            # Discover preferred LAN IP without sending traffic
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            logger.info("Failed to resolve local IP")
            logger.info(traceback.format_exc())
            return None

    @staticmethod
    def _generate_password():
        return "".join(secrets.choice(ALPHANUM) for _ in range(6))

    @staticmethod
    def _get_home_dir():
        return (
            os.environ.get("HOME")
            or getattr(decky_plugin, "DECKY_USER_HOME", None)
            or str(Path.home())
        )

    @staticmethod
    def _get_user():
        return (
            os.environ.get("DECKY_USER")
            or os.environ.get("USER")
            or getattr(decky_plugin, "DECKY_USER", None)
            or "deck"
        )

    @staticmethod
    def _build_command():
        # Grant the target user full rw/delete over their home dir
        if not Plugin._password:
            Plugin._password = Plugin._generate_password()
        home_dir = Plugin._get_home_dir()
        user = Plugin._get_user()
        volume_arg = f"{home_dir}::A,{user}"
        auth_arg = f"{user}:{Plugin._password}"
        return [
            "sudo",
            "-u",
            user,
            "-E",
            str(SCRIPT_PATH),
            "-p",
            str(COPYPARTY_PORT),
            "-v",
            volume_arg,
            "-a",
            auth_arg,
        ]

    @staticmethod
    def _stop_process():
        if Plugin._proc and Plugin._proc.poll() is None:
            try:
                Plugin._proc.terminate()
            except Exception:
                logger.info("Failed to terminate copyparty process")
                logger.info(traceback.format_exc())
        Plugin._proc = None

    @staticmethod
    def _start_process():
        env = os.environ.copy()
        home_dir = Plugin._get_home_dir()
        user = Plugin._get_user()
        env["HOME"] = home_dir
        env["USER"] = user
        #logger.info(f"Using Copyparty script at {SCRIPT_PATH} (exists={SCRIPT_PATH.exists()}) with python {sys.executable}")
        cmd = Plugin._build_command()
        logger.info(f"Starting Copyparty on port {COPYPARTY_PORT}")
        Plugin._proc = subprocess.Popen(
            cmd,
            stdout=std_out_file,
            stderr=std_err_file,
            env=env,
        )

    async def is_enabled(self):
        return Plugin._enabled

    async def set_enabled(self, enabled):
        logger.info(f"Set enabled: {enabled}")
        if enabled:
            Plugin._password = Plugin._generate_password()
            Plugin._stop_process()  # ensure restart with fresh password
        else:
            Plugin._stop_process()
        Plugin._enabled = enabled

    async def get_status(self):
        url = None
        ip = self._get_local_ip()
        if Plugin._enabled and ip:
            url = f"http(s)://{ip}:{COPYPARTY_PORT}"
        return {
            "enabled": Plugin._enabled,
            "password": Plugin._password if Plugin._enabled else None,
            "url": url,
            "home": self._get_home_dir(),
            "user": self._get_user(),
        }

    async def copyparty_runner(self):
        await asyncio.sleep(1)
        logger.info("Copyparty runner started")
        while True:
            try:
                if Plugin._enabled:
                    if Plugin._proc is None or Plugin._proc.poll() is not None:
                        Plugin._start_process()
                else:
                    Plugin._stop_process()
            except Exception:
                logger.info(traceback.format_exc())
            await asyncio.sleep(1.0)

    async def _main(self):
        try:
            loop = asyncio.get_event_loop()
            Plugin._runner_task = loop.create_task(Plugin.copyparty_runner(self))
            logger.info("Initialized")
        except Exception:
            logger.exception("main")
