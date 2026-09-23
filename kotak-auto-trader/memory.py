"""Short conversation memory + user profile. Makes follow-ups work
('cancel that', 'no - 10 qty', 'same for INFY') and remembers your prefs."""
import json
import logging
import os

import paths

log = logging.getLogger("memory")

MEM_FILE = paths.data_path("memory.json")
PROFILE_FILE = paths.data_path("user_profile.json")
MAX_TURNS = 8


class Memory:
    def __init__(self):
        self.turns = []
        try:
            if os.path.exists(MEM_FILE):
                self.turns = json.load(open(MEM_FILE)) or []
        except Exception:
            self.turns = []

    def save(self):
        try:
            json.dump(self.turns[-(MAX_TURNS * 2):], open(MEM_FILE, "w"))
        except Exception as e:
            log.warning("mem save: %s", e)

    def add(self, role: str, text: str):
        self.turns.append({"role": role, "text": (text or "")[:400]})
        self.turns = self.turns[-(MAX_TURNS * 2):]
        self.save()

    def context_text(self) -> str:
        return "\n".join(f"{t['role']}: {t['text']}" for t in self.turns)

    def clear(self):
        self.turns = []
        self.save()


class Profile:
    """Things user asked to remember. Cap 20 notes."""

    def __init__(self):
        self.notes = []
        try:
            if os.path.exists(PROFILE_FILE):
                self.notes = json.load(open(PROFILE_FILE)).get("notes", []) or []
        except Exception:
            self.notes = []

    def save(self):
        try:
            json.dump({"notes": self.notes[-20:]}, open(PROFILE_FILE, "w"), indent=1)
        except Exception as e:
            log.warning("profile save: %s", e)

    def add_note(self, note: str):
        self.notes.append(note[:200])
        self.notes = self.notes[-20:]
        self.save()

    def context_text(self) -> str:
        return "; ".join(self.notes[-10:])
