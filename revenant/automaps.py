"""Automap processing.

This module is created to work with automap images and map (dat) files.

Original code was written by Vinylon
http://accursedfarms.com/forums/viewtopic.php?f=63&t=8128

Some illustrating tweaks by Nicord
https://www.moddb.com/mods/the-forsaken
"""
import os.path
import sys
from typing import Callable

from PIL import Image


def scan_for_files(directory, extension):
    """
    Scans directory for sequence of files.
    Considered pattern is [name]_[x]_[y].
    Both maps ('dat' files) and automaps ('bmp' files) are supported,
    but you need to mention file extension.

    Each parameter in filename must be a number (including negative),
    Length of the parameter must be less than 4 letters.

    :param directory: where to search files, for example 'automaps/"
    :param extension: specific type of file, only 'bmp' or 'dat' are supported
    :return: dictionary with found sequences and their parameters. False if nothing found
    """
    if directory[-1] != '/' and directory[-1] != '\\':
        directory = directory + '/'

    if os.path.isdir(directory):
        files = os.listdir(directory)

    else:
        print(f'No directory named "{directory}" has been found!')
        return False

    print(f'Scanning "{directory}" for files like "name_x_y.{extension}"')

    names = []
    raw_data = []
    ignored = 0

    for file in files:
        if file[-3:].lower() != extension.lower():
            # wrong extension
            ignored += 1
            continue

        if os.path.isfile(directory + file):
            name_x_y = file.split('_')

            file_is_correct = True

            if len(name_x_y) != 3:
                ignored += 1
                continue
            else:
                # removing extension
                name_x_y[2] = name_x_y[2][0:-4]

            if len(name_x_y[0]) > 3:
                file_is_correct = False

            if len(name_x_y[1]) > 3:
                file_is_correct = False

            if len(name_x_y[2]) > 3:
                file_is_correct = False

            if not str(name_x_y[0]).isdigit():
                file_is_correct = False

            # checking for negative numbers
            if name_x_y[1][0] == '-':
                if not str(name_x_y[1][1:]).isdigit():
                    file_is_correct = False
            else:
                if not str(name_x_y[1]).isdigit():
                    file_is_correct = False

            # checking for negative numbers
            if name_x_y[2][0] == '-':
                if not str(name_x_y[2][1:]).isdigit():
                    file_is_correct = False
            else:
                if not str(name_x_y[2]).isdigit():
                    file_is_correct = False

            if file_is_correct:
                names.append(int(name_x_y[0]))
                # Files are named by pattern name_x_y.type
                file_size = os.path.getsize(directory + file)
                raw_data.append(
                    [int(name_x_y[0]), int(name_x_y[1]), int(name_x_y[2]),
                     file_size])
            else:
                ignored += 1
                continue

    unique_names = list(set(names))

    if not unique_names:
        print('...nothing found')
        return False

    data = {}

    for name in unique_names:
        data[name] = []
        data[name].append(names.count(name))
        list_of_x = []
        list_of_y = []
        list_of_sizes = []

        for raw in raw_data:
            # name_x_y
            if raw[0] == name:
                list_of_x.append(raw[1])
                list_of_y.append(raw[2])
                list_of_sizes.append(raw[3])

        # Data is formed using template
        # [name]:[counts][minX][maxX][minY][maxY][directory][min_size][max_size]
        data[name].append(min(list_of_x))
        data[name].append(max(list_of_x))
        data[name].append(min(list_of_y))
        data[name].append(max(list_of_y))
        data[name].append(directory)
        data[name].append(min(list_of_sizes))
        data[name].append(max(list_of_sizes))

    print()
    print('\t Found %d tiles for %d maps in "%s" (%d files ignored)' %
          (len(raw_data), len(data.keys()), directory[:-1], ignored))
    return data


