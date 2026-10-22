"""Convert Revenant I2D imagery resources into PNG or GIF images.

I2D is the 2D imagery format of the 1998 game Revenant (Cinematix Studios).  It is a
"CGS" resource file, so the layout is::

    [FileResHdr : 20 bytes][header : hdrsize bytes][bitmap table : 4 * topbm][data]

``header`` holds a ``SImageryHeader``::

    int32  imageryid            // 0 = OBJIMAGE_ANIMATION, the only id used by I2D files
    int32  numstates
    SImageryStateHeader states[numstates]    // 76 bytes each

and ``data`` holds the imagery body.  For animation imagery the body starts with one
``SAnimImageryState`` per state (five 32-bit fields)::

    OFFSET still                // static image      -> TBitmap
    OFFSET anim                 // animation         -> TAnimationData
    OFFSET invitem              // inventory icon    -> TBitmap
    OFFSET invanim              // inventory anim    -> TAnimationData
    uint32 flags

followed by the bitmaps/animation records those offsets point at.  Every ``OFFSET`` is
a byte delta relative to the address of the offset field itself, all integers are
little endian.

A ``TBitmap`` (``TBitmapData``) is::

    int32 width, height, regx, regy
    uint32 flags, drawmode, keycolor
    uint32 aliassize;  OFFSET alias
    uint32 alphasize;  OFFSET alpha
    uint32 zbufsize;   OFFSET zbuffer
    uint32 normalsize; OFFSET normal
    uint32 palettesize; OFFSET palette     // SPalette: 256 x uint16 5:5:5 + 256 x RGB32
    uint32 datasize
    <pixel data>

Pixel data is stored as is, or with ``BM_CHUNKED`` as a ``SChunkHeader`` grid of 64x64
blocks which are individually RLE/LZ compressed (8 bit) or stored verbatim (15/16 bit),
or with ``BM_COMPRESSED`` as a whole-image RLE/LZ stream (see ``_decompress_image``).
A ``TAnimationData`` is::

    int32 flags, maxwidth, maxheight, numframes
    uint32 drawmode
    SAnimationFrame frames[numframes]      // 40 bytes each, bitmap is the last field

Output rules: an image with a single frame is written as PNG, an animation with more
than one frame as an animated GIF (frames are aligned by their registration points,
the per-frame motion deltas are not applied).  A file that yields a single image is
written as ``<name>.png``/``<name>.gif``; otherwise the file name is suffixed with the
image kind (``still``/``anim``/``inv``/``invanim``) and, for imagery with several
states, with the state number - ``<name>_s02_anim.gif``.

Walkmaps, z-buffers, normal and alias buffers are metadata for the game engine and are
not exported, but the z-buffer is used as the transparency mask for level geometry
(tiles and props store their silhouette there, while the colour plane below may hold
real black pixels), and palette/key colour transparency ends up in the alpha channel.

Usage::

    python i2d_to_image.py AoRogoss.I2D
    python i2d_to_image.py "C:/Games/Revenant/unpack-imagery/Imagery" -r -o images
    python i2d_to_image.py --info AoRogoss.I2D
"""

from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import click
from PIL import Image

# --------------------------------------------------------------------------- #
# Format constants
# --------------------------------------------------------------------------- #

RES_MAGIC = b'CGSR'
RES_VERSION = 1
RES_HEADER_SIZE = 20

IMAGERY_ANIMATION = 0

STATE_HEADER_SIZE = 76          # SImageryStateHeader
ANIM_STATE_SIZE = 20            # SAnimImageryState
ANIM_HEADER_SIZE = 20           # TAnimationData without the frames array
ANIM_FRAME_SIZE = 40            # SAnimationFrame
ANIM_FRAME_BITMAP_FIELD = 36    # offset of the bitmap OFFSET inside SAnimationFrame
BITMAP_HEADER_SIZE = 72         # TBitmapData, pixel data follows

CHUNK_WIDTH = 64
CHUNK_HEIGHT = 64
CHUNK_PIXELS = CHUNK_WIDTH * CHUNK_HEIGHT

MAX_BITMAP_SIZE = 8192
MAX_ANIMATION_FRAMES = 4096
MAX_CHUNK_BLOCKS = 1 << 16

# GIF has no alpha channel: pixels below the threshold become the transparent
# palette entry, the rest becomes opaque
GIF_TRANSPARENT_INDEX = 255
GIF_ALPHA_THRESHOLD = 128

# Bitmap flags (revdefs.h)
BM_8BIT = 0x0001
BM_15BIT = 0x0002
BM_16BIT = 0x0004
BM_24BIT = 0x0008
BM_32BIT = 0x0010
BM_ZBUFFER = 0x0020
BM_NORMALS = 0x0040
BM_ALIAS = 0x0080
BM_ALPHA = 0x0100
BM_PALETTE = 0x0200
BM_REGPOINT = 0x0400
BM_NOBITMAP = 0x0800
BM_5BITPAL = 0x1000
BM_COMPRESSED = 0x4000
BM_CHUNKED = 0x8000
BM_ARGB4444 = 0x10000
BM_ARGB1555 = 0x20000

BM_ANY_16BIT = BM_15BIT | BM_16BIT | BM_ARGB4444 | BM_ARGB1555

_FILE_RES_HEADER = struct.Struct('<IHBBIII')
_IMAGERY_HEADER = struct.Struct('<ii')
_STATE_HEADER = struct.Struct('<32sII' + 'h' * 18)
_ANIM_STATE = struct.Struct('<IIIII')
_ANIM_HEADER = struct.Struct('<iiiiI')
_ANIM_FRAME = struct.Struct('<iiiiiiiiII')
_BITMAP_HEADER = struct.Struct('<iiiiIIIIIIIIIII')
_BITMAP_PALETTE = struct.Struct('<III')
_CHUNK_HEADER = struct.Struct('<B3xii')

