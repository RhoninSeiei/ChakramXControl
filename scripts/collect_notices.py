"""Collect third-party license notices from the Windows release environment.

Run with the same CPython environment used to build the one-file executable.
For example::

    python scripts/collect_notices.py --output dist/THIRD_PARTY_NOTICES.txt

The collector reads package license files from the installed distributions and
the CPython base installation. It does not download files or inspect source
outside the pinned HIDAPI submodule license text below.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import platform
import sqlite3
import ssl
import sys
import zlib
from pathlib import Path, PurePosixPath


EXPECTED_DISTRIBUTIONS = {
    "pyinstaller": "6.22.3",
    "hidapi": "0.15.0",
}

HIDAPI_SUBMODULE_COMMIT = "d6b2a974608dec3b76fb1e36c189f22b9cf3650c"
HIDAPI_GPL3_SHA256 = "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903"

ZLIB_LICENSE_VERSION = "1.3.1"
ZLIB_LICENSE = """/* zlib.h -- interface of the 'zlib' general purpose compression library
  version 1.3.1, January 22nd, 2024

  Copyright (C) 1995-2024 Jean-loup Gailly and Mark Adler

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.

  Jean-loup Gailly        Mark Adler
  jloup@gzip.org          madler@alumni.caltech.edu

  The data format used by the zlib library is described by RFCs (Request for
  Comments) 1950 to 1952 in the files http://tools.ietf.org/html/rfc1950
  (zlib format), rfc1951 (deflate format) and rfc1952 (gzip format).
*/"""

HIDAPI_CORE_LICENSES = {
    "LICENSE.txt": """HIDAPI can be used under one of three licenses.

1. The GNU General Public License, version 3.0, in LICENSE-gpl3.txt
2. A BSD-Style License, in LICENSE-bsd.txt.
3. The more liberal original HIDAPI license. LICENSE-orig.txt

The license chosen is at the discretion of the user of HIDAPI. For example:
1. An author of GPL software would likely use HIDAPI under the terms of the
GPL.

2. An author of commercial closed-source software would likely use HIDAPI
under the terms of the BSD-style license or the original HIDAPI license.
""",
    "LICENSE-bsd.txt": """Copyright (c) 2010, Alan Ott, Signal 11 Software
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
      this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Signal 11 Software nor the names of its
      contributors may be used to endorse or promote products derived from
      this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
""",
    "LICENSE-orig.txt": """HIDAPI - Multi-Platform library for
communication with HID devices.

Copyright 2009, Alan Ott, Signal 11 Software.
All Rights Reserved.

This software may be used by anyone for any reason so
long as the copyright notice in the source files
remains intact.
""",
}

SQLITE_PUBLIC_DOMAIN_NOTICE = """SQLite core is dedicated to the public domain by its authors and does not
require a license. The bundled engine version is reported above. The SQLite
project's copyright page describes this status at:
https://www.sqlite.org/copyright.html
"""

PROTOCOL_REFERENCES = """These repositories were consulted as protocol references only. Their source
code and binaries are not included in this executable.

- G-Helper Chakram X implementation at commit
  a3c3ccae51f005d92d8d4ee161e6661ab511274d:
  https://github.com/seerge/g-helper/tree/a3c3ccae51f005d92d8d4ee161e6661ab511274d
- libratbag ASUS implementation at commit
  1aec93b2f81036014063fb8a9ac194a1c71bdec8:
  https://github.com/libratbag/libratbag/tree/1aec93b2f81036014063fb8a9ac194a1c71bdec8
- ASUS Armoury Mouse SDK and P708 HAL were inspected locally as protocol
  references only. No ASUS DLL or Armoury Crate file is bundled.
