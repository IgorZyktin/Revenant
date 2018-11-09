# Revenant
<p>Set of tools created to interact with Revenant content (RPG game by Cinematix studios, released in 1999 by the publisher Eidos Interactive)</p>
<br>
<p><strong>** MAP processing (dat and bmp files related to game maps).</strong></p>
<p><strong>Example 1: save automaps from given directory</strong></p>
<p>When you play Revenant, that small map in lower right corner of the screen is called automap. Automap is built out of
small *.bmp files located in module file. This script is stitching that small files into a single big image.</p>
<pre><code>data = scan_for_files('automaps', 'bmp')
print('Found data in "automaps" folder:', data)
stitch_automaps(data)
</code></pre>
<p><strong>Example 2: save all automaps from all nearby directories</strong></p>
<pre><code>save_all_automaps()
</code></pre>
<p><strong>Example 3: save heatmaps from given directory</strong></p>
<p>Whole game world in Revenant is built like a mesh out of small *.dat files. Each map file contains data about any objects
located there. When you play the game, all changes in game world (all differences from original map *.dat files). are saved in your
savegame directory. Unfortunately, original map files were created in proprietary format. Therefore heatmaps are the best we could get
out of them. Heatmap is built based on size of the files. Bigger the file, brighter the tile it represents.</p>
<pre><code>data = scan_for_files('map', 'dat')
print('Found data in "map" folder:', data)
stitch_heatmaps(data)
</code></pre>
<p><strong>Example 4: save all heatmaps from all nearby directories</strong></p>
<pre><code>save_all_heatmaps()
</code></pre>
<p><strong>Example 5: write player's progress over default game map</strong></p>
<p>Same as heat maps, but for specific player. At first this script creates heatmaps for default game world (without changes by player).
Since all saves in Revenant are built upon creating lots of specific *.dat files, that represent players' actions , it is possible to
show that difference graphically. Progress heatmap will show you where's the most difference in file sizes. And that difference
represents already visited places in game world.</p>
<pre><code>show_progress_on_map()
</code></pre>

<br>
<p><strong>DAT processing (dat files related to the game menu).</strong></p>
<p>Game uses strange color encoding system, similar to r5g5b5a1 (five bits for color and on for alpha channel). But encoding bits are shifted for some reason.
Real ingame color format is: [G3][G4][G5][B1][B2][B3][B4][B5][A][R1][R2][R3][R4][R5][G1][G2]</p>
<p>For example:
red   0000000001111100
green 1110000000000011
blue  0001111100000000</p>
<p>Each file also contains header with technical information. Contents of the header are unknown. For example, loadgamealpha.dat has 616 560 bytes. We know that it contains 640x480 pixels image, with two bytes for pixel. Therefore it has 640 x 480 x 2 bytes = 307 200 x 2 = 614 400 bytes. File size is 616 560 bytes, therefore header is 616 560 - 614 400 = 2160 bytes. If you start to read from 2160 byte, you get colors of the pixels</p>
<p>Note that this counts only for dat files in "resources" directory! Game uses two completely different types of encoding for *.dat files. Files in 'resources' folder are related to 2D images. Files in 'maps' folder are related to game levels and have much more complicated structure.</p>
<p><strong>Example 6: save all dat files in current directory as bmp files (including subfiles)</strong></p>
<pre><code>all_dat_to_bmp()
</code></pre>
<p><strong>Example 7: save single dat file as bmp file</strong></p>
<pre><code>dat_to_bmp('menus.dat')
</code></pre>
<p><strong>Example 8: merge existing bmp files into existing dat file.</strong></p>
<pre><code>insert_bmp_into_dat('menus.dat')
</code></pre>
<p>If it's a single image, you need somefile_main.bmp. If dat file requires more than one file, then you need to create sequence. Simplest way to do that - extract with dat_to_bmp func, change files you need, and repack it back.</p>