# Image kinds a single imagery state can hold
KIND_STILL = 'still'
KIND_ANIMATION = 'anim'
KIND_INVENTORY = 'inv'
KIND_INVENTORY_ANIMATION = 'invanim'
KIND_BITMAP = 'bitmap'


class I2DError(Exception):
    """Raised when an I2D file is malformed or uses an unsupported feature."""


# --------------------------------------------------------------------------- #
# Low level helpers
# --------------------------------------------------------------------------- #

def _need(buffer: bytes, offset: int, size: int, what: str) -> None:
    """Verify that ``size`` bytes at ``offset`` are inside ``buffer``."""
    if offset < 0 or size < 0 or offset + size > len(buffer):
        msg = (
            f'{what}: read outside of the buffer '
            f'(offset {offset}, size {size}, buffer {len(buffer)} bytes)'
        )
        raise I2DError(msg)


def _u32(buffer: bytes, offset: int) -> int:
    _need(buffer, offset, 4, 'uint32')
    return struct.unpack_from('<I', buffer, offset)[0]


def _pointer(buffer: bytes, field_offset: int) -> int | None:
    """Resolve an OFFSET field: a byte delta relative to the field itself."""
    value = _u32(buffer, field_offset)
    return None if value == 0 else field_offset + value


def _expand5(value: int) -> int:
    """5-bit colour component to 8-bit."""
    return (value << 3) | (value >> 2)


def _expand6(value: int) -> int:
    """6-bit colour component to 8-bit."""
    return (value << 2) | (value >> 4)


def _expand4(value: int) -> int:
    """4-bit colour/alpha component to 8-bit."""
    return (value << 4) | value


# --------------------------------------------------------------------------- #
# Bitmap decoding
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Bitmap:
    """A decoded TBitmap with RGBA pixels ready to be saved."""

    width: int
    height: int
    regx: int
    regy: int
    flags: int
    rgba: bytes
    description: str

    def to_image(self) -> Image.Image:
        return Image.frombytes('RGBA', (self.width, self.height), self.rgba)


def _palette_lut(buffer: bytes, field_offset: int, palettesize: int) -> bytes:
    """Read a SPalette and return 256 RGB triples expanded from the 5:5:5 words."""
    if palettesize < 512 or _u32(buffer, field_offset) == 0:
        msg = 'bitmap uses palette indices but has no SPalette'
        raise I2DError(msg)

    pointer = field_offset + _u32(buffer, field_offset)
    _need(buffer, pointer, 512, 'SPalette')

    lut = bytearray(256 * 3)
    for index, word in enumerate(struct.unpack_from('<256H', buffer, pointer)):
        red = (word >> 10) & 0x1F
        green = (word >> 5) & 0x1F
        blue = word & 0x1F
        base = index * 3
        lut[base] = _expand5(red)
        lut[base + 1] = _expand5(green)
        lut[base + 2] = _expand5(blue)
    return bytes(lut)


def _alpha_plane(
    buffer: bytes,
    field_offset: int,
    flags: int,
    width: int,
    height: int,
) -> bytes | None:
    """Read the optional 5-bit per pixel alpha buffer."""
    if not flags & BM_ALPHA:
        return None

    alphasize, alpha = struct.unpack_from('<II', buffer, field_offset + 36)
    if alpha == 0 or alphasize == 0:
        return None

    pointer = field_offset + 40 + alpha
    size = width * height
    _need(buffer, pointer, size, 'bitmap alpha buffer')
    return buffer[pointer:pointer + size]


def _decompress_chunk(buffer: bytes, pointer: int) -> bytes:
    """Decompress one 64x64 8-bit chunk (TChunkCache::ChunkDecompress).

    The chunk starts with a 4 byte id followed by the RLE/LZ escape bytes and a byte
    stream that covers CHUNK_HEIGHT rows: an escape introduces a run, a skip or a
    row end, the LZ opcode copies bytes from earlier in the *source* stream.
    """
    _need(buffer, pointer, 6, 'bitmap chunk')
    chunk_id, dle_rle, dle_lz = struct.unpack_from('<IBB', buffer, pointer)
    del chunk_id  # only a cache key for the original engine

    out = bytearray(CHUNK_PIXELS)
    pos = pointer + 6
    written = 0
    row = CHUNK_HEIGHT

    while row > 0:
        if pos >= len(buffer):
            msg = 'compressed bitmap chunk is truncated'
            raise I2DError(msg)

        opcode = buffer[pos]
        pos += 1

        if opcode == dle_rle:
            if pos >= len(buffer):
                msg = 'compressed bitmap chunk is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            pos += 1

            if count == 0:                      # end of row
                row -= 1
            elif count >= 0x80:                 # skip pixels
                written += count & 0x7F
            else:                               # fill with the next byte
                if pos >= len(buffer):
                    msg = 'compressed bitmap chunk is truncated'
                    raise I2DError(msg)
                value = buffer[pos]
                pos += 1
                length = min(count, CHUNK_PIXELS - written)
                if length > 0:
                    out[written:written + length] = bytes((value,)) * length
                    written += length

        elif opcode == dle_lz:
            if pos + 2 >= len(buffer):
                msg = 'compressed bitmap chunk is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            distance = struct.unpack_from('<H', buffer, pos + 1)[0]
            pos += 3
            back = pos - distance - 4
            if count and (back < 0 or back + count > len(buffer)):
                msg = 'compressed bitmap chunk has a bad back reference'
                raise I2DError(msg)
            length = min(count, CHUNK_PIXELS - written)
            if length > 0:
                out[written:written + length] = buffer[back:back + length]
                written += length

        else:                                   # raw pixel
            if written < CHUNK_PIXELS:
                out[written] = opcode
            written += 1

    return bytes(out)


