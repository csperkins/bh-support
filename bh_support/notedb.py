#!/usr/bin/env python3.9
#
# Copyright (c) 2020-2022 Colin Perkins
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

from typing  import Dict, List
from pathlib import Path

# =================================================================================================
# Code to communicate with the running Bear application:

class XCallError(Exception):
    def __init__(self, reason):
        self.reason = reason


def xcall(scheme:str, action:str, parameters:Dict[str,str] = {}):
    params = urllib.parse.urlencode(parameters, quote_via=urllib.parse.quote)
    url    = F"{scheme}://x-callback-url/{action}?{params}"
    args   = ["/Applications/xcall.app/Contents/MacOS/xcall", "-url", url]
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        stdout, stderr = proc.communicate()
        if   stdout != b"" and stderr == b"":
            return json.loads(stdout)
        elif stdout == b"" and stderr != b"":
            raise XCallError(json.loads(stderr))
        else:
            print("subprocess failed with no output - this should never happen ")
            sys.exit()


# =================================================================================================
# The NoteDB class provides an efficient way of accessing the notes. It
# works using a local backup of the Bear notes, to avoid having to make
# numerous slow IPC calls to Bear.app.

BACKUP_DIR = "/Users/csp/Backups/Bear"
FILES_DIR  = "/Users/csp/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/Local Files/Note Files/"
IMAGE_DIR  = "/Users/csp/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/Local Files/Note Images/"

