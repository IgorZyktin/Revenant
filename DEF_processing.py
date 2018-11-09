"""
    This module is created to interact with DEF files.

    Revenant has 4 major DEF files:
        char.def    (parameters for player and NPC's)
        class.def   (parameters for classes of all objects in game)
        weapon.def  (parameters for weapons)
        armor.def   (parameters for armor)

    It's not the full list. There are a lot of scenarios
    written in DEF files, subtitles and other stuff.

    This script allows you to interact with weapons.def
"""
import xlwt
import xlrd
import os


def strip_keyword(line):
    """
    Searching keywords in line. Keywords are usually like BEGIN, WEAPON, END etc.

    :param line: input text
    :return: keyword if found or False
    """

    define = False
    text = line.strip()
    text = text.replace('\n', '')
    text = text.replace('\t', '')
    text = text.replace('"', '')

    if len(text) < 2:
        # it's empty
        return False

    if len(text) > 0 and text[0] == '/':
        # it's a comment
        return False

    if len(text) > 0 and text[0] == '#':
        # it's a defined value, written like #define SOME 18
        define = True
        text = text[8:]
        # note that we're not saving comments
        find = text.find('/')
        if find:
            text = text[0:find]

    word = ''
    for char in text:
        # note that SOME_TEXT also might be a keyword
        if char == '_' or char.isalpha():
            word = word + char
        else:
            # supposedly we've got a space here
            break

    rest = text[len(word):]
    rest = rest.strip()

    return word, rest, define


def weapons_from_def(fname):
    """
    Stripping data from weapon.def file.

    :param fname: input file (usually weapon.def)
    :return: True if nothing interrupted the process. False if there are any errors.
    """

    if not os.path.isfile(fname):
        print('Extraction from *.def is not possible, no such file as "%s"' % fname)
        return False

    with open(fname, 'r') as file:
        lines = file.readlines()

    current = ''
    weapons = {}
    defines = []

    for line in lines:
        keyword = strip_keyword(line)

        if not keyword:
            continue

        if keyword[2] == 1:
            # saving defines
            defines.append([keyword[0], keyword[1]])
            continue

        if keyword[0] == 'WEAPON':
            current = keyword[1]
            weapons[current] = []
            continue

        if keyword[0] == 'END':
            current = ''
            continue

        if keyword[0] == 'BASICMODS':
            params = keyword[1]
            params = params.split(',')
            weapons[current] = params
            continue

        if keyword[0] == 'DESCRIPTION':
            weapons[current].append(keyword[1])
            continue

    return weapons, defines


def weapons_to_def(weapons):
    """
    Saving weapons to "weapon.def" file

    :param weapons: input dictionary with weapons data
    :return: True if nothing interrupted the process. False if there are any errors.
    """

    if not weapons:
        print('Unable to save "weapon.def", given data is not correct')
        return False

    fname = 'weapon.def'

    # do not overwrite!
    add = 0
    while os.path.isfile(fname):
        fname = 'weapon_' + str(add) + '.def'
        add += 1

    with open(fname, 'w') as file:
        file.write('// Revenant - Copyright 1999 Cinematix Studios, Inc.\n')
        file.write('// ********** Revenant WEAPON.DEF File ************ \n')
        file.write('\n')

        for weapon in weapons:
            file.write('WEAPON "' + str(weapon) + '"\n')
            file.write('BEGIN\n')
            file.write('\tBASICMODS\t')

            for i in range(len(weapons[weapon])):
                if 0 <= i < 7:
                    file.write(weapons[weapon][i] + ',')
                elif i == 7:
                    file.write(weapons[weapon][i] + '\n')

            file.write('\tDESCRIPTION\t')
            file.write(str(weapons[weapon][-1]) + '\n')
            file.write('END\n')
            file.write('\n')

        file.close()
        print('File [' + fname + '] successfully saved.')
    return True