def _decompress_image(
    buffer: bytes,
    pointer: int,
    size: int,
    width: int,
    height: int,
) -> bytes:
    """Decompress a whole ``BM_COMPRESSED`` 8-bit bitmap into palette indices.

    The payload starts with the two escape bytes (RLE and LZ) followed by one
    opcode stream per scanline::

        <rle> 0            end of scanline, the rest of the line is transparent
        <rle> count>=0x80  skip (count & 0x7f) pixels
        <rle> count<0x80   fill count pixels with the next byte
        <lz>  count, dist  copy count pixels from earlier in the stream
        other              literal pixel
    """
    _need(buffer, pointer, size, 'compressed bitmap data')
    if size < 2:
        msg = 'compressed bitmap data is truncated'
        raise I2DError(msg)

    dle_rle = buffer[pointer]
    dle_lz = buffer[pointer + 1]
    end = pointer + size
    pos = pointer + 2

    plane = bytearray(width * height)
    row = 0
    column = 0

    while pos < end and row < height:
        opcode = buffer[pos]
        pos += 1

        if opcode == dle_rle:
            if pos >= end:
                msg = 'compressed bitmap data is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            pos += 1

            if count == 0:                      # end of scanline
                row += 1
                column = 0
            elif count >= 0x80:                 # skip pixels
                column += count & 0x7F
            else:                               # fill with the next byte
                if pos >= end:
                    msg = 'compressed bitmap data is truncated'
                    raise I2DError(msg)
                value = buffer[pos]
                pos += 1
                for _ in range(count):
                    if column < width:
                        plane[row * width + column] = value
                    column += 1

        elif opcode == dle_lz:
            if pos + 2 >= end:
                msg = 'compressed bitmap data is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            distance = struct.unpack_from('<H', buffer, pos + 1)[0]
            pos += 3
            back = pos - distance - 4
            if count and (back < 0 or back + count > len(buffer)):
                msg = 'compressed bitmap data has a bad back reference'
                raise I2DError(msg)
            for _ in range(count):
                if column < width:
                    plane[row * width + column] = buffer[back]
                back += 1
                column += 1

        else:                                   # literal pixel
            if column < width:
                plane[row * width + column] = opcode
            column += 1

    return bytes(plane)


def _decompress_z_chunk(buffer: bytes, pointer: int) -> bytes:
    """Decompress one 64x64 16-bit z-buffer chunk (TChunkCache::ChunkDecompressZ).

    The stream is the same RLE/LZ encoding as the colour chunks, but every write
    produces a 16-bit depth value: a literal or a run byte only supplies the low
    half, the high half comes from the ``highbyte`` state, which an LZ opcode with
    count 0 sets (``<lz> 00 7f`` makes every following pixel 0x7fXX).
    """
    _need(buffer, pointer, 6, 'z-buffer chunk')
    _chunk_id, dle_rle, dle_lz = struct.unpack_from('<IBB', buffer, pointer)

    out = bytearray(b'\x7f\x7f' * CHUNK_PIXELS)
    pos = pointer + 6
    written = 0
    highbyte = 0
    row = CHUNK_HEIGHT
    end = len(buffer)

    while row > 0:
        if pos >= end:
            msg = 'z-buffer chunk is truncated'
            raise I2DError(msg)

        opcode = buffer[pos]
        pos += 1

        if opcode == dle_rle:
            if pos >= end:
                msg = 'z-buffer chunk is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            pos += 1

            if count == 0:                      # end of row
                row -= 1
            elif count >= 0x80:                 # skip pixels
                written += count & 0x7F
            else:                               # fill with the next value
                if pos >= end:
                    msg = 'z-buffer chunk is truncated'
                    raise I2DError(msg)
                value = buffer[pos]
                pos += 1
                length = min(count, CHUNK_PIXELS - written)
                if length > 0:
                    pair = bytes((value, highbyte))
                    out[written * 2:(written + length) * 2] = pair * length
                    written += length

        elif opcode == dle_lz:
            if pos >= end:
                msg = 'z-buffer chunk is truncated'
                raise I2DError(msg)
            count = buffer[pos]
            pos += 1

            if count == 0:                      # set the high byte state
                if pos >= end:
                    msg = 'z-buffer chunk is truncated'
                    raise I2DError(msg)
                highbyte = buffer[pos]
                pos += 1
                continue

            if pos + 2 > end:
                msg = 'z-buffer chunk is truncated'
                raise I2DError(msg)
            distance = struct.unpack_from('<H', buffer, pos)[0]
            pos += 2
            back = pos - distance - 4
            if back < 0 or back + count > end:
                msg = 'z-buffer chunk has a bad back reference'
                raise I2DError(msg)

            length = min(count, CHUNK_PIXELS - written)
            for index in range(length):
                out[(written + index) * 2] = buffer[back + index]
                out[(written + index) * 2 + 1] = highbyte
            written += length

        else:                                   # literal pixel
            if written < CHUNK_PIXELS:
                out[written * 2] = opcode
                out[written * 2 + 1] = highbyte
            written += 1

    return bytes(out)


def _blit_block(
    plane: bytearray,
    block: bytes,
    width: int,
    height: int,
    left: int,
    top: int,
    bytes_per_pixel: int,
) -> None:
    """Copy one decompressed 64x64 block into the image plane."""
    rows = min(CHUNK_HEIGHT, height - top)
    columns = min(CHUNK_WIDTH, width - left)
    if rows <= 0 or columns <= 0:
        return

    source_pitch = CHUNK_WIDTH * bytes_per_pixel
    target_pitch = width * bytes_per_pixel
    length = columns * bytes_per_pixel

    for row in range(rows):
        source = row * source_pitch
        target = (top + row) * target_pitch + left * bytes_per_pixel
        plane[target:target + length] = block[source:source + length]


