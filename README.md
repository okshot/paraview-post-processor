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
  ./main.py
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
  ./main.py
- Enter path to output you want to plot.
- It will read the metadata and provide with you all the variables that can be plotted and how you can plot them.
- The metadata is saved for faster plotting in future.

Edit the defaults.toml file to change defaults presented while plotting.  
To reset defaults, delete the default.toml file created.

# PyGMT not working
- Please follow the official guide at https://www.pygmt.org/latest/ to install PyGMT if you have issues with that.
