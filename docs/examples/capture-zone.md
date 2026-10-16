# Example: the capture zone of a pumping well

`examples/capture_zone.py` builds a 21 x 21 single-layer model (100 m cells,
K = 10 m/d, 10 m thick) with fixed heads of 30 m on the west edge and 20 m on
the east, and a well pumping 200 m3/d in the middle. Particles are released from
the centre of every cell on column 3, upstream of the well, and tracked forward
with MODPATH 7. Those that end in the well are inside its capture zone.

For steady uniform flow the capture zone far upstream has the width
`W = Q / (K * b * i)` = 200 / (10 * 10 * 0.005) = **400 m**.

Run it (needs the `mf6` and `mp7` binaries):

    uv run python examples/capture_zone.py

Output of a real run:

    == flow run
       success: True
       convergence: converged
    == water balance
       percent_discrepancy: 0.037296
       balanced: True
    == capture zone
       released: 21
       captured: 3
       captured_width_m: 300.0
       analytical_width_m: 400.0

Three of the 21 particles reach the well, a captured band of 300 m against the
analytical 400 m. Because particles start 100 m apart, the count can only agree
with `W / spacing` to within one particle, and the finite domain and the
cell-averaged well head also shift it slightly; the test accepts a difference of
one particle. The pathline plot (`plot_modpath_pathlines`) shows the three
captured lines ending at the well and the rest passing around it.
