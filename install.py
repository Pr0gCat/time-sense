#!/usr/bin/env python3
"""Install or uninstall time-sense for Claude Code or Codex by copying files.

    python3 install.py claude [--uninstall]
    python3 install.py codex  [--uninstall]

Claude Code:
  - copies skills/time-sense to ~/.claude/skills/time-sense
  - writes the resident rule into ~/.claude/CLAUDE.md between markers
  - merges the enforcement hook into ~/.claude/settings.json
Codex (skills path unverified):
  - copies skills/time-sense to ~/.codex/skills/time-sense
  - writes the resident rule into ~/.codex/AGENTS.md between markers

Re-running replaces the previous install. Existing files are backed up once
as <file>.bak-time-sense before the first change. Python >= 3.9, stdlib only.
omp installs through `omp plugin install` instead (see INSTALL.md).
"""

import argparse
import json
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
BEGIN = "<!-- time-sense:begin -->"
END = "<!-- time-sense:end -->"
HOOK_EVENTS = (
    ("PreToolUse", "Bash"),
    ("PreToolUse", "Agent|Task"),
    ("PostToolUse", "Bash"),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit"),
    ("PostToolUseFailure", "Bash"),
)

TARGETS = {
    "claude": {
        "skills": os.path.join(HOME, ".claude", "skills"),
        "rules": os.path.join(HOME, ".claude", "CLAUDE.md"),
        "settings": os.path.join(HOME, ".claude", "settings.json"),
    },
    "codex": {
        "skills": os.path.join(HOME, ".codex", "skills"),
        "rules": os.path.join(HOME, ".codex", "AGENTS.md"),
        "settings": None,
    },
}


def say(msg):
    print("time-sense: " + msg)


def backup_once(path):
    bak = path + ".bak-time-sense"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)
        say("backed up %s -> %s" % (path, bak))


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def strip_block(text):
    pattern = re.compile(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)
    return pattern.sub("\n", text).rstrip("\n") + ("\n" if text.strip() else "")


def install_skill(cfg):
    dest = os.path.join(cfg["skills"], "time-sense")
    if os.path.islink(dest):
        os.unlink(dest)
    elif os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(
        os.path.join(REPO, "skills", "time-sense"), dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    say("copied skill -> " + dest)
    return dest


def install_rules(cfg, skill_dir):
    tb = os.path.join(skill_dir, "scripts", "tb.py")
    with open(os.path.join(REPO, "rules", "time-sense.md")) as fh:
        rule = fh.read().replace("{{TB}}", tb).strip()
    path = cfg["rules"]
    backup_once(path)
    text = strip_block(read(path))
    block = "%s\n%s\n%s\n" % (BEGIN, rule, END)
    write(path, (text + "\n" if text else "") + block)
    say("wrote rule -> " + path)


def hook_command(skill_dir):
    return "python3 " + os.path.join(skill_dir, "scripts", "claude_hook.py")


def is_ours(handler):
    return "time-sense" in handler.get("command", "") and "claude_hook.py" in handler.get("command", "")


def remove_hooks(settings):
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            group["hooks"] = [h for h in group.get("hooks", []) if not is_ours(h)]
            if group["hooks"]:
                groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)


def load_settings(path):
    text = read(path)
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        sys.exit("time-sense: %s is not valid JSON; fix it first" % path)


def install_hooks(cfg, skill_dir):
    path = cfg["settings"]
    settings = load_settings(path)
    backup_once(path)
    remove_hooks(settings)
    hooks = settings.setdefault("hooks", {})
    for event, matcher in HOOK_EVENTS:
        hooks.setdefault(event, []).append(
            {"matcher": matcher, "hooks": [{"type": "command", "command": hook_command(skill_dir)}]}
        )
    write(path, json.dumps(settings, indent=2) + "\n")
    say("merged hooks -> " + path)


def uninstall(cfg):
    dest = os.path.join(cfg["skills"], "time-sense")
    if os.path.islink(dest):
        os.unlink(dest)
    elif os.path.exists(dest):
        shutil.rmtree(dest)
    say("removed " + dest)
    if os.path.exists(cfg["rules"]):
        write(cfg["rules"], strip_block(read(cfg["rules"])))
        say("removed rule from " + cfg["rules"])
    if cfg["settings"] and os.path.exists(cfg["settings"]):
        settings = load_settings(cfg["settings"])
        remove_hooks(settings)
        write(cfg["settings"], json.dumps(settings, indent=2) + "\n")
        say("removed hooks from " + cfg["settings"])


def main():
    p = argparse.ArgumentParser(description="Install time-sense for Claude Code or Codex.")
    p.add_argument("target", choices=sorted(TARGETS))
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()
    cfg = TARGETS[args.target]
    if args.uninstall:
        uninstall(cfg)
        return 0
    skill_dir = install_skill(cfg)
    install_rules(cfg, skill_dir)
    if cfg["settings"]:
        install_hooks(cfg, skill_dir)
    say("done; start a new %s session to load it" % args.target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
