"""

    This module is created for easy conversion dat->bmp and bmp->dat.

    Game uses strange color encoding system, similar to r5g5b5a1 
    (five bits for color and one for alpha channel). But encoding bits are shifted for some reason.
    
    Real game color format is: 
    [G3][G4][G5][B1][B2][B3][B4][B5][A][R1][R2][R3][R4][R5][G1][G2]
    
    For example:
    red   0000000001111100
    green 1110000000000011
    blue  0001111100000000
    
    Each file also contains header with technical information. Contents of the header are unknown.
    For example, loadgamealpha.dat has 616 560 bytes. We know that it contains 640x480 pixels image,
    with two bytes per pixel. Therefore it has 640 x 480 x 2 bytes = 307 200 x 2 = 614 400 bytes of
    graphical content. File size is 616 560 bytes, therefore header is 616 560 - 614 400 = 2160 bytes. 
    If you start to read from byte number 2160, you will get colors of the pixels
    
    Example 1: save all dat files in current directory as bmp files (including loadbars and buttons)
    
    all_dat_to_bmp()
    
    Example 2: save single dat file as bmp file
    
    dat_to_bmp('menus.dat')
    
    Example 3: merge existing bmp files into existing dat file. If it's a single image, you need
    file_main.bmp. If dat file requires more than one file, then you need to create sequence. 
    Simplest way to do that - extract with dat_to_bmp func, change files you need, and repack it back.
    
    insert_bmp_into_dat('menus.dat')
"""
import os.path
import sys

from PIL import Image


def pack_color(rgb_color):
    """
    Packing color into Revenant game format

    :param rgb_color: tuple with three values (R 0-255, G 0-255, B 0-255)
    :return: encoded color (0-255, 0-255)
    """
    red = int(rgb_color[0] / 8)
    green = int(rgb_color[1] / 8)
    blue = int(rgb_color[2] / 8)

    red = bin(red)[2:].rjust(5, '0')
    green = bin(green)[2:].rjust(5, '0')
    blue = bin(blue)[2:].rjust(5, '0')

    encoded_color = green[2:] + blue + '0' + red + green[
                                                   :2]  # '0' is for alpha-channel

    rev_color_a = int(encoded_color[0:8], 2)
    rev_color_b = int(encoded_color[8:], 2)

    return rev_color_a, rev_color_b


def unpack_color(rev_color_a, rev_color_b):
    """
    Unpacking color from Revenant game format

    :param rev_color_a: encoded color (0-255) part A
    :param rev_color_b: encoded color (0-255) part B
    :return: tuple with three values (R 0-255, G 0-255, B 0-255)
    """
    color_1 = bin(rev_color_a)[2:].rjust(8, '0')
    color_2 = bin(rev_color_b)[2:].rjust(8, '0')

    color = color_1 + color_2

    red = color[9:14]
    green = color[-2:] + color[0:3]
    blue = color[3:8]

    red = int(red, 2) * 8
    green = int(green, 2) * 8
    blue = int(blue, 2) * 8

    return red, green, blue


def get_known_files():
    """
    Loads already known files from known.txt
    Syntax is [name.dat] [start] [width] [height] [postfix]

    :return: list of known files
    """
    known_file = '..\\known.txt'
    known = []
    if os.path.isfile(known_file):
        with open(known_file) as file:
            for line in file:
                if len(line) > 3:
                    param = line.split()
                    #            filename        start          width         height      postfix
                    known.append(
                        [param[0], int(param[1]), int(param[2]), int(param[3]),
                         param[4]])
                else:
                    continue
    else:
        print('known.txt file is not found')
        return False
    return known


def dat_to_bmp(filename, postfix='main'):
    """
    Extracts pixel data from dat file and saves it as bmp file

    :param filename: Specified file, like demo.dat
    :param postfix: specified sub image (buttons, load bars, etc.)
    :return:  True if result saved, False if not
    """

    if not os.path.isfile(filename):
        print('Unable to start conversion, [%s] is not found.' % filename)
        return False

    known = get_known_files()

    if not known:
        print(
            'Unable start conversion, list of known files is not found.' % filename)
        return False

    # Files with [postfix] other than ours might have some additional data inside
    # We're putting them into list and will return to them at the end of this function
    sub_files = []
    current_file = ''
    for line in known:
        if line[0] == filename:
            if postfix == line[4]:
                current_file = line
            else:
                sub_files.append(line)

    if not current_file:
        print(
            'Unable to start conversion, file [%s] has unknown structure.' % filename)
        return False

    start = current_file[1]
    width = current_file[2]
    height = current_file[3]
    postfix = current_file[4]

    bmp_image = Image.new('RGB', (width, height), (0, 0, 0))

    with open(filename, 'rb') as file:
        raw_data = file.read()

    data = []
    i = 0
    # skipping header of the file
    for chunk in raw_data:
        if i >= start:  # pixels start on this position
            data.append(int(chunk))
        else:
            i += 1
    i = 0
    for img_y in range(0, height):
        for img_x in range(0, width):
            if i + 3 < len(data):
                rgb_color = unpack_color(data[i], data[i + 1])
                bmp_image.putpixel((img_x, img_y), rgb_color)
                i += 2  # one bmp pixel is two bytes in game's pixels
            else:
                break

    output_name = filename[0:-4] + '_' + str(postfix) + '.bmp'

    # do not overwrite!
    if os.path.isfile(output_name):
        add = 1
        while os.path.isfile(output_name):
            output_name = filename[0:-4] + '_' + str(postfix) + '(' + str(
                add).rjust(2, '0') + ').bmp'
            add += 1

    bmp_image.save(output_name)

    print(
        'dat -> bmp conversion is successful. [%s] is converted and saved as [%s]' % (
            filename, output_name))

    # recursive extraction
    if postfix == 'main' and len(sub_files) > 0:
        for file in sub_files:
            dat_to_bmp(file[0], file[4])  # filename.dat + postfix
    return True