def _read_z_plane(
    buffer: bytes,
    field_offset: int,
    width: int,
    height: int,
    flags: int,
) -> bytes | None:
    """Decode the depth plane of a z-buffered bitmap as w*h 16-bit words.

    Level geometry keeps its cut-outs in this plane, so it doubles as the
    transparency mask: 0 and 0x7f7f mean "no geometry here" (see the tile
    uploader in the engine port, ``UploadTileBitmap``).
    """
    zbuffersize, zbuffer = struct.unpack_from('<II', buffer, field_offset + 44)
    if zbuffersize == 0 or zbuffer == 0:
        return None

    pointer = field_offset + 48 + zbuffer

    if flags & BM_CHUNKED:
        _need(buffer, pointer, _CHUNK_HEADER.size, 'z-buffer SChunkHeader')
        _, grid_width, grid_height = _CHUNK_HEADER.unpack_from(buffer, pointer)
        if not 0 < grid_width <= MAX_BITMAP_SIZE or not 0 < grid_height <= MAX_BITMAP_SIZE:
            return None
        table = pointer + _CHUNK_HEADER.size
        _need(buffer, table, 4 * grid_width * grid_height, 'z-buffer block table')

        plane = bytearray(b'\x7f\x7f' * (width * height))
        for block_y in range(grid_height):
            for block_x in range(grid_width):
                entry = table + 4 * (block_y * grid_width + block_x)
                offset = _u32(buffer, entry)
                if offset == 0:                 # no geometry in this block
                    continue
                block = _decompress_z_chunk(buffer, entry + offset)
                _blit_block(
                    plane,
                    block,
                    width,
                    height,
                    block_x * CHUNK_WIDTH,
                    block_y * CHUNK_HEIGHT,
                    2,
                )
        return bytes(plane)

    size = width * height * 2
    if zbuffersize < size:
        return None
    _need(buffer, pointer, size, 'z-buffer')
    return buffer[pointer:pointer + size]


def _coverage_from_z(plane: bytes, width: int, height: int) -> bytes:
    """Turn a depth plane into a 5-bit coverage plane: 31 where geometry exists."""
    count = width * height
    words = struct.unpack_from(f'<{count}H', plane)
    coverage = bytearray(count)
    for index, word in enumerate(words):
        if word != 0 and word != 0x7F7F:
            coverage[index] = 31
    return bytes(coverage)


def _read_chunked_plane(
    buffer: bytes,
    base: int,
    width: int,
    height: int,
    flags: int,
) -> bytes:
    """Assemble the pixel plane of a BM_CHUNKED bitmap."""
    _need(buffer, base, _CHUNK_HEADER.size, 'SChunkHeader')
    _chunk_type, grid_width, grid_height = _CHUNK_HEADER.unpack_from(buffer, base)
    if grid_width <= 0 or grid_height <= 0 or grid_width * grid_height > MAX_CHUNK_BLOCKS:
        msg = f'SChunkHeader: bad block grid {grid_width}x{grid_height}'
        raise I2DError(msg)

    table = base + _CHUNK_HEADER.size
    _need(buffer, table, 4 * grid_width * grid_height, 'SChunkHeader block table')

    eight_bit = bool(flags & BM_8BIT)
    bytes_per_pixel = 1 if eight_bit else 2
    plane = bytearray(width * height * bytes_per_pixel)

    for block_y in range(grid_height):
        for block_x in range(grid_width):
            entry = table + 4 * (block_y * grid_width + block_x)
            offset = _u32(buffer, entry)
            if offset == 0:                     # blank block, stays transparent
                continue

            chunk = entry + offset
            if eight_bit and flags & BM_COMPRESSED:
                block = _decompress_chunk(buffer, chunk)
            elif eight_bit:
                size = CHUNK_PIXELS
                _need(buffer, chunk, 4 + size, 'bitmap chunk')
                block = buffer[chunk + 4:chunk + 4 + size]
            else:
                size = CHUNK_PIXELS * 2
                _need(buffer, chunk, 4 + size, 'bitmap chunk')
                block = buffer[chunk + 4:chunk + 4 + size]

            _blit_block(
                plane,
                block,
                width,
                height,
                block_x * CHUNK_WIDTH,
                block_y * CHUNK_HEIGHT,
                bytes_per_pixel,
            )

    return bytes(plane)


def _read_plane(
    buffer: bytes,
    field_offset: int,
    width: int,
    height: int,
    flags: int,
    datasize: int,
) -> tuple[str, bytes]:
    """Return the raw pixel plane of a bitmap: ('idx8' | 'px16' | 'rgb24', bytes)."""
    if flags & BM_NOBITMAP:
        msg = 'bitmap has no pixel data (BM_NOBITMAP)'
        raise I2DError(msg)

    if flags & BM_CHUNKED:
        if flags & BM_8BIT:
            kind = 'idx8'
        elif flags & BM_ANY_16BIT:
            kind = 'px16'
        else:
            msg = f'chunked bitmap of unsupported format 0x{flags:08x}'
            raise I2DError(msg)
        plane = _read_chunked_plane(buffer, field_offset + BITMAP_HEADER_SIZE, width, height, flags)
        return kind, plane

    if flags & BM_COMPRESSED:
        if not flags & BM_8BIT:
            msg = f'compressed bitmap of unsupported format 0x{flags:08x}'
            raise I2DError(msg)
        plane = _decompress_image(
            buffer,
            field_offset + BITMAP_HEADER_SIZE,
            datasize,
            width,
            height,
        )
        return 'idx8', plane

    if flags & BM_8BIT:
        kind, size = 'idx8', width * height
    elif flags & BM_ANY_16BIT:
        kind, size = 'px16', width * height * 2
    elif flags & BM_24BIT:
        kind, size = 'rgb24', width * height * 3
    elif flags & BM_32BIT:
        msg = '32 bit bitmaps are not supported'
        raise I2DError(msg)
    else:
        msg = f'unsupported bitmap flags 0x{flags:08x}'
        raise I2DError(msg)

    data = field_offset + BITMAP_HEADER_SIZE
    _need(buffer, data, size, 'bitmap pixels')
    return kind, buffer[data:data + size]


