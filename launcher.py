import os
import sys
from pathlib import Path


def is_packaged_app():
    return ".app/Contents/MacOS" in str(Path(sys.executable).resolve())


def resolve_app_script_path():
    if is_packaged_app():
        exe_path = Path(sys.executable).resolve()
        resources_dir = exe_path.parent.parent / "Resources"
        app_script = resources_dir / "app.py"
        if app_script.exists():
            return app_script
        raise FileNotFoundError(f"app.py not found in packaged resources: {app_script}")

    repo_root = Path(__file__).resolve().parent
    return repo_root / "app.py"


def resolve_runtime_root():
    env_root = os.getenv("TALKTODATA_HOME", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    if is_packaged_app():
        exe_path = Path(sys.executable).resolve()
        app_bundle = exe_path.parent.parent.parent
        companion = app_bundle.parent / "TalkToData-data"
        return companion.resolve()

    default_root = Path.home() / "Desktop" / "TalkToData-data"
    return default_root.resolve()


def prepare_runtime_root(runtime_root):
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "documents").mkdir(parents=True, exist_ok=True)


def main():
    runtime_root = resolve_runtime_root()
    prepare_runtime_root(runtime_root)
    os.environ["TALKTODATA_HOME"] = str(runtime_root)

    app_script = resolve_app_script_path()
    if not app_script.exists():
        raise FileNotFoundError(f"Streamlit app script not found: {app_script}")

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(app_script),
        "--server.headless=false",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