def stitch_automaps(data, dest_dir='RevAPI_automaps'):
    """
    Stitches big automap image from small tiles and saves it as bmp file.

    :param data: prepared dictionary from scan_for_files func
    :param dest_dir: where to save files
    :return: True if nothing interrupted the process. False if there are any errors.
    """
    if not data:
        return False

    tile_size = 64  # in pixels
    iteration = 1

    for key in data.keys():
        has_maps = False

        min_x = data[key][1]
        max_x = data[key][2]
        min_y = data[key][3]
        max_y = data[key][4]
        directory = data[key][5]

        filename = directory[:-1]

        map_width = abs(min_x - max_x) + 1
        map_height = abs(min_y - max_y) + 1

        map_image = Image.new('RGB',
                              (tile_size * map_width, tile_size * map_height))

        for curr_y in range(min_y, max_y + 1):
            for curr_x in range(min_x, max_x + 1):
                tile_file = directory + "%d_%d_%d.bmp" % (key, curr_x, curr_y)

                if os.path.isfile(tile_file):
                    # not all files in allowed range actually exist
                    has_maps = True
                    tile_image = Image.open(tile_file)
                    paste_x = tile_size * (curr_x - min_x)
                    paste_y = tile_size * (curr_y - min_y)
                    map_image.paste(tile_image, (paste_x, paste_y))

        if not os.path.isdir(dest_dir):
            os.mkdir(dest_dir)

        new_file = dest_dir + '/' + filename + '_' + str(key).rjust(2,
                                                                    '0') + '.bmp'

        if has_maps:
            if os.path.isfile(new_file):

                # do not overwrite!
                add = 1
                while os.path.isfile(new_file):
                    new_file = dest_dir + '/' + filename + '_' + \
                               str(key).rjust(2, '0') + '(' + str(
                        add) + ').bmp'
                    add += 1

            num = str(key).rjust(2)
            width = str(tile_size * map_width).rjust(4)
            height = str(tile_size * map_height).ljust(4)
            tile = str(data[key][0]).rjust(3)
            file = new_file.ljust(20)
            left = str(len(data.keys()) - iteration).rjust(2)

            map_image.save(new_file, 'BMP')

            print('\t\tAutomap [%s] is done, resolution [%s x %s],'
                  ' [%s] tiles, saved as %s (%s files left)' %
                  (num, width, height, tile, file, left))

            iteration += 1

    return True


def stitch_heatmaps(data, dest_dir='RevAPI_heatmaps'):
    """
    Whole game world in Revenant is built like a mesh out of small *.dat files.
    Each map file contains data about any objects located there.
    When you play the game, all changes in game world (all differences from original map *.dat files)
    are saved in your savegame directory

    This function stitches big heatmap image from *.dat files and saves it as bmp file.
    Heatmap is built based on size of the files. Bigger the file, brighter the tile it represents.

    :param data: prepared dictionary from scan_for_files func
    :param dest_dir: destination directory, where to save results
    :return: True if nothing interrupted the process. False if there are any errors.
    """
    if not data:
        return False

    tile_size = 16  # in pixels
    iteration = 1

    for key in data.keys():
        has_maps = False

        min_x = data[key][1]
        max_x = data[key][2]
        min_y = data[key][3]
        max_y = data[key][4]
        directory = data[key][5]
        # min_size = data[key][6]
        max_size = data[key][7]

        filename = directory[:-1]

        map_width = abs(min_x - max_x) + 1
        map_height = abs(min_y - max_y) + 1

        map_image = Image.new('RGB',
                              (tile_size * map_width, tile_size * map_height),
                              (32, 32, 32))

        for curr_y in range(min_y, max_y + 1):
            for curr_x in range(min_x, max_x + 1):
                tile_file = directory + "%d_%d_%d.dat" % (key, curr_x, curr_y)

                if os.path.isfile(tile_file):
                    # not all files in allowed range actually exist
                    has_maps = True
                    file_size = os.path.getsize(tile_file)

                    delta = 256 / max_size  # minimum size is usually too small to be used

                    color = int(file_size * delta)

                    if color < 16:
                        color = 16

                    tile_image = Image.new('RGB', (tile_size, tile_size),
                                           (color, 0, color))  # violet shades

                    paste_x = tile_size * (curr_x - min_x)
                    paste_y = tile_size * (curr_y - min_y)
                    map_image.paste(tile_image, (paste_x, paste_y))

        if not os.path.isdir(dest_dir):
            os.mkdir(dest_dir)

        new_file = dest_dir + '/' + filename + '_' + str(key).rjust(2,
                                                                    '0') + '.bmp'

        if has_maps:
            if os.path.isfile(new_file):
                add = 1
                while os.path.isfile(new_file):
                    new_file = dest_dir + '/' + filename + '_' + str(
                        key).rjust(2, '0') + '(' + str(add) + ').bmp'
                    add += 1

            num = str(key).rjust(2)
            width = str(tile_size * map_width).rjust(4)
            height = str(tile_size * map_height).ljust(4)
            tile = str(data[key][0]).rjust(3)
            file = new_file.ljust(20)
            left = str(len(data.keys()) - iteration).rjust(2)

            map_image.save(new_file, 'BMP')

            print(
                '\t\tHeatmap [%s] is done, resolution [%s x %s], [%s] tiles, saved as %s (%s files left)' %
                (num, width, height, tile, file, left))

            iteration += 1

    return True