def insert_bmp_into_dat(dat_name, postfix='main'):
    """
    Takes existing dat file and merge bmp image into it.

    :param dat_name: put our data into this file
    :param postfix: specified sub image (buttons, load bars, etc.)
    :return: True if result saved, False if not
    """
    bmp_name = dat_name[0:-4] + '_' + postfix + '.bmp'

    have_dat = os.path.isfile(dat_name)
    have_bmp = os.path.isfile(bmp_name)

    if not have_bmp and not have_dat:
        print(
            'Unable to start conversion, both [%s] and [%s] are not found.' % (
                dat_name, bmp_name))
        return False
    elif have_bmp and not have_dat:
        print(
            'Unable to start conversion, target file [%s] is not found.' % dat_name)
        return False
    elif not have_bmp and have_dat:
        print(
            'Unable to start conversion, source file [%s] is not found.' % bmp_name)
        return False

    known = get_known_files()

    if not known:
        print(
            'Unable to start conversion, list of known files is not found.' % dat_name)
        return False

    # Files with [postfix] other than ours might have some additional data inside
    # We're putting them into list and will return to them at the end of this function
    sub_files = []
    current_file = ''
    for line in known:
        if line[0] == dat_name:
            if postfix == line[4]:
                current_file = line
            else:
                sub_files.append(line)

    if not current_file:
        print(
            'Unable to start conversion, file [%s] has unknown structure.' % dat_name)
        return False

    start = current_file[1]
    postfix = current_file[4]

    bmp_data = Image.open(bmp_name, 'r')
    bmp_data = list(bmp_data.getdata())

    with open(dat_name, 'rb') as dat_file:
        raw_data = dat_file.read()

    data = []

    new_pixels = len(bmp_data)
    pixel_space = 0

    for i in range(0, len(raw_data), 2):
        if start <= i < (
                start + new_pixels * 2):  # one bmp pixel is two bytes in game's pixels
            color = pack_color(bmp_data[pixel_space])
            data.append(color[0])
            data.append(color[1])
            pixel_space += 1
        else:
            data.append(raw_data[i])
            data.append(raw_data[i + 1])

    # file wil be overwritten
    output_name = dat_name

    binary_data = bytearray(data)
    with open(output_name, 'wb') as result_file:
        result_file.write(binary_data)
        print(
            'bmp -> dat conversion is successful. Data from [%s] is added to [%s]' % (
                bmp_name, output_name))

    # recursive inserting
    if postfix == 'main' and len(sub_files) > 0:
        for file in sub_files:
            insert_bmp_into_dat(file[0], file[4])  # filename.dat + postfix
    return True


def all_dat_to_bmp():
    """
    Scans directory in the same folder as the script.
    If finds *.dat files - applies converting function to them.
    """
    directory = os.listdir(os.curdir)

    known = get_known_files()

    if not known:
        print('Unable start conversion, list of known files is not found.')
        return

    known = set([each[0].lower() for each in known])

    i = 0
    for file in directory:
        if os.path.isfile(file):
            if file[-4:].lower() == '.dat' and file in known:
                i += 1
                print('[%3s]' % i, end=' ')
                dat_to_bmp(file)

    if i > 0:
        print('Conversion complete. %d files converted.' % i)


def extract_piece_of_dat(filename, position):
    """
    Extracts section of dat file located after [position].
    Might be useful to cut off header of the file.

    :param filename: specified dat file, like menus.dat'
    :param position: number of exact byte to start copying
    :return: True if nothing interrupted the process. False if there are any errors.
    """

    if not os.path.isfile(filename):
        print('Unable to start conversion, [%s] is not found.' % filename)
        return False

    with open(filename, 'rb') as file:
        raw_data = file.read()

    data = []
    i = 0
    # skipping header of the file
    for chunk in raw_data:
        if i >= position:
            data.append(int(chunk))
        else:
            i += 1

    output_name = 'new_' + filename
    # do not overwrite!
    if os.path.isfile(output_name):
        add = 1
        while os.path.isfile(output_name):
            output_name = 'new_' + filename + '(' + str(add).rjust(2,
                                                                   '0') + ').dat'
            add += 1

    with open(output_name, 'wb') as result_file:
        binary_data = bytearray(data)
        result_file.write(binary_data)

    print(
        'dat -> dat extraction is successful. [%s] is converted and saved as [%s]' % (
            filename, output_name))
    return True


if __name__ == '__main__':
    args = sys.argv[1:]

    if len(args) != 2:
        print('You need to specify mode and target to run this script')
        print()
        print('Possible examples:')
        print('python images.py extract *')
        print('python images.py extract somefile.dat')
        print('python images.py insert somefile.dat')
        sys.exit()

    mode, target, *_ = args
    mode = mode.lower()

    if mode == 'extract':
        dat_to_bmp(target)

    elif mode == 'insert':
        insert_bmp_into_dat(target)

    else:
        print(f'Arguments are not recognised: {args}')
