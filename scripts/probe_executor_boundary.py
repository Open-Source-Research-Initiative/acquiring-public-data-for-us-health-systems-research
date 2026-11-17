#!/usr/bin/env python3
"""Synthetic local namespace visibility probe; does not qualify an agent boundary."""
import json
import os
import shutil
import subprocess
import tempfile


def main():
    result = {"probe": "synthetic_namespace_visibility", "qualified": False,
              "qualification_reason": "A child namespace does not constrain model or host tools.",
              "unshare_path": shutil.which("unshare"), "mount_path": shutil.which("mount")}
    with tempfile.TemporaryDirectory(prefix=".isolation-probe-", dir=os.getcwd()) as root:
        reference = os.path.join(root, "reference")
        empty = os.path.join(root, "empty")
        os.mkdir(reference)
        os.mkdir(empty)
        canary = os.path.join(reference, "canary")
        with open(canary, "w", encoding="utf-8") as output:
            output.write("synthetic canary\n")
        result["host_canary_readable"] = os.access(canary, os.R_OK)
        if result["unshare_path"] and result["mount_path"]:
            command = ('mount --make-rprivate / && mount --bind "$PROBE_DIR/empty" '
                       '"$PROBE_DIR/reference" && '
                       'if test -r "$PROBE_DIR/reference/canary"; then echo CANARY_EXPOSED; '
                       'else echo CANARY_HIDDEN; fi; '
                       'if test -r /etc/passwd; then echo HOST_FILE_VISIBLE; fi')
            process = subprocess.run([result["unshare_path"], "--user", "--map-root-user",
                                      "--mount", "--net", "--fork", "sh", "-c", command],
                                     env={**os.environ, "PROBE_DIR": root}, capture_output=True,
                                     text=True, timeout=10, check=False)
            result["namespace_returncode"] = process.returncode
            result["namespace_stdout"] = process.stdout.splitlines()
            result["namespace_stderr"] = process.stderr.strip()
            result["host_canary_readable_after"] = os.access(canary, os.R_OK)
        else:
            result["namespace_result"] = "unavailable"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
