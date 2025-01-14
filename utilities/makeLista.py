# -*- coding: utf-8 -*-

# Copyright 2009-2020 CDPedistas (see AUTHORS.txt)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3, as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For further info, check  https://github.com/PyAr/CDPedia/

from __future__ import print_function

import os
import sys

usage = """
Use: makeLista.py <directory>

    directory where the wikipedia is decompressed

    example: "makeLista.py wikipedia-es-html.7z"

    The program shows the list and percentages using stdout
"""

PASOSHOW = 1000


def main(nomdir):
    total = tamtotal = 0
    acum = {}
    pasoant = 0

    print("Analyzing %r..." % nomdir)
    for cwd, directorios, archivos in os.walk(nomdir):
        for fname in archivos:
            fullpath = os.path.join(cwd, fname)

            tamanio = os.stat(fullpath).st_size
            tamtotal += tamanio

            if "~" in fname:
                raiz = fname.split("~")[0].decode("utf-8")
            else:
                raiz = "None"

            (cant, tam) = acum.get(raiz, (0, 0))
            cant += 1
            tam += tamanio
            acum[raiz] = (cant, tam)
            total += 1

            if total // PASOSHOW > pasoant:
                sys.stdout.write("\r%d...     " % total)
                sys.stdout.flush()
                pasoant = total // PASOSHOW

    print("\nShowing the results for a total of %d files that occupy %.2f MB:\n" % (
        total, tamtotal / 1048576.0))
    maslargo = max([len(x) for x in acum.keys()])
    print("  %s    Cant      Cant%%  Size   Size%%" % "Root".ljust(maslargo))
    for (raiz, (cant, tam)) in sorted(acum.items(), key=lambda x: x[1][1], reverse=True):
        tammb = tam / 1048576.0
        if tammb < 1:
            break
        print("  %s  %7d  %8.2f%%  %3d MB  %7.2f%%" % (
            raiz.ljust(maslargo), cant, 100 * cant / float(total),
            tammb, 100 * tam / float(tamtotal)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(usage)
        sys.exit(1)

    main(sys.argv[1])