def _rgba_from_indices(
    indices: bytes,
    width: int,
    height: int,
    palette: bytes,
    alpha: bytes | None,
) -> bytes:
    """Expand palette indices into RGBA pixels.

    Without a coverage plane index 0 is the transparent colour (that is what the
    keyed blitter does); with one (alpha buffer or z-buffer silhouette) the
    coverage decides instead, so a black pixel may still be drawn.
    """
    if alpha is None:
        lookup = [bytes((0, 0, 0, 0))]
        for index in range(1, 256):
            base = index * 3
            lookup.append(bytes((palette[base], palette[base + 1], palette[base + 2], 255)))
        return b''.join([lookup[index] for index in indices])

    pixels = bytearray(width * height * 4)
    for index, value in enumerate(indices):
        level = alpha[index] & 0x1F
        if level == 0:
            continue
        target = index * 4
        source = value * 3
        pixels[target] = palette[source]
        pixels[target + 1] = palette[source + 1]
        pixels[target + 2] = palette[source + 2]
        pixels[target + 3] = _expand5(level)
    return bytes(pixels)


def _rgba_from_words(
    plane: bytes,
    width: int,
    height: int,
    flags: int,
    keycolor: int,
    alpha: bytes | None,
) -> bytes:
    """Expand 15/16 bit direct colour pixels into RGBA."""
    count = width * height
    words = struct.unpack_from(f'<{count}H', plane)

    argb4444 = bool(flags & BM_ARGB4444)
    argb1555 = bool(flags & BM_ARGB1555)
    high_bits = bool(flags & BM_16BIT)
    key = keycolor & 0xFFFF
    keyed = alpha is None

    pixels = bytearray(count * 4)
    target = 0

    for index, word in enumerate(words):
        opacity = 255

        if argb4444:
            alpha4 = (word >> 12) & 0x0F
            red = _expand4((word >> 8) & 0x0F)
            green = _expand4((word >> 4) & 0x0F)
            blue = _expand4(word & 0x0F)
            opacity = _expand4(alpha4)
        elif argb1555:
            red = _expand5((word >> 10) & 0x1F)
            green = _expand5((word >> 5) & 0x1F)
            blue = _expand5(word & 0x1F)
            opacity = 255 if word & 0x8000 else 0
        elif high_bits:
            red = _expand5((word >> 11) & 0x1F)
            green = _expand6((word >> 5) & 0x3F)
            blue = _expand5(word & 0x1F)
        else:
            red = _expand5((word >> 10) & 0x1F)
            green = _expand5((word >> 5) & 0x1F)
            blue = _expand5(word & 0x1F)

        if keyed:
            if word == key:
                target += 4
                continue
        else:
            level = alpha[index] & 0x1F
            if level == 0:
                target += 4
                continue
            opacity = _expand5(level)

        if opacity == 0:
            target += 4
            continue

        pixels[target] = red
        pixels[target + 1] = green
        pixels[target + 2] = blue
        pixels[target + 3] = opacity
        target += 4

    return bytes(pixels)


