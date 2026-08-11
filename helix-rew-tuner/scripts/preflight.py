#!/usr/bin/env python3
"""Read-only dependency and layout preflight for helix-rew-tuner."""

import argparse
import json
import re
import sys
from pathlib import Path


MINIMUM_PYTHON = (3, 9)
DEPENDENCIES = {
    "numpy": ("NumPy", (1, 23, 0)),
    "scipy": ("SciPy", (1, 9, 0)),
}


def _final_release_tuple(value):
    """Parse a PEP 440 final/post release, rejecting unstable/local forms."""
    match = re.fullmatch(
        r"[vV]?(\d+(?:\.\d+)*)(?:\.post\d+)?", str(value).strip(), re.IGNORECASE)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _release_at_least(release, minimum):
    width = max(len(release), len(minimum))
    return (release + (0,) * (width - len(release))
            >= minimum + (0,) * (width - len(minimum)))


def _required_text(version):
    return ">=" + ".".join(str(part) for part in version)


def _runtime_check(module_name, display_name, minimum, module_loader):
    required = _required_text(minimum)
    install = "python -m pip install -r requirements.txt"
    try:
        module = module_loader(module_name)
    except (ImportError, ModuleNotFoundError) as exc:
        return {
            "ok": False,
            "version": None,
            "required": required,
            "message": "%s is unavailable (%s). Run `%s` from the skill directory."
                       % (display_name, exc, install),
        }
    version = str(getattr(module, "__version__", "unknown"))
    release = _final_release_tuple(version)
    ok = release is not None and _release_at_least(release, minimum)
    message = "%s %s is ready (requires %s)." % (display_name, version, required)
    if release is None:
        message = ("%s %s is not a supported final release; %s is required. "
                   "Run `%s`." % (display_name, version, required, install))
    elif not ok:
        message = ("%s %s is too old; %s is required. Run `%s`."
                   % (display_name, version, required, install))
    return {"ok": ok, "version": version, "required": required,
            "message": message}


def _path_check(path, label):
    resolved = path.resolve()
    ok = resolved.is_dir()
    message = ("%s found at %s." % (label, resolved) if ok else
               "%s is missing at %s; reinstall the complete skill folder."
               % (label, resolved))
    return {"ok": ok, "path": str(resolved), "message": message}


def collect_preflight(module_loader=__import__):
    """Return dependency and skill-path checks without modifying the system."""
    skill_root = Path(__file__).resolve().parents[1]
    py_version = tuple(sys.version_info[:3])
    py_required = _required_text(MINIMUM_PYTHON)
    py_ok = py_version >= MINIMUM_PYTHON
    py_text = ".".join(str(part) for part in py_version)
    python_check = {
        "ok": py_ok,
        "version": py_text,
        "required": py_required,
        "message": ("Python %s is ready (requires %s)." % (py_text, py_required)
                    if py_ok else
                    "Python %s is too old; install Python %s and rerun this preflight."
                    % (py_text, py_required)),
    }
    runtime = {"python": python_check}
    for module_name, (display_name, minimum) in DEPENDENCIES.items():
        runtime[module_name] = _runtime_check(
            module_name, display_name, minimum, module_loader)
    paths = {
        "skill_root": _path_check(skill_root, "Skill root"),
        "scripts": _path_check(skill_root / "scripts", "Scripts directory"),
        "references": _path_check(skill_root / "references", "References directory"),
    }
    failures = [check["message"] for check in list(runtime.values()) + list(paths.values())
                if not check["ok"]]
    return {
        "skill": "helix-rew-tuner",
        "ready": not failures,
        "runtime": runtime,
        "paths": paths,
        "failures": failures,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check helix-rew-tuner dependencies and paths without installing anything.")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args(argv)
    report = collect_preflight()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("helix-rew-tuner preflight: %s" % ("READY" if report["ready"] else "NOT READY"))
        for group in ("runtime", "paths"):
            for name, check in report[group].items():
                print("[%s] %s: %s" % ("ok" if check["ok"] else "fail", name,
                                        check["message"]))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
