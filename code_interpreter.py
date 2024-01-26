import asyncio
import atexit
import base64
import glob
import io
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

import matplotlib
import PIL.Image
from jupyter_client import BlockingKernelClient

sys.path.insert(0, str(Path(__file__).absolute().parent.parent.parent))  # NOQA


import traceback


def print_traceback():
    print("".join(traceback.format_exception(*sys.exc_info())))


def extract_code(text):
    return text


WORK_DIR = os.getenv("M6_CODE_INTERPRETER_WORK_DIR", os.getcwd() + "/ci_workspace/")

STATIC_URL = os.getenv("M6_CODE_INTERPRETER_STATIC_URL", "http://127.0.0.1:7866/static")

LAUNCH_KERNEL_PY = """
from ipykernel import kernelapp as app
app.launch_new_instance()
"""

INIT_CODE_FILE = str(
    Path(__file__).absolute().parent / "resource" / "code_interpreter_init_kernel.py"
)

ALIB_FONT_FILE = str(
    Path(__file__).absolute().parent / "resource" / "AlibabaPuHuiTi-3-45-Light.ttf"
)

_KERNEL_CLIENTS: Dict[int, BlockingKernelClient] = {}


def _start_kernel(pid) -> BlockingKernelClient:
    connection_file = os.path.join(WORK_DIR, f"kernel_connection_file_{pid}.json")
    launch_kernel_script = os.path.join(WORK_DIR, f"launch_kernel_{pid}.py")
    for f in [connection_file, launch_kernel_script]:
        if os.path.exists(f):
            print(f"WARNING: {f} already exists")
            os.remove(f)

    os.makedirs(WORK_DIR, exist_ok=True)
    with open(launch_kernel_script, "w") as fout:
        fout.write(LAUNCH_KERNEL_PY)

    kernel_process = subprocess.Popen(
        [
            sys.executable,
            launch_kernel_script,
            "--IPKernelApp.connection_file",
            connection_file,
            "--matplotlib=inline",
            "--quiet",
        ],
        cwd=WORK_DIR,
    )
    print(f"INFO: kernel process's PID = {kernel_process.pid}")

    # Wait for kernel connection file to be written
    while True:
        if not os.path.isfile(connection_file):
            time.sleep(0.1)
        else:
            # Keep looping if JSON parsing fails, file may be partially written
            try:
                with open(connection_file, "r") as fp:
                    json.load(fp)
                break
            except json.JSONDecodeError:
                pass

    # Client
    kc = BlockingKernelClient(connection_file=connection_file)
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    kc.load_connection_file()
    kc.start_channels()
    kc.wait_for_ready()
    return kc


def _kill_kernels():
    for v in _KERNEL_CLIENTS.values():
        v.shutdown()
    for k in list(_KERNEL_CLIENTS.keys()):
        del _KERNEL_CLIENTS[k]


atexit.register(_kill_kernels)
signal.signal(signal.SIGTERM, _kill_kernels)
signal.signal(signal.SIGINT, _kill_kernels)


def _serve_image(image_base64: str) -> str:
    image_file = f"{uuid.uuid4()}.png"
    local_image_file = os.path.join(WORK_DIR, image_file)

    png_bytes = base64.b64decode(image_base64)
    assert isinstance(png_bytes, bytes)
    bytes_io = io.BytesIO(png_bytes)
    PIL.Image.open(bytes_io).save(local_image_file, "png")

    image_url = f"{STATIC_URL}/{image_file}"
    return image_url


def _escape_ansi(line: str) -> str:
    ansi_escape = re.compile(r"(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", line)


def _fix_matplotlib_cjk_font_issue():
    ttf_name = os.path.basename(ALIB_FONT_FILE)
    local_ttf = os.path.join(
        os.path.abspath(os.path.join(matplotlib.matplotlib_fname(), os.path.pardir)),
        "fonts",
        "ttf",
        ttf_name,
    )
    if not os.path.exists(local_ttf):
        try:
            shutil.copy(ALIB_FONT_FILE, local_ttf)
            font_list_cache = os.path.join(matplotlib.get_cachedir(), "fontlist-*.json")
            for cache_file in glob.glob(font_list_cache):
                with open(cache_file) as fin:
                    cache_content = fin.read()
                if ttf_name not in cache_content:
                    os.remove(cache_file)
        except Exception:
            print_traceback()