def stitch_progress(source_data, progress_data, dest_dir='RevAPI_progress'):
    """
    This function requires already built heatmaps of original level (violet).
    Player's progress will be painted using green heatmaps over given originals.
    Heatmap is built based on size of the files. Bigger the file, brighter the tile it represents.

    :param source_data: prepared dictionary from scan_for_files func. This describes default world map
    :param progress_data: prepared dictionary from scan_for_files func. This describes player progress
    :param dest_dir: destination directory, where to save results
    :return: True if nothing interrupted the process. False if there are any errors.
    """
    if not progress_data:
        return False

    tile_size = 16  # in pixels
    iteration = 1

    for key in progress_data.keys():
        has_maps = False

        min_x = source_data[key][1]
        max_x = source_data[key][2]
        min_y = source_data[key][3]
        max_y = source_data[key][4]

        directory = progress_data[key][5]
        # min_size = progress_data[key][6]
        max_size = progress_data[key][7]

        map_width = abs(min_x - max_x) + 1
        map_height = abs(min_y - max_y) + 1

        filename = directory[:-1]

        source_file = dest_dir + '/' + source_data[key][5][:-1] + '_' + str(
            key).rjust(2, '0') + '.bmp'

        if os.path.isfile(source_file):
            map_image = Image.open(source_file)
        else:
            map_image = Image.new('RGB', (
                tile_size * map_width, tile_size * map_height), (32, 32, 32))

        for curr_y in range(min_y, max_y + 1):
            for curr_x in range(min_x, max_x + 1):
                tile_file = directory + "%d_%d_%d.dat" % (key, curr_x, curr_y)

                if os.path.isfile(tile_file):
                    # not all files in allowed range actually exist
                    has_maps = True
                    file_size = os.path.getsize(tile_file)

                    delta = 256 / max_size

                    color = int(file_size * delta)

                    if color < 16:
                        color = 16

                    tile_image = Image.new('RGB', (tile_size, tile_size),
                                           (0, color, 0))  # green shades

                    paste_x = tile_size * (curr_x - min_x)
                    paste_y = tile_size * (curr_y - min_y)
                    map_image.paste(tile_image, (paste_x, paste_y))

        if not os.path.isdir(dest_dir):
            os.mkdir(dest_dir)

        new_file = source_file[:-4] + '_' + filename + '_' + str(key).rjust(2,
                                                                            '0') + '.bmp'

        if has_maps:
            if os.path.isfile(new_file):
                add = 1
                while os.path.isfile(new_file):
                    new_file = source_file[:-4] + '_' + filename + '_' + \
                               str(key).rjust(2, '0') + '(' + str(
                        add) + ').bmp'
                    add += 1

            num = str(key).rjust(2)
            width = str(tile_size * map_width).rjust(4)
            height = str(tile_size * map_height).ljust(4)
            tile = str(progress_data[key][0]).rjust(3)
            file = new_file.ljust(20)
            left = str(len(progress_data.keys()) - iteration).rjust(2)

            map_image.save(new_file, 'BMP')

            print(
                '\t\tProgress heatmap [%s] is done, resolution [%s x %s], [%s] tiles, saved as %s (%s files left)' %
                (num, width, height, tile, file, left))

            iteration += 1

    return True


