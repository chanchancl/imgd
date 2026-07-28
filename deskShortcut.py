import subprocess
import traceback
from pathlib import Path
from sys import argv

import winshell


def find_uv_python_exe(project_dir: Path) -> str:
    """通过 uv python dir 找到带图标的真实 python.exe。"""
    result = subprocess.run(
        ["uv", "python", "dir"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    uv_python_dir = Path(result.stdout.strip())

    version = project_dir.joinpath(".python-version").read_text().strip()
    candidates = sorted(uv_python_dir.glob(f"cpython-{version}*"), reverse=True)
    if candidates:
        return str(candidates[0] / "python.exe")
    raise FileNotFoundError(f"找不到 cpython-{version}* 于 {uv_python_dir}")


def create_shortcut(script: Path, icon: str):
    """发送脚本的快捷方式到桌面，指向项目 .venv 中的 python.exe。"""
    venv_python = script.parent / ".venv" / "Scripts" / "python.exe"

    dest = Path.home() / "Desktop" / (script.stem + ".lnk")
    winshell.CreateShortcut(
        Path=str(dest),
        Target=str(venv_python),
        Arguments=f'"{script}"',
        StartIn=str(script.parent),
        Icon=(icon, 0),
        Description=f"[comic] {script.stem}",
    )
    print(f"✓ {script.name} -> {dest}")


def main():
    scripts = [Path(x) for x in argv[1:]]
    project_dir = scripts[0].resolve().parent
    icon = find_uv_python_exe(project_dir)
    for s in scripts:
        create_shortcut(s.resolve(), icon)
    print("Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