def _rgba_from_bgr(plane: bytes) -> bytes:
    """Expand 24 bit RGBTRIPLE (blue, green, red) pixels into RGBA."""
    pixels = bytearray(len(plane) // 3 * 4)
    for index in range(len(plane) // 3):
        source = index * 3
        target = index * 4
        pixels[target] = plane[source + 2]
        pixels[target + 1] = plane[source + 1]
        pixels[target + 2] = plane[source]
        pixels[target + 3] = 255
    return bytes(pixels)


def _describe(flags: int) -> str:
    if flags & BM_8BIT:
        return '8-bit palette'
    if flags & BM_ARGB4444:
        return '16-bit ARGB4444'
    if flags & BM_ARGB1555:
        return '16-bit ARGB1555'
    if flags & BM_16BIT:
        return '16-bit RGB565'
    if flags & BM_15BIT:
        return '15-bit RGB555'
    if flags & BM_24BIT:
        return '24-bit RGB'
    return f'flags 0x{flags:08x}'


def _recover_size(
    buffer: bytes,
    field_offset: int,
    flags: int,
    size_hint: tuple[int, int] | None,
) -> tuple[int, int, str]:
    """Recover a bitmap size that the original tool left uninitialised.

    ``Dungeon/duntoutcol.i2d`` was written with 0xAAAAAAAA instead of the real
    width/height.  The chunk grid still describes the block layout and the state
    header carries the intended size, so use the latter when it fits the grid.
    """
    if not flags & BM_CHUNKED:
        msg = f'TBitmap at {field_offset}: corrupt size, not a chunked bitmap'
        raise I2DError(msg)

    base = field_offset + BITMAP_HEADER_SIZE
    _need(buffer, base, _CHUNK_HEADER.size, 'SChunkHeader')
    _, grid_width, grid_height = _CHUNK_HEADER.unpack_from(buffer, base)
    if not 0 < grid_width <= MAX_BITMAP_SIZE or not 0 < grid_height <= MAX_BITMAP_SIZE:
        msg = f'TBitmap at {field_offset}: corrupt size and block grid'
        raise I2DError(msg)

    width = grid_width * CHUNK_WIDTH
    height = grid_height * CHUNK_HEIGHT

    if size_hint is not None:
        hint_width, hint_height = size_hint
        if 0 < hint_width <= width and 0 < hint_height <= height:
            width, height = hint_width, hint_height

    return width, height, ', size recovered'


def read_bitmap(
    buffer: bytes,
    field_offset: int,
    size_hint: tuple[int, int] | None = None,
) -> Bitmap:
    """Decode the TBitmap located at ``field_offset``."""
    _need(buffer, field_offset, BITMAP_HEADER_SIZE, 'TBitmap header')
    (
        width,
        height,
        regx,
        regy,
        flags,
        _drawmode,
        keycolor,
        _aliassize,
        _alias,
        _alphasize,
        _alpha,
        _zbuffersize,
        _zbuffer,
        _normalsize,
        _normal,
    ) = _BITMAP_HEADER.unpack_from(buffer, field_offset)
    palettesize, palette, datasize = _BITMAP_PALETTE.unpack_from(buffer, field_offset + 60)

    if not 0 < width <= MAX_BITMAP_SIZE or not 0 < height <= MAX_BITMAP_SIZE:
        width, height, note = _recover_size(buffer, field_offset, flags, size_hint)
    else:
        note = ''

    kind, plane = _read_plane(buffer, field_offset, width, height, flags, datasize)

    alpha = _alpha_plane(buffer, field_offset, flags, width, height)
    masked_by_z = False
    if alpha is None and flags & BM_ZBUFFER:
        # map tiles and level props carry their silhouette in the depth plane;
        # their colour plane is painted all over, often with real black pixels
        # under a valid depth, which the colour key alone would erase
        zplane = _read_z_plane(buffer, field_offset, width, height, flags)
        if zplane is not None:
            coverage = _coverage_from_z(zplane, width, height)
            if any(coverage):       # a fully empty depth plane carries no silhouette
                alpha = coverage
                masked_by_z = True

    if kind == 'idx8':
        rgbs = _palette_lut(buffer, field_offset + 64, palettesize)
        rgba = _rgba_from_indices(plane, width, height, rgbs, alpha)
    elif kind == 'px16':
        rgba = _rgba_from_words(plane, width, height, flags, keycolor, alpha)
    else:
        rgba = _rgba_from_bgr(plane)

    description = _describe(flags)
    if flags & BM_CHUNKED:
        description += ', chunked'
    elif flags & BM_COMPRESSED:
        description += ', compressed'
    if alpha is not None:
        description += ', z-buffer transparency' if masked_by_z else ', alpha'
    description += note

    return Bitmap(
        width=width,
        height=height,
        regx=regx,
        regy=regy,
        flags=flags,
        rgba=rgba,
        description=description,
    )


def read_animation(buffer: bytes, field_offset: int) -> list[Bitmap]:
    """Decode the TAnimationData referenced by the OFFSET field at ``field_offset``."""
    base = _pointer(buffer, field_offset)
    if base is None:
        return []

    _need(buffer, base, ANIM_HEADER_SIZE, 'TAnimationData')
    _flags, _maxwidth, _maxheight, numframes, _drawmode = _ANIM_HEADER.unpack_from(buffer, base)
    if not 0 <= numframes <= MAX_ANIMATION_FRAMES:
        msg = f'TAnimationData at {base}: bad frame count {numframes}'
        raise I2DError(msg)

    frames: list[Bitmap] = []
    for index in range(numframes):
        frame_offset = base + ANIM_HEADER_SIZE + index * ANIM_FRAME_SIZE
        _need(buffer, frame_offset, ANIM_FRAME_SIZE, 'SAnimationFrame')
        values = _ANIM_FRAME.unpack_from(buffer, frame_offset)
        bitmap_offset = values[-1]
        if bitmap_offset == 0:
            msg = f'SAnimationFrame {index} at {frame_offset}: no bitmap'
            raise I2DError(msg)
        frames.append(read_bitmap(buffer, frame_offset + ANIM_FRAME_BITMAP_FIELD + bitmap_offset))

    return frames


# --------------------------------------------------------------------------- #
# I2D file parsing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class State:
    """A SImageryStateHeader entry."""

    index: int
    name: str
    flags: int
    aniflags: int
    frames: int
    width: int
    height: int
    regx: int
    regy: int
    regz: int
    animregx: int
    animregy: int
    animregz: int
    invaniflags: int
    invframes: int


@dataclass(frozen=True)
class ExportedImage:
    """One image (or animation) found in an I2D file."""

    kind: str
    label: str
    frames: Sequence[Bitmap]
    suffix: str

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    @property
    def extension(self) -> str:
        return 'gif' if self.animated else 'png'

    def summary(self) -> str:
        first = self.frames[0]
        size = f'{first.width}x{first.height}'
        if self.animated:
            size = f'{size}, {len(self.frames)} frames'
        extra = '' if self.kind == KIND_BITMAP else f', {first.description}'
        return f'{self.label}: {size}{extra}'


def _state_suffix(kind: str, state: State, numstates: int) -> str:
    """File name suffix for an image of a given state."""
    if numstates > 1:
        return f's{state.index:02d}_{kind}'
    return kind


def _state_label(kind: str, state: State) -> str:
    name = state.name or 'unnamed'
    return f'{kind} (state {state.index} "{name}")'


class I2DFile:
    """A parsed I2D imagery resource."""

    def __init__(
        self,
        path: Path,
        header: bytes,
        body: bytes,
        imagery_id: int,
        numstates: int,
        topbm: int,
        version: int,
        comptype: int,
        states: list[State],
        bitmap_offsets: tuple[int, ...] = (),
    ):
        self.path = path
        self.header = header
        self.body = body
        self.imagery_id = imagery_id
        self.numstates = numstates
        self.topbm = topbm
        self.version = version
        self.comptype = comptype
        self.states = states
        self.bitmap_offsets = bitmap_offsets

    def images(self, inventory: bool = True, animation: bool = True) -> Iterator[ExportedImage]:
        """Yield every image the imagery states refer to."""
        if self.imagery_id != IMAGERY_ANIMATION:
            msg = (
                f'imagery id {self.imagery_id} is not 2D animation imagery '
                f'(only id {IMAGERY_ANIMATION} is supported)'
            )
            raise I2DError(msg)

        for state in self.states:
            base = state.index * ANIM_STATE_SIZE
            still_field = base
            anim_field = base + 4
            invitem_field = base + 8
            invanim_field = base + 12
            size_hint = (state.width, state.height)

            still = _pointer(self.body, still_field)
            if still is not None:
                yield ExportedImage(
                    kind=KIND_STILL,
                    label=_state_label(KIND_STILL, state),
                    frames=[read_bitmap(self.body, still, size_hint)],
                    suffix=_state_suffix(KIND_STILL, state, self.numstates),
                )

            if animation:
                frames = read_animation(self.body, anim_field)
                if frames:
                    yield ExportedImage(
                        kind=KIND_ANIMATION,
                        label=_state_label(KIND_ANIMATION, state),
                        frames=frames,
                        suffix=_state_suffix(KIND_ANIMATION, state, self.numstates),
                    )

            if not inventory:
                continue

            invitem = _pointer(self.body, invitem_field)
            if invitem is not None:
                yield ExportedImage(
                    kind=KIND_INVENTORY,
                    label=_state_label(KIND_INVENTORY, state),
                    frames=[read_bitmap(self.body, invitem, size_hint)],
                    suffix=_state_suffix(KIND_INVENTORY, state, self.numstates),
                )

            if animation:
                frames = read_animation(self.body, invanim_field)
                if frames:
                    yield ExportedImage(
                        kind=KIND_INVENTORY_ANIMATION,
                        label=_state_label(KIND_INVENTORY_ANIMATION, state),
                        frames=frames,
                        suffix=_state_suffix(
                            KIND_INVENTORY_ANIMATION,
                            state,
                            self.numstates,
                        ),
                    )

    def bitmaps(self) -> Iterator[ExportedImage]:
        """Yield raw bitmaps from the file's bitmap table.

        Only used for files whose states do not reference any imagery (the two
        ``automap.i2d`` files); their marker bitmaps are still worth exporting.
        """
        for index, offset in enumerate(self.bitmap_offsets):
            yield ExportedImage(
                kind=KIND_BITMAP,
                label=f'bitmap {index}',
                frames=[read_bitmap(self.body, offset)],
                suffix=f'bm{index:02d}',
            )


def read_i2d(path: Path) -> I2DFile:
    """Parse the I2D resource file at ``path``."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise I2DError(str(error)) from error

    if len(data) < RES_HEADER_SIZE:
        msg = 'file is too small to be an I2D resource'
        raise I2DError(msg)

    resmagic, topbm, comptype, version, datasize, _objsize, hdrsize = (
        _FILE_RES_HEADER.unpack_from(data, 0)
    )
    if data[:4] != RES_MAGIC:
        msg = f'bad magic {resmagic:#010x}, expected {RES_MAGIC!r}'
        raise I2DError(msg)
    if version != RES_VERSION:
        msg = f'unsupported resource version {version}'
        raise I2DError(msg)

    header_offset = RES_HEADER_SIZE
    _need(data, header_offset, hdrsize, 'imagery header')
    header = data[header_offset:header_offset + hdrsize]

    if hdrsize < _IMAGERY_HEADER.size:
        msg = 'imagery header is truncated'
        raise I2DError(msg)

    imagery_id, numstates = _IMAGERY_HEADER.unpack_from(header, 0)
    if numstates < 0:
        msg = f'bad state count {numstates}'
        raise I2DError(msg)

    states: list[State] = []
    for index in range(numstates):
        offset = _IMAGERY_HEADER.size + index * STATE_HEADER_SIZE
        _need(header, offset, STATE_HEADER_SIZE, 'SImageryStateHeader')
        values = _STATE_HEADER.unpack_from(header, offset)
        name = values[0].split(b'\0', 1)[0].decode('latin-1').strip()
        states.append(
            State(
                index=index,
                name=name,
                flags=values[2],
                aniflags=values[3],
                frames=values[4],
                width=values[5],
                height=values[6],
                regx=values[7],
                regy=values[8],
                regz=values[9],
                animregx=values[10],
                animregy=values[11],
                animregz=values[12],
                invaniflags=values[19],
                invframes=values[20],
            )
        )

    bitmap_offsets: tuple[int, ...] = ()
    if topbm:
        table_offset = header_offset + hdrsize
        _need(data, table_offset, 4 * topbm, 'bitmap table')
        bitmap_offsets = struct.unpack_from(f'<{topbm}I', data, table_offset)

    body_offset = header_offset + hdrsize + 4 * topbm
    if body_offset >= len(data):
        msg = 'imagery body is missing'
        raise I2DError(msg)

    body = data[body_offset:min(len(data), body_offset + datasize)]
    if len(body) < datasize:
        msg = f'imagery body is truncated ({len(body)} of {datasize} bytes)'
        raise I2DError(msg)

    return I2DFile(
        path=path,
        header=header,
        body=body,
        imagery_id=imagery_id,
        numstates=numstates,
        topbm=topbm,
        version=version,
        comptype=comptype,
        states=states,
        bitmap_offsets=bitmap_offsets,
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def compose_frames(frames: Sequence[Bitmap]) -> list[Image.Image]:
    """Render animation frames on a shared canvas, aligned by registration points."""
    if len(frames) == 1:
        return [frames[0].to_image()]

    left = max(frame.regx for frame in frames)
    top = max(frame.regy for frame in frames)
    positions = [(left - frame.regx, top - frame.regy) for frame in frames]
    width = max(position[0] + frame.width for position, frame in zip(positions, frames))
    height = max(position[1] + frame.height for position, frame in zip(positions, frames))

    images: list[Image.Image] = []
    for position, frame in zip(positions, frames):
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        canvas.paste(frame.to_image(), position)
        images.append(canvas)
    return images


def save_png(bitmap: Bitmap, path: Path) -> None:
    bitmap.to_image().save(path, 'PNG')


def _gif_frame(image: Image.Image) -> Image.Image:
    """Convert an RGBA frame into a paletted GIF frame with a transparent index.

    Pillow's own RGBA -> P conversion takes the transparent index from the
    quantised palette, which loses transparency when a frame mixes transparent
    and semi-transparent pixels (the flame animations do).  Reserving index 255
    for transparency and painting the transparent pixels with it keeps the
    background transparent, at the price of a hard alpha cut-off.
    """
    alpha = image.getchannel('A')
    frame = image.convert('RGB').quantize(
        colors=GIF_TRANSPARENT_INDEX,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    transparent = alpha.point(lambda value: 255 if value < GIF_ALPHA_THRESHOLD else 0)
    frame.paste(GIF_TRANSPARENT_INDEX, mask=transparent)
    frame.info['transparency'] = GIF_TRANSPARENT_INDEX
    return frame


def save_gif(frames: Sequence[Bitmap], path: Path, duration: int) -> None:
    images = [_gif_frame(image) for image in compose_frames(frames)]
    first, rest = images[0], images[1:]
    first.save(
        path,
        format='GIF',
        save_all=True,
        append_images=rest,
        duration=duration,
        loop=0,
        disposal=2,
        optimize=False,
        transparency=GIF_TRANSPARENT_INDEX,
    )


def save_image(image: ExportedImage, path: Path, duration: int) -> None:
    if image.animated:
        save_gif(image.frames, path, duration)
    else:
        save_png(image.frames[0], path)


# --------------------------------------------------------------------------- #
# Command line interface
# --------------------------------------------------------------------------- #

def find_files(paths: Iterable[Path], recursive: bool) -> list[Path]:
    """Expand the given files/directories into a sorted list of I2D files."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            pattern = '**/*.[iI]2[Dd]' if recursive else '*.[iI]2[Dd]'
            found.extend(sorted(path.glob(pattern)))
        else:
            found.append(path)
    return found


def report_file(file: I2DFile) -> None:
    """Print the structure of a parsed I2D file."""
    print(
        f'{file.path.name}: imagery={file.imagery_id}, states={file.numstates}, '
        f'bitmaps={file.topbm}, version={file.version}, compression={file.comptype}'
    )
    for state in file.states:
        print(
            f'  state {state.index} "{state.name}": flags=0x{state.flags:08x}, '
            f'frames={state.frames}, size={state.width}x{state.height}, '
            f'reg=({state.regx}, {state.regy}, {state.regz}), invframes={state.invframes}'
        )
    images = list(file.images())
    if not images:
        images = list(file.bitmaps())
    for image in images:
        print(f'    {image.summary()}')


@click.command()
@click.argument('paths', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    '-o', '--output-folder', default=None, type=click.Path(file_okay=False, path_type=Path),
    help='Folder for generated images (default: next to the source file).',
)
@click.option('-r', '--recursive', is_flag=True, help='Search sub-folders of given folders.')
@click.option(
    '--fps', default=24.0, show_default=True, type=float,
    help='Animation speed used for the GIF frame delay.',
)
@click.option('--no-inventory', is_flag=True, help='Do not export inventory images.')
@click.option('--no-animation', is_flag=True, help='Do not export animations.')
@click.option('--no-overwrite', is_flag=True, help='Keep already existing image files.')
@click.option('--info', is_flag=True, help='Only print the structure of the given files.')
@click.option('-q', '--quiet', is_flag=True, help='Only print errors.')
def main(
    paths: tuple[Path, ...],
    output_folder: Path | None,
    recursive: bool,
    fps: float,
    no_inventory: bool,
    no_animation: bool,
    no_overwrite: bool,
    info: bool,
    quiet: bool,
) -> None:
    """Convert I2D imagery files into PNG (static) or GIF (animated) images.

    PATHS may be I2D files or folders with I2D files.
    """
    if fps <= 0:
        raise click.UsageError('--fps must be a positive number')

    files = find_files(paths, recursive)
    if not files:
        hint = '' if recursive else ' (use --recursive to search sub-folders)'
        raise click.UsageError(f'No I2D files found{hint}')

    duration = max(10, round(1000.0 / fps))
    exported = 0
    failed = 0

    for path in files:
        try:
            file = read_i2d(path)
            if info:
                report_file(file)
                continue

            folder = output_folder if output_folder is not None else path.parent
            folder.mkdir(parents=True, exist_ok=True)

            images = list(file.images(inventory=not no_inventory, animation=not no_animation))
            if not images:
                # files without imagery states (the automap markers) keep their
                # bitmaps only in the bitmap table
                images = list(file.bitmaps())
            if not images:
                if not quiet:
                    print(f'{path.name}: nothing to export')
                continue

            for image in images:
                stem = path.stem
                name = stem if len(images) == 1 else f'{stem}_{image.suffix}'
                target = folder / f'{name}.{image.extension}'

                if no_overwrite and target.exists():
                    if not quiet:
                        print(f'{path.name} -> {target.name}: already exists, skipped')
                    continue

                save_image(image, target, duration)
                exported += 1
                if not quiet:
                    print(f'{path.name} -> {target}: {image.summary()}')

        except (I2DError, OSError) as error:
            failed += 1
            print(f'{path.name}: {error}', file=sys.stderr)

    if not quiet and not info:
        print(f'Done: {exported} image(s) written, {failed} file(s) failed')

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
