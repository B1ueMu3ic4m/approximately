"""v0.66 — zero-dependency guard: the core imports stdlib only.

The headline claim is "zero dependencies". This test makes it
mechanical: every module-level (top-of-file) import in the core
package must come from the standard library or from approximately
itself. Optional extras (tiktoken, openai) are allowed only as
lazy imports inside function bodies — that is the documented design
("extras stay optional and lazy").
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "src" / "approximately"


# Frozen stdlib-root list (CPython 3.9-era names; pinned instead of
# read from sys.stdlib_module_names, which 3.9 lacks). Over-inclusion
# is harmless for this audit; under-inclusion would false-positive.
_STDLIB_ROOTS = frozenset({
    "__future__", "_abc", "_aix_support", "_android_support",
    "_apple_support", "_ast", "_ast_unparse", "_asyncio", "_bisect",
    "_blake2", "_bz2", "_codecs", "_codecs_cn", "_codecs_hk",
    "_codecs_iso2022", "_codecs_jp", "_codecs_kr", "_codecs_tw",
    "_collections", "_collections_abc", "_colorize", "_compat_pickle",
    "_contextvars", "_csv", "_ctypes", "_curses", "_curses_panel",
    "_datetime", "_dbm", "_decimal", "_elementtree", "_frozen_importlib",
    "_frozen_importlib_external", "_functools", "_gdbm", "_hashlib",
    "_heapq", "_hmac", "_imp", "_interpchannels", "_interpqueues",
    "_interpreters", "_io", "_ios_support", "_json", "_locale", "_lsprof",
    "_lzma", "_markupbase", "_md5", "_multibytecodec", "_multiprocessing",
    "_opcode", "_opcode_metadata", "_operator", "_osx_support",
    "_overlapped", "_pickle", "_posixshmem", "_posixsubprocess", "_py_abc",
    "_py_warnings", "_pydatetime", "_pydecimal", "_pyio", "_pylong",
    "_pyrepl", "_queue", "_random", "_remote_debugging", "_scproxy", "_sha1",
    "_sha2", "_sha3", "_signal", "_sitebuiltins", "_socket", "_sqlite3",
    "_sre", "_ssl", "_stat", "_statistics", "_string", "_strptime",
    "_struct", "_suggestions", "_symtable", "_sysconfig", "_thread",
    "_threading_local", "_tkinter", "_tokenize", "_tracemalloc", "_types",
    "_typing", "_uuid", "_warnings", "_weakref", "_weakrefset", "_winapi",
    "_wmi", "_zoneinfo", "_zstd", "abc", "annotationlib", "antigravity",
    "argparse", "array", "ast", "asyncio", "atexit", "base64", "bdb",
    "binascii", "bisect", "builtins", "bz2", "cProfile", "calendar", "cmath",
    "cmd", "code", "codecs", "codeop", "collections", "colorsys",
    "compileall", "compression", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis", "doctest",
    "email", "encodings", "ensurepip", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib",
    "functools", "gc", "genericpath", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "importlib", "inspect", "io", "ipaddress",
    "itertools", "json", "keyword", "linecache", "locale", "logging", "lzma",
    "mailbox", "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "msvcrt", "multiprocessing", "netrc", "nt", "ntpath", "nturl2path",
    "numbers", "opcode", "operator", "optparse", "os", "pathlib", "pdb",
    "pickle", "pickletools", "pkgutil", "platform", "plistlib", "poplib",
    "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
    "py_compile", "pyclbr", "pydoc", "pydoc_data", "pyexpat", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource",
    "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtplib", "socket",
    "socketserver", "sqlite3", "sre_compile", "sre_constants", "sre_parse",
    "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "tempfile", "termios", "textwrap", "this", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "zoneinfo",
})


def _module_level_third_party(path: Path) -> list:
    stdlib = _STDLIB_ROOTS
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []

    def walk_body(body, at_module_level):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Try)):
                # imports nested anywhere below these are lazy/optional
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in stdlib and root != "approximately":
                        offenders.append(f"{path.name}:{node.lineno} "
                                         f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = node.module.split(".")[0] if node.module else ""
                if node.level == 0 and root and root not in stdlib \
                        and root != "approximately":
                    offenders.append(f"{path.name}:{node.lineno} "
                                     f"from {node.module}")
            if at_module_level and isinstance(node, (ast.If, ast.With)):
                walk_body(node.body, True)

    walk_body(tree.body, True)
    return offenders


def test_core_module_level_imports_are_stdlib_only():
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        if "contrib" in path.parts:
            continue  # adapters are optional extras by design
        offenders.extend(_module_level_third_party(path))
    assert offenders == [], (
        "top-level third-party imports break the zero-dependency "
        f"claim: {offenders}")


def test_contrib_adapters_are_excluded_from_the_guard():
    """The guard's contract: contrib/ is outside its scope (adapters
    legitimately import their frameworks at module level)."""
    adapters = list((CORE / "contrib").rglob("*.py"))
    assert adapters, "contrib adapters missing?"


def test_auditor_flags_a_real_violation(tmp_path):
    """Self-test: the auditor catches what it exists to catch."""
    bad = tmp_path / "fake_core.py"
    bad.write_text(
        "import requests\n"
        "import json\n"
        "def f():\n"
        "    import tiktoken  # lazy is fine\n",
        encoding="utf-8")
    offenders = _module_level_third_party(bad)
    assert offenders == ["fake_core.py:1 import requests"]


def test_auditor_allows_lazy_optional_imports(tmp_path):
    good = tmp_path / "fake_core.py"
    good.write_text(
        "import json\n"
        "def f():\n"
        "    import tiktoken\n"
        "def g():\n"
        "    from openai import OpenAI\n",
        encoding="utf-8")
    assert _module_level_third_party(good) == []
