# Revenant

Set of tools created to interact with Revenant content (RPG game by Cinematix studios, released in
1999 by the publisher Eidos Interactive).

## Before you start

All scripts in this repository are supposed to be launched using Python 3.

Basic setup for the start using command line:

```shell
pip install uv
git clone git@github.com:IgorZyktin/Revenant.git
cd Revenant
uv sync
```

## Automap processing

When you play Revenant, that small map in lower right corner of the screen is called an automap.
Automap is built out of small *.bmp files located in the module file.

How to stitch them:

```shell
uv run python automaps.py --source-folder C:\Games\Revenant\Modules\Ahkuilon\Automaps
```

You may need to unpack your module first, for example "Ahkuilon.rvm". It is just a zip file, you can
rename it to "Ahkuilon.zip" and then unpack.

Already processed automaps:

* [Outdoor](./automaps/automaps_00.png)
* [Castle](./automaps/automaps_02.png)
* [Ancient tower](./automaps/automaps_03.png)
* [Arakna Island](./automaps/automaps_04.png)
* [City](./automaps/automaps_05.png)
* [Caves 1](./automaps/automaps_30.png)
* [Caves 2](./automaps/automaps_31.png)
* [Caves 3](./automaps/automaps_32.png)
* [Caves 4](./automaps/automaps_36.png)
* [Altar](./automaps/automaps_37.png)
* [Caves 5](./automaps/automaps_39.png)
* [Catacombs 1](./automaps/automaps_41.png)
* [Catacombs 2](./automaps/automaps_44.png)
* [Catacombs 3](./automaps/automaps_45.png)
* [Catacombs 4](./automaps/automaps_46.png)
* [Catacombs 5](./automaps/automaps_48.png)
* [Catacombs 6](./automaps/automaps_49.png)
* [Other world 1](./automaps/automaps_51.png)
* [Other world 2](./automaps/automaps_52.png)
* [Other world 3](./automaps/automaps_53.png)
* [Other world 4](./automaps/automaps_54.png)
* [Other world 5](./automaps/automaps_55.png)
* [Other world 6](./automaps/automaps_56.png)
* [Other world 7](./automaps/automaps_57.png)
* [Other world 8](./automaps/automaps_58.png)
* [Demo outdoor](./automaps/demo_10.png)
* [Demo underground](./automaps/demo_30.png)