class NoteDB:
    _nlist = {}
    _dt    = None
    _ri    = None
    _bib   = None

    def __init__(self) -> None:
        self.synchronise()
        self._dt = None
        self._ri = None


    def _synchronise_attachment(self, atype, path, line):
            i = 0
            b = line.find(f"[{atype}:", i) + len(atype) + 2
            if b is None:
                return
            e = line.find("]", b)
            s = line.find("/", b) + 1
            f = line[b:e]
            assert line[s:e] != "note.md"
            if atype == "file":
                src_path = Path(FILES_DIR) / f
            if atype == "image":
                src_path = Path(IMAGE_DIR) / f
            dst_path = path / line[s:e]
            shutil.copy(src_path, dst_path)
            print(f"             {line[s:e]}")


    def _synchronise_note(self, note, path, ident) -> None:
        print(f"synchronise: {note['title']}")
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "note.json", "w") as outf:
            outf.write(json.dumps(note))
        with open(path / "note.md", "w") as outf:
            result  = xcall("bear", "open-note", {"id": ident, "open_note": "no", "show_window": "no"})
            content = result["note"].splitlines()
            for line in content:
                outf.write(line)
                outf.write("\n")
                if "[file:" in line:
                    self._synchronise_attachment("file", path, line)
                if "[image:" in line:
                    self._synchronise_attachment("image", path, line)


    def synchronise(self) -> None:
        self._nlist = {}
        title_changed = []
        active = []
        result = xcall("bear", "search", {"show_window": "no", "token": "EBBE62-71E861-46E1B9"})
        nlist  = json.loads(result["notes"])
        for note in nlist:
            ident = note["identifier"]
            mdate = note["modificationDate"].replace(":", "-")
            path  = Path(BACKUP_DIR) / "active" / ident / mdate

            self._nlist[ident] = note
            active.append(ident)

            tags_changed = False
            json_path = path / "note.json"
            if json_path.exists():
                with open(json_path, "r") as json_file:
                    meta = json.load(json_file)
                    if sorted(meta["tags"]) != sorted(note["tags"]):
                        tags_changed = True
            else:
                # Has the note title changed compared to the previously backed-up version?
                note_dates = sorted(list(Path(F"{BACKUP_DIR}/active/{ident}/").glob("*")))
                if note_dates != []:
                    json_path  = note_dates[-1] / "note.json"
                    with open(json_path, "r") as json_file:
                        meta = json.load(json_file)
                        if meta["title"] != note["title"]:
                            print(f"titleChange: {meta['title']} -> {note['title']}")
                            title_changed.append(meta["title"])

            done = path / ".done"
            if not done.exists() or tags_changed:
                self._synchronise_note(note, path, ident)
                done.touch()

        # When a note title changes, Bear updates wiki-style links to the
        # note with the changed title but doesn't update the modification
        # time of those notes. If there are notes with changed titles, we
        # must manually find those notes that link to them, and back them
        # up.
        for ident in active:
            for link in self.note_links(ident):
                if link in title_changed:
                    note = self._nlist[ident]
                    mdate = note["modificationDate"].replace(":", "-")
                    path  = Path(BACKUP_DIR) / "active" / ident / mdate
                    done = path / ".done"
                    self._synchronise_note(note, path, ident)
                    done.touch()

        # Remove deleted notes
        for note in Path(F"{BACKUP_DIR}/active").glob("*"):
            del_dir = Path(BACKUP_DIR) / "deleted"
            del_dir.mkdir(exist_ok=True)
            if not note.name in active:
                src = Path(BACKUP_DIR) / "active"  / note.name
                dst = Path(BACKUP_DIR) / "deleted" / note.name
                if dst.exists():
                    print(f"ERROR: deleted note was already deleted? {note.name}")
                else:
                    src.rename(dst)
                    print(f"{note.name} deleted")


    def create_note(self, title, body):
        print(f"create note: {title}")
        xcall("bear", "create", {"title": title, "text": body})
        self.synchronise()


    def note_list(self) -> List[Dict[str,str]]:
        # This returns a list containing information about all the notes in
        # the backup, where each entry is a dictionary formatted as follows:
        #
        #   {
        #     'creationDate': '2019-07-07T13:02:42Z', 
        #     'tags': '[]', 
        #     'title': 'Index', 
        #     'modificationDate': '2021-11-15T08:45:59Z', 
        #     'identifier': '3C2749F1-34B3-4333-A658-CCAD4B38B7A6-23171-0001BB008509F4D7', 
        #     'pin': 'yes'
        #   }
        #
        return self._nlist.values()


    def has_note_with_title(self, note_title:str) -> bool:
        # This returns `True` if a note with the given `note_title` exists
        for note in self._nlist.values():
            if note["title"] == note_title:
                return True
        return False


    def note_exists(self, note_id:str) -> bool:
        # This returns `True` if a note with the given `note_id` is in the backup.
        return note_id in self._nlist.keys()


    def note_info(self, note_id:str) -> Dict[str,str]:
        # Returns information about a single note in the backup. The returned value
        # is a dictionary formatted as for the `note_list()` method.
        return self._nlist[note_id]


    def note_contents(self, note_id:str) -> List[str]:
        # Returns the contents of a particular note
        note_dates = sorted(list(Path(F"{BACKUP_DIR}/active/{note_id}/").glob("*")))
        note_file  = note_dates[-1] / "note.md"
        with open(note_file, "r") as inf:
            note = inf.read().splitlines()
        return note


    def note_links(self, note_id:str) -> List[str]:
        # Returns the list of notes that this has links to
        links = []
        for line in self.note_contents(note_id):
            offset = 0
            found  = True
            while found:
                start  = line.find("[[", offset)
                if start == -1:
                    found = False
                else:
                    finish = line.find("]]", start)
                    if finish == -1:
                        print(f"ERROR: unterminated link in note {note_id}")
                        print(f"  {line}")
                        sys.exit()
                    link = line[start + 2:finish]
                    if not link in links:
                        links.append(link)
                    offset = finish + 2
        return links


    def add_to_note(self, note_title, text_to_add):
        print(f"update note: {note_title}")
        result = xcall("bear", "add-text", {"title": note_title, 
                                            "text" : text_to_add,
                                            "show_window": "no",
                                            "mode" : "append"})
        self.synchronise()