def explain_weapons(weapons_dict):
    """
    Make a table with all parameters explained.

    :param weapons_dict: input dictionary with weapons data
    :return: None
    """
    col_width = 15
    spacers = 175

    print('Found {} weapons'.format(len(weapons_dict)))
    print('-' * spacers)
    print('|           Weapon            |', end='')
    print('eqslot'.center(col_width) + '|', end='')
    print('type'.center(col_width) + '|', end='')
    print('damage'.center(col_width) + '|', end='')
    print('combining'.center(col_width) + '|', end='')
    print('poison'.center(col_width) + '|', end='')
    print('value'.center(col_width) + '|', end='')
    print('damagemod'.center(col_width) + '|', end='')
    print('minstrenght'.center(col_width) + '|', end='')
    print('DESCRIPTION'.center(col_width) + '|')
    print('-' * spacers)

    i = 1
    for weapon in weapons_dict:
        print('|' + str(i).rjust(2) + '.', end='')
        print(weapon.rjust(25)+' |', end='')
        for x in range(0, 9):
            print(weapons_dict[weapon][x].center(col_width) + '|', end='')
        print('')
        i += 1
    print('-' * spacers)


def weapons_from_xls(fname):
    """
    Stripping data from weapon.xls file.

    :param fname: input file (usually weapon.xls)
    :return: True if nothing interrupted the process. False if there are any errors.
    """

    if not os.path.isfile(fname):
        print('Extraction form *.xls is not possible, no such file as "%s"' % fname)
        return False

    book = xlrd.open_workbook(fname, formatting_info=False)
    sheet = book.sheet_by_index(0)

    weapons_dict = {}

    for row in range(1, sheet.nrows):
        weapon = sheet.cell_value(row, 1)
        weapons_dict[weapon] = []

        for col in range(2, 10):
            parameters = str(int(sheet.cell_value(row, col)))
            weapons_dict[weapon].append(parameters)

        description = sheet.cell_value(row, sheet.ncols-1)
        weapons_dict[weapon].append(description)

    return weapons_dict


def weapons_to_xls(fname, weapons):
    """
    Saving weapons to "weapon.def" file

    :param fname: output file
    :param weapons: input dictionary with weapons data
    :return: True if nothing interrupted the process. False if there are any errors.
    """

    if not weapons:
        print('Unable to save as "%s", given data in not correct' % fname)
        return False

    book = xlwt.Workbook('utf8')
    font_r = xlwt.easyxf('font: height 240,name Arial,colour_index black, bold off,\
        italic off; align: horz center, vert top, horiz right;\
        pattern: pattern solid, fore_colour white;')
    font_c = xlwt.easyxf('font: height 240,name Arial,colour_index black, bold off,\
        italic off; align: horz center, vert center, horiz center;\
        pattern: pattern solid, fore_colour white;')

    sheet = book.add_sheet('weapons')

    # Line, Column, Cell, Text, Font
    sheet.col(0).width = 1000
    sheet.col(0).border = ""
    sheet.write(0, 0, 'N', font_c)

    sheet.col(1).width = 7000
    sheet.write(0, 1, 'Weapon', font_r)

    sheet.col(2).width = 2000
    sheet.write(0, 2, 'eqslot', font_c)

    sheet.col(3).width = 2000
    sheet.write(0, 3, 'type', font_c)

    sheet.col(4).width = 3000
    sheet.write(0, 4, 'damage', font_c)

    sheet.col(5).width = 3000
    sheet.write(0, 5, 'combining', font_c)

    sheet.col(6).width = 2000
    sheet.write(0, 6, 'poison', font_c)

    sheet.col(7).width = 3500
    sheet.write(0, 7, 'value', font_c)

    sheet.col(8).width = 3500
    sheet.write(0, 8, 'damagemod', font_c)

    sheet.col(9).width = 3500
    sheet.write(0, 9, 'minstrenght', font_c)

    sheet.col(10).width = 4000
    sheet.write(0, 10, 'DESCRIPTION', font_c)

    i = 1
    for weapon in weapons:
        sheet.write(i, 0, i, font_c)
        sheet.write(i, 1, weapon, font_r)
        j = 2
        for par in weapons[weapon]:
            if par.isdigit():
                sheet.write(i, j, int(par), font_c)
            else:
                sheet.write(i, j, par, font_c)
            j += 1
        i += 1

    # do not overwrite!
    i = 0
    while os.path.isfile(fname):
        fname = 'weapon_' + str(i) + '.xls'
        i += 1
    book.save(fname)
    print('File [' + fname + '] successfully saved.')
    return True


def weapon_def_to_xls(fname):
    weapons_data = weapons_from_def(fname)
    # weapon.def does not have #define section
    weapons_to_xls(fname, weapons_data[0])