def _execute_code(kc: BlockingKernelClient, code: str) -> str:
    kc.wait_for_ready()
    kc.execute(code)
    result = ""
    image_idx = 0
    while True:
        text = ""
        image = ""
        finished = False
        msg_type = "error"
        try:
            msg = kc.get_iopub_msg()
            msg_type = msg["msg_type"]
            if msg_type == "status":
                if msg["content"].get("execution_state") == "idle":
                    finished = True
            elif msg_type == "execute_result":
                text = msg["content"]["data"].get("text/plain", "")
                # if "image/png" in msg["content"]["data"]:
                #     image_b64 = msg["content"]["data"]["image/png"]
                #     image_url = _serve_image(image_b64)
                #     image_idx += 1
                #     image = "![fig-%03d](%s)" % (image_idx, image_url)
            elif msg_type == "display_data":
                if "image/png" in msg["content"]["data"]:
                    image_b64 = msg["content"]["data"]["image/png"]
                    image_url = _serve_image(image_b64)
                    image_idx += 1
                    image = "![fig-%03d](%s)" % (image_idx, image_url)
                else:
                    text = msg["content"]["data"].get("text/plain", "")
            elif msg_type == "stream":
                msg_type = msg["content"]["name"]  # stdout, stderr
                text = msg["content"]["text"]
            elif msg_type == "error":
                text = _escape_ansi("\n".join(msg["content"]["traceback"]))
                if "M6_CODE_INTERPRETER_TIMEOUT" in text:
                    text = "Timeout: Code execution exceeded the time limit."
        except queue.Empty:
            text = "Timeout: Code execution exceeded the time limit."
            finished = True
        except Exception:
            text = "The code interpreter encountered an unexpected error."
            print_traceback()
            finished = True
        if text:
            # result += f"\n\n{msg_type}:\n\n```\n{text}\n```"
            result += f"{text}"
        if image:
            result += f"\n\n{image}"
        if finished:
            break
    result = result.strip("\n")
    return result


# @register_tool('code_interpreter')
class CodeInterpreter:
    description = "Python代码沙盒，可用于执行Python代码。"
    parameters = [{"name": "code", "type": "string", "description": "待执行的代码"}]

    def __init__(self, cfg: Optional[Dict] = None):
        self.args_format = "此工具的输入应为Markdown代码块。"
        # super().__init__(cfg)

    def call(self, params: str, timeout: Optional[int] = 30, **kwargs) -> str:
        code = params

        pid: int = os.getpid()
        if pid in _KERNEL_CLIENTS:
            kc = _KERNEL_CLIENTS[pid]
        else:
            _fix_matplotlib_cjk_font_issue()
            kc = _start_kernel(pid)
            with open(INIT_CODE_FILE) as fin:
                start_code = fin.read()
                start_code = start_code.replace(
                    "{{M6_FONT_PATH}}", repr(ALIB_FONT_FILE)[1:-1]
                )
            print(_execute_code(kc, start_code))
            _KERNEL_CLIENTS[pid] = kc

        if timeout:
            code = f"_M6CountdownTimer.start({timeout})\n{code}"

        fixed_code = []
        for line in code.split("\n"):
            fixed_code.append(line)
            if line.startswith("sns.set_theme("):
                fixed_code.append(
                    'plt.rcParams["font.family"] = _m6_font_prop.get_name()'
                )
        fixed_code = "\n".join(fixed_code)
        fixed_code += "\n\n"  # Prevent code not executing in notebook due to no line breaks at the end
        result = _execute_code(kc, fixed_code)

        if timeout:
            _execute_code(kc, "_M6CountdownTimer.cancel()")

        return result if result.strip() else "Finished execution."


if __name__ == "__main__":
    tool = CodeInterpreter()
    codes = """
8*8
""".strip()
    print(tool.call(codes))
