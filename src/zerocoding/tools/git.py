
import subprocess


def run_git(args, cwd=None):
    return subprocess.check_output(["git"] + list(args), cwd=cwd, text=True).strip()
