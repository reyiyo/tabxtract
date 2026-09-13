# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Entry point of the frozen binary.

PyInstaller runs the entry script as a bare `__main__`, with no parent
package, so freezing `server/__main__.py` directly breaks its relative
imports. This wrapper imports the package first, which is what gives them
context.
"""
from server.__main__ import main

if __name__ == "__main__":
    main()
