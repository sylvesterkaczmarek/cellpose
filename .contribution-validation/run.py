"""Validate the paper plotting change without models or external datasets."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = Path(os.environ["REVIEW_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
TEST = ROOT / "tests/test_paper_analysis.py"
SOURCE = ROOT / "paper/3.0/analysis.py"
BASE = "a54cb48849b7e225a81e8e43dcb042d42427f543"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == BASE
assert not subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
assert not TEST.exists()
shutil.copyfile(Path(__file__).with_name("test_paper_analysis.py"), TEST)
old = SOURCE.read_text()
node = next(n for n in ast.parse(old).body if isinstance(n, ast.FunctionDef) and n.name == "real_examples")
lines = old.splitlines(keepends=True)
segment = "".join(lines[node.lineno - 1:node.end_lineno])
replacements = [
    ("def real_examples(folder):", "def real_examples(folder, *, save_figures=False):"),
    ('    """ download test_data from CARE and put in folder """',
     '    """Run the real-data examples after downloading CARE test data to folder.\n\n'
     '    Set save_figures=True to save each AP plot as cp_ap.png in that dataset\'s\n'
     '    test_data directory instead of displaying it. Model execution and NumPy\n'
     '    result files are unchanged. Existing plot files at that path are replaced.\n'
     '    """'),
    ("        plt.figure(figsize=(4, 4))", "        fig = plt.figure(figsize=(4, 4))"),
    ("        plt.show()\n", '        if save_figures:\n            try:\n                fig.savefig(root / "cp_ap.png")\n            finally:\n                plt.close(fig)\n        else:\n            plt.show()\n'),
]
for before, after in replacements:
    assert segment.count(before) == 1, before
    segment = segment.replace(before, after)
fixed = "".join(lines[:node.lineno - 1]) + segment + "".join(lines[node.end_lineno:])
ast.parse(fixed)
runs = []


def run(label):
    xml = OUT / f"{label}.xml"
    command = [sys.executable, "-m", "pytest", "--confcutdir=tests", str(TEST), "-q", f"--junitxml={xml}"]
    with (OUT / f"{label}.log").open("w") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    print((OUT / f"{label}.log").read_text(), flush=True)
    document = ET.parse(xml).getroot()
    counts = {key: sum(int(s.get(key, 0)) for s in document.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    record = {"label": label, "command": command, "exit_code": result.returncode, **counts}
    runs.append(record)
    return record


red = run("original")
assert red["exit_code"] == 1 and red["failures"] == 3 and red["errors"] == 0, red
SOURCE.write_text(fixed)
green = run("fixed")
assert green["exit_code"] == 0 and green["tests"] == 4 and green["skipped"] == 0, green
subprocess.run(["git", "diff", "--check"], check=True)
files = [str(p.relative_to(ROOT)) for p in [SOURCE, TEST]]
for name in files:
    target = OUT / "files" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / name, target)
summary = {"base": BASE, "issue": 1499, "files": files, "runs": runs,
           "source_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
           "scope": "Paper plotting only, real Matplotlib/NumPy output with synthetic model and image inputs; root model-dependent fixtures excluded",
           "limits": ["Missing datasets and paper labels are not resolved", "No inference or full --runslow validation", "Cellpose maintainer exception required for assisted implementation"],
           "upstream_pr_submitted": False}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
subprocess.run(["git", "add", "--", *files], check=True)
(OUT / "patch.diff").write_bytes(subprocess.check_output(["git", "diff", "--cached", "--binary"]))
assert sorted(subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()) == sorted(files)
print("VALIDATED", json.dumps(summary), flush=True)
