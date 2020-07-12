# -*- coding: utf8 -*-

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

"""Reduce images based on precalculated scale values."""

from __future__ import with_statement, unicode_literals

import config
import logging
import os
import shutil
import subprocess

from src.images.embed import image_is_embeddable

logger = logging.getLogger('images.scale')


def run(verbose):
    """Reduce images using precalculated scales."""
    notfound = 0
    done_now = {}
    embed_enabled = config.EMBED_IMAGES

    # load already processed images
    done_before = {}
    if os.path.exists(config.LOG_REDUCDONE):
        with open(config.LOG_REDUCDONE, "rt", encoding="utf-8") as fh:
            for line in fh:
                parts = line.strip().split()
                scale = int(parts[0])
                dskurl = parts[1]
                done_before[dskurl] = scale

    # load paths of embeddable images selected previously
    images_embed = set()
    if embed_enabled and os.path.exists(config.LOG_IMAGES_EMBEDDED):
        with open(config.LOG_IMAGES_EMBEDDED, 'rt', encoding='utf-8') as fh:
            images_embed = set(line.strip() for line in fh)

    src = os.path.join(config.DIR_TEMP, "images")
    dst = os.path.join(config.DIR_IMGSLISTAS)

    # load image path and its correspondig scale
    with open(config.LOG_REDUCCION, "rt", encoding="utf-8") as fh:
        for line in fh:
            parts = line.strip().split(config.SEPARADOR_COLUMNAS)
            scale = int(parts[0])
            dskurl = parts[1]

            frompath = os.path.join(src, dskurl)
            topath = os.path.join(dst, dskurl)
            if not os.path.exists(frompath):
                logger.warning("Don't have the img %r", frompath)
                notfound += 1
                continue

            # create the dir to hold it
            dirname = os.path.dirname(topath)
            if not os.path.exists(dirname):
                os.makedirs(dirname)

            # rules to skip scaling of some images: math/*, .png, and < 2KB
            imgsize = os.stat(frompath).st_size
            if dskurl.startswith('math') or dskurl.endswith('.png') or imgsize < 2048:
                scale = 100

            # check if image scaling was already done
            scaled_before = done_before.get(dskurl)
            if scaled_before == scale:
                done_now[dskurl] = scale
                continue

            # change size only if needed, otherwise just make a copy
            if verbose:
                logger.debug("Rescaling to %d%% image %s", scale, dskurl)
            if scale == 100:
                done_now[dskurl] = 100
                if embed_enabled and image_is_embeddable(dskurl, imgsize):
                    # don't copy image, leave it out of image blocks, it will
                    # be embedded from original location (without any reduction)
                    images_embed.add(dskurl)
                else:
                    shutil.copyfile(frompath, topath)

            else:
                cmd = ['convert', frompath, '-resize', '%d%%' % (scale,), topath]
                errorcode = subprocess.call(cmd)
                if not errorcode:
                    done_now[dskurl] = scale
                else:
                    logger.warning("Got %d when processing %s", errorcode, frompath)

    # save images processed now
    with open(config.LOG_REDUCDONE, "wt", encoding="utf-8") as fh:
        for dskurl, scale in done_now.items():
            fh.write("%3d %s\n" % (scale, dskurl))

    # save paths of selected images to be embedded
    with open(config.LOG_IMAGES_EMBEDDED, 'wt', encoding='utf-8') as fh:
        for dskurl in images_embed:
            fh.write(dskurl + '\n')

    # delete extra images from previous processing
    for dskurl in (set(done_before) - set(done_now)):
        fullpath = os.path.join(dst, dskurl)
        try:
            os.remove(fullpath)
        except OSError as exc:
            logger.error("When erasing %r (got OSError %s)", fullpath, exc)

    # if verbose warn not found images
    if not verbose and notfound:
        logger.warning("%d images not found!", notfound)
    return notfound