"""


class NoticeError(RuntimeError):
    """The release environment does not contain verified license material."""


def normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def load_distribution(name: str, expected_version: str):
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NoticeError(f"Required build distribution is missing: {name}.") from exc
    if distribution.version != expected_version:
        raise NoticeError(
            f"Expected {name}=={expected_version}, found {distribution.version}. "
            "Review and update the pinned license inputs before packaging."
        )
    return distribution


def license_files(distribution, required_names: set[str]) -> list[tuple[str, str]]:
    declared = distribution.metadata.get_all("License-File") or []
    if not declared:
        raise NoticeError(f"{distribution.metadata['Name']} has no License-File metadata.")

    files = list(distribution.files or [])
    selected: list[tuple[str, str]] = []
    for required_name in sorted(required_names):
        matches = [
            file for file in files
            if PurePosixPath(str(file)).name.casefold() == required_name.casefold()
            and "licenses" in {part.casefold() for part in PurePosixPath(str(file)).parts}
        ]
        if required_name.casefold() not in {
            PurePosixPath(name).name.casefold() for name in declared
        }:
            raise NoticeError(
                f"{distribution.metadata['Name']} does not declare {required_name} as a license file."
            )
        if len(matches) != 1:
            raise NoticeError(
                f"Expected one installed copy of {required_name} for "
                f"{distribution.metadata['Name']}, found {len(matches)}."
            )
        path = Path(distribution.locate_file(matches[0]))
        if not path.is_file():
            raise NoticeError(f"Declared license file is missing: {path.name}.")
        selected.append((f"{distribution.metadata['Name']} {distribution.version} / {required_name}",
                         path.read_text(encoding="utf-8", errors="strict")))
    return selected


def extract_pysqlite_license(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    start = source.find("# Copyright (C) ")
    end_marker = "# 3. This notice may not be removed or altered from any source distribution."
    end = source.find(end_marker, start)
    if start < 0 or end < 0:
        raise NoticeError(f"Could not locate the pysqlite license in {path.name}.")
    end += len(end_marker)
    return "\n".join(line[2:] if line.startswith("# ") else line for line in source[start:end].splitlines())


def add_license(sections: list[str], seen: dict[str, str], title: str, source: str,
                text: str) -> None:
    content = normalized_text(text)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if digest in seen:
        sections.append(
            f"### {title}\n\n"
            f"The complete text is identical to **{seen[digest]}** and is reproduced there.\n\n"
            f"Source: `{source}`. SHA-256: `{digest}`."
        )
        return
    seen[digest] = title
    sections.append(
        f"### {title}\n\nSource: `{source}`. SHA-256: `{digest}`.\n\n"
        f"```text\n{content}```"
    )


def build_notice() -> str:
    if sys.platform != "win32":
        raise NoticeError("Run this collector with the Windows release interpreter.")
    if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 13):
        raise NoticeError("The release environment must use Windows CPython 3.13.x.")

    pyinstaller = load_distribution("pyinstaller", EXPECTED_DISTRIBUTIONS["pyinstaller"])
    hidapi = load_distribution("hidapi", EXPECTED_DISTRIBUTIONS["hidapi"])
    pyinstaller_licenses = license_files(pyinstaller, {"COPYING.txt"})
    hidapi_licenses = license_files(
        hidapi,
        {"LICENSE.txt", "LICENSE-bsd.txt", "LICENSE-gpl3.txt", "LICENSE-orig.txt"},
    )

    base = Path(sys.base_prefix)
    python_license = base / "LICENSE.txt"
    if not python_license.is_file():
        raise NoticeError("The CPython base installation does not contain LICENSE.txt.")
    python_text = python_license.read_text(encoding="utf-8", errors="strict")
    if not python_text.strip():
        raise NoticeError("The CPython base installation's LICENSE.txt is empty.")

    try:
        import _tkinter
        import sqlite3
        import ssl
        import zlib
    except ImportError as exc:
        raise NoticeError(f"A packaged Windows runtime component is unavailable: {exc}.") from exc

    zlib_version = zlib.ZLIB_RUNTIME_VERSION
    if zlib_version != ZLIB_LICENSE_VERSION:
        raise NoticeError(
            f"The bundled zlib runtime is {zlib_version}, but the verified license text is for "
            f"{ZLIB_LICENSE_VERSION}. Refresh the zlib notice before packaging."
        )

    sqlite_source = base / "Lib" / "sqlite3"
    pysqlite_licenses = []
    for filename in ("__init__.py", "dbapi2.py"):
        path = sqlite_source / filename
        if not path.is_file():
            raise NoticeError(f"The CPython sqlite3 source file is missing: {filename}.")
        pysqlite_licenses.append((filename, extract_pysqlite_license(path)))

    tcl_license = base / "tcl" / "tk8.6" / "license.terms"
    if not tcl_license.is_file():
        raise NoticeError("The Windows CPython Tcl/Tk license.terms file is missing.")

    sections: list[str] = []
    sections.append(
        "# Third-Party Notices\n\n"
        "This file is generated from the Windows release build environment. It records "
        "third-party license texts and does not select a license for the application.\n\n"
        "## Build and runtime components\n\n"
        f"- CPython {platform.python_version()} ({platform.python_implementation()}); "
        "base-distribution license file included below.\n"
        f"- PyInstaller {pyinstaller.version}; its one-file bootloader is covered by the "
        "included PyInstaller copying file.\n"
        f"- hidapi {hidapi.version}; the installed distribution metadata supplies multiple "
        "license alternatives, all included below.\n"
        f"- Tcl/Tk {_tkinter.TCL_VERSION}/{_tkinter.TK_VERSION}; "
        f"SQLite {sqlite3.sqlite_version}; zlib {zlib_version}; {ssl.OPENSSL_VERSION}.\n"
    )

    sections.append(
        "## CPython and bundled Windows runtime notices\n\n"
        "The complete CPython base-distribution LICENSE.txt follows. It contains the "
        "Python Software Foundation terms and notices for Microsoft Distributable Code, "
        "bzip2, libffi, Apache License 2.0, Tcl, and Tk.\n"
    )
    seen: dict[str, str] = {}
    add_license(sections, seen, "CPython 3.13 base distribution", "CPython LICENSE.txt", python_text)
    add_license(sections, seen, "Tcl/Tk license terms", "tcl/tk8.6/license.terms",
                tcl_license.read_text(encoding="utf-8", errors="strict"))

    sections.append(
        "## SQLite\n\n"
        f"The bundled SQLite engine reports version {sqlite3.sqlite_version}. SQLite's core "
        "code is dedicated to the public domain and does not require a license. The upstream "
        "copyright page records this status: https://www.sqlite.org/copyright.html\n\n"
        "The Python sqlite3 adapter also carries the following pysqlite license notices.\n"
    )
    for filename, text in pysqlite_licenses:
        add_license(sections, seen, f"pysqlite adapter notice from {filename}",
                    f"Lib/sqlite3/{filename}", text)

    add_license(sections, seen, "zlib 1.3.1", "zlib 1.3.1 zlib.h license block", ZLIB_LICENSE)

    sections.append("## PyInstaller\n\nThe installed PyInstaller distribution includes the bootloader exception and runtime-hook notices in COPYING.txt.\n")
    for title, text in pyinstaller_licenses:
        add_license(sections, seen, title, "PyInstaller distribution license file", text)

    sections.append(
        "## hidapi Python binding\n\n"
        "The installed wheel does not declare one selected license expression. Its LICENSE.txt "
        "says the binding may be used under the GPLv3, BSD-style, or original license at the "
        "user's discretion. All installed alternatives are reproduced below without choosing "
        "one for this application.\n"
    )
    for title, text in hidapi_licenses:
        add_license(sections, seen, title, "hidapi 0.15.0 dist-info/licenses", text)

    sections.append(
        "## HIDAPI C library\n\n"
        "The hidapi 0.15.0 wheel metadata does not record the HIDAPI submodule commit. "
        "The official cython-hidapi 0.15.0 source tag pins that submodule to "
        f"`{HIDAPI_SUBMODULE_COMMIT}`. This notice uses that pinned upstream source for the "
        "native HIDAPI license alternatives. The wheel metadata lists only the Cython binding "
        "license files. The upstream offers the same three alternatives. The GPLv3 text was "
        "checked against the installed hidapi wheel and is reproduced in the binding section "
        "above.\n\n"
        f"Source tag: https://github.com/trezor/cython-hidapi/tree/0.15.0\n"
        f"Pinned submodule: https://github.com/libusb/hidapi/tree/{HIDAPI_SUBMODULE_COMMIT}\n"
    )
    for filename, text in HIDAPI_CORE_LICENSES.items():
        add_license(sections, seen, f"HIDAPI core {filename}",
                    f"libusb/hidapi {HIDAPI_SUBMODULE_COMMIT}/{filename}", text)
    installed_gpl = next(text for title, text in hidapi_licenses if title.endswith("LICENSE-gpl3.txt"))
    gpl_digest = hashlib.sha256(normalized_text(installed_gpl).encode("utf-8")).hexdigest()
    if gpl_digest != HIDAPI_GPL3_SHA256:
        raise NoticeError(
            "The installed hidapi GPLv3 text no longer matches the pinned HIDAPI submodule. "
            "Refresh the upstream license source before packaging."
        )
    add_license(sections, seen, "HIDAPI core LICENSE-gpl3.txt",
                f"libusb/hidapi {HIDAPI_SUBMODULE_COMMIT}/LICENSE-gpl3.txt", installed_gpl)

    sections.append(PROTOCOL_REFERENCES)
    return "\n\n".join(sections).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="THIRD_PARTY_NOTICES.md",
        help="output path; use '-' to write the notice to standard output",
    )
    arguments = parser.parse_args()

    try:
        notice = build_notice()
    except NoticeError as exc:
        print(f"License collection failed: {exc}", file=sys.stderr)
        return 1

    if arguments.output == "-":
        sys.stdout.write(notice)
    else:
        output = Path(arguments.output)
        if not output.is_absolute():
            output = Path(__file__).resolve().parent.parent / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(notice, encoding="utf-8", newline="\n")
        print(f"Wrote {output} ({len(notice.encode('utf-8'))} bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
