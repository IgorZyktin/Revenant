"""Automap processing.

This module is created to work with automap images.

Original code was written by Vinylon
http://accursedfarms.com/forums/viewtopic.php?f=63&t=8128
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import click
from PIL import Image


@click.command()
@click.option('--source-folder')
@click.option('--output-folder', default='.')
def main(source_folder: str | None, output_folder: str):
    """Entry point."""
    if source_folder is None:
        msg = 'You have to specify source folder'
        sys.exit(msg)

    source = Path(source_folder)
    if not source.exists():
        msg = f'Source folder {source_folder!r} does not exist'
        sys.exit(msg)

    output = Path(output_folder)
    if not output.exists():
        output.mkdir(parents=True, exist_ok=True)

    data = scan_for_files(source)
    stitch_automaps(data, source, output)


@dataclass(frozen=True)
class Tile:
    """Single tile."""
    name: str
    x: int
    y: int
    size: int


def scan_for_files(source: Path, extension: str = 'bmp') -> list[Tile]:
    """Scan directory for source files.

    Considered pattern is [name]_[x]_[y].
    """
    print(f'Scanning "{source}" for files like "name_x_y.{extension}"')
    tiles: list[Tile] = []

    for entry in source.iterdir():
        if not entry.is_file():
            continue

        if not entry.name.endswith(extension):
            continue

        string = entry.name[:-len(extension) - 1]
        parts = string.split('_')

        if len(parts) != 3:
            continue

        name, x, y = parts
        tiles.append(
            Tile(
                name=name,
                x=int(x),
                y=int(y),
                size=entry.stat().st_size,
            )
        )

    if not tiles:
        msg = 'No automap files found'
        sys.exit(msg)

    print(f'Found {len(tiles)} tiles in {source}')
    return tiles


def stitch_automaps(tiles: list[Tile], source: Path, output: Path) -> None:
    """Stitch big automap image from small tiles and save it as bmp file."""
    if not tiles:
        return

    tile_size = 64  # in pixels
    tiles_by_name: dict[str, list[Tile]] = {}

    for tile in tiles:
        tiles_by_name.setdefault(tile.name, []).append(tile)

    for name in sorted(tiles_by_name):
        local_tiles = tiles_by_name[name]

        min_x = 0
        max_x = 0
        min_y = 0
        max_y = 0
        for local_tile in local_tiles:
            min_x = min(min_x, local_tile.x)
            min_y = min(min_y, local_tile.y)
            max_x = max(max_x, local_tile.x)
            max_y = max(max_y, local_tile.y)

        map_width_in_tiles = abs(min_x - max_x) + 1
        map_height_in_tiles = abs(min_y - max_y) + 1
        map_width = map_width_in_tiles * tile_size
        map_height = map_height_in_tiles * tile_size
        map_image = Image.new('RGB', (map_width, map_height))

        has_maps = False
        for curr_y in range(min_y, max_y + 1):
            for curr_x in range(min_x, max_x + 1):
                filename = f'{name}_{curr_x}_{curr_y}.bmp'
                path = source / filename

                if path.exists():
                    # not all files in allowed range actually exist
                    has_maps = True
                    tile_image = Image.open(path)
                    paste_x = tile_size * (curr_x - min_x)
                    paste_y = tile_size * (curr_y - min_y)
                    map_image.paste(tile_image, (paste_x, paste_y))

        long_name = name.rjust(2, '0')
        new_file = output / f'automap_{long_name}.png'

        if has_maps:
            map_image.save(new_file, 'PNG')

            print(
                f'Automap [{long_name}] is done, resolution [{map_width} x {map_height}], '
                f'{len(local_tiles)} tiles, saved as {new_file}'
            )


if __name__ == '__main__':
    main()
