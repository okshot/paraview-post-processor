# paraview-post-processor
A CLI interface to interactively extract and plot data from ASPECT output files using Paraview

# Setup
- Install the requirements with
  ```bash
  pip install -r requirements.txt
- Clone the repo with
  ```bash
  git clone https://github.com/okshot/paraview-post-processor
  cd paraview-post-processor
- Run with
  ```bash
  python3 ./main.py
- On first run provide the path to pvpython available in package contents of Paraview and it will save that as default eg.
  ```bash
  ~/Downloads/post-process via  v3.9.17                                                                                                        
  $ ./main.py

  ╔══════════════════════════════════════╗
  ║     ASPECT Post-Processor v1.0       ║
  ╚══════════════════════════════════════╝


  ── First-Time Setup ──
  This tool requires pvpython (ParaView's Python interpreter)
  for extracting data from ASPECT output files.

  ⚠ Could not auto-detect pvpython
  Enter full path to pvpython: /Applications/ParaView-6.1.1.app/Contents/bin/pvpython
  ✓ pvpython path verified
  ✓ Configuration saved to /Users/akshat/Downloads/post-process/defaults.toml

# Using
- Run with
  ```bash
  python3 ./main.py
- Enter path to output you want to plot.
- It will read the metadata and provide with you all the variables that can be plotted and how you can plot them.
- The metadata is saved for faster plotting in future.
  ```bash
  ── Input File ──
  Path to solution.pvd or output directory: /Users/akshat/Documents/thesis/aspect_tests/output_test_106

  Loading cached metadata... done
  ✓ Loaded: /Users/akshat/Documents/thesis/aspect_tests/output_test_106/solution.pvd

  Timesteps  : 1 (0 → 0 yrs)
  Scalars    : p, T, density_field, crust_field, density, thermal_expansivity, specific_heat, viscosity, strain_rate, principal_stress_1, principal_stress_2, principal_stress_3, depth, dynamic_topography
  Vectors    : velocity, shear_stress, principal_stress_direction_1, principal_stress_direction_2, principal_stress_direction_3, maximum_horizontal_compressive_stress, stress
  Longitude  : 65.5° – 114.5°
  Latitude   : 10.5° – 44.5°
  Depth      : -0 – 400 km


  ── Main Menu ──
  [1] Cross-section slice  (2D map / cross-section)
  [2] Depth-averaged map   (average between two depths)
  [3] Re-plot from saved CSV
  [4] Change timestep      [current: t=0 (0 yrs)]
  [5] Switch to different run
  [6] Edit defaults
  [q] Quit

Edit the defaults.toml file to change defaults presented while plotting.  
To reset defaults, delete the default.toml file created.

# PyGMT not working
- Please follow the official guide at https://www.pygmt.org/latest/ to install PyGMT if you have issues with that.





Written and debugged with help of Claude Opus 4.6