def save_all_automaps(path: str = '', extension: str = 'bmp') -> None:
    """Save all automaps including nested directories.

    If finds files that fit into template name_x_y.bmp,
    applies automaps stitching function to them.
    """
    save_all(
        path=path,
        extension=extension,
        on_success='Conversion complete. {i} files converted as automaps',
        on_fail='No automap files found in nearby directories',
        handler=stitch_automaps,
    )


def save_all_heatmaps(path: str = '', extension: str = 'dat'):
    """Save all heatmaps including nested directories.

    If finds files that fit into template name_x_y.dat,
    applies heatmaps stitching function to them.
    """
    save_all(
        path=path,
        extension=extension,
        on_success='Conversion complete. {i} files converted as heatmaps',
        on_fail=('No suitable to heatmap creation '
                 'files are found in nearby directories'),
        handler=stitch_heatmaps,
    )


def save_all(path: str, extension: str, on_success: str,
             on_fail: str, handler: Callable) -> None:
    """Generic function for automap/heatmap stitching."""
    path = path or os.curdir

    i = 0
    for folder in os.listdir(path):
        if os.path.isdir(folder):
            data = scan_for_files(folder, extension)
            if data:
                handler(data)
                i += 1

    if i:
        print(on_success.format(i))
    else:
        print(on_fail)


def show_progress_on_map(source='map', progress='savegame'):
    """
    Guide for the stitch_progress function.
    To make this script work you need two sets of dat files - originals and from save game directory.
    At first, script makes regular heatmap stitching for the source directory.
    At second, it makes heatmaps for progress directory and paints them over pictures of source ones.
    As the result you can see player's progress over game map painted in green.

    :param source: name of the directory that contains original dat files (from non started game)
    :param progress: name of the directory that contains player's progress (dat files from saved game)
    :return: True if nothing interrupted the process. False if there are any errors.
    """
    source_data = scan_for_files(source, 'dat')
    progress_data = scan_for_files(progress, 'dat')

    if progress_data and source_data:

        source_stitched = stitch_heatmaps(source_data,
                                          'RevAPI_progress')

        progress_stitched = stitch_progress(source_data,
                                            progress_data,
                                            'RevAPI_progress')

        return source_stitched and progress_stitched
    else:
        if (not progress_data) and source_data:
            print('Not enough information to show progress. '
                  'Progress directory is empty.')

        elif progress_data and (not source_data):
            print('Not enough information to show progress. '
                  'Source directory is empty.')

        else:
            print('Not enough information to show progress. No input data.')

    return False


if __name__ == '__main__':
    args = sys.argv[1:]

    if len(args) < 2 or len(args) > 3:
        print('You need to specify mode to run this script')
        print()
        print('Possible examples:')
        print('python automaps.py automaps *')
        print('python automaps.py automaps my_dir')
        print('python automaps.py heatmaps *')
        print('python automaps.py heatmaps my_dir')
        print('python automaps.py progress src1_dir src2_dir')
        sys.exit()

    mode, directory, *rest = args

    mode = mode.lower().strip()
    directory = directory.strip()

    if mode == 'heatmaps':
        if directory == '*':
            save_all_heatmaps()
        else:
            save_all_heatmaps(directory)

    elif mode == 'automaps':
        if directory == '*':
            save_all_automaps()
        else:
            save_all_automaps(directory)

    elif mode == 'progress':
        source, target, *_ = rest
        show_progress_on_map(source, target)

    else:
        print(f'Arguments are not recognised: {args}')
