# Superconducting CPW Participation Ratio & QTLS Analysis

This repository provides tools for simulating and calculating the interface participation ratios ($p_i$) and Two-Level System (TLS) limited quality factors ($Q_{TLS}$) of superconducting Coplanar Waveguide (CPW) resonators. 

It is designed to process output data from 2D electrostatic finite element simulations (e.g., COMSOL Multiphysics) and apply rigorous dielectric scaling models to predict device performance.

## Overview
Interface dielectric defects at the Metal-Air (MA), Metal-Substrate (MS), and Substrate-Air (SA) boundaries are the primary source of microwave loss in state-of-the-art superconducting resonators. This toolkit allows you to:
1. **Extract Energy Fractions:** Use the provided COMSOL template to simulate the electric field energy distribution ($U_i$) across different geometric regions of a trenched or un-trenched CPW.
2. **Calculate True Participation Ratios ($p_i$):** Correctly scale the simulated capital $P_i$ ($U_i/U_{tot}$) based on target interface thicknesses and relative permittivities ($\epsilon_r$).
3. **Predict $Q_{TLS}$:** Apply loss tangents ($\tan \delta_i$) to calculate the expected TLS-limited quality factor in an interactive GUI.

## Repository Contents

### 1. `Participation_Ratio_Calculations.py`
A Python/Tkinter GUI application that imports CSV data from COMSOL, calculates $p_i$ for each interface, plots loss contributions, and features:
* **Auto-Calculate Mode:** Automatically updates plots and data tables as you type new material parameters.
* **Save/Load Profiles:** Save your standard interface stack variables ($\epsilon$ and $\tan \delta$) to a local JSON file to easily switch between material types (e.g., Nb vs. Ta).
* **Live Data Table:** Instantly inspect actual small $p_i$ values inside the GUI without exporting.

### 2. `2D_cross_section.mph` (COMSOL Electrostatics File)
This COMSOL Multiphysics file contains the 2D cross-section of a CPW structure. To minimize computation time, it exploits device symmetry by simulating only half of the center trace and one ground plane.
* **Geometry Variables:** Parametrically defined so you can easily sweep the center trace width (`w`), gap to ground (`gap`), trench depth (`d`), and metal thickness.
* **Physics:** Sets up the basic electrostatics for the CPW, incorporating thin (e.g., 10 nm) proxy boundary layers to represent the MA, MS, and SA interfaces.
* **Integration Variables:** Automatically configured to integrate the stored electric field energy ($U_i$) inside each interface proxy layer, as well as the bulk Silicon and the total simulation bounds.

### 3. `Example_simulation.csv`
A sample exported result file generated from running a parametric sweep (e.g., sweeping the `gap` variable) in the COMSOL file. It serves as the standard input format for the Python GUI. It contains:
* The independent geometric variable (e.g., `gap`).
* The total simulated energy (`U_total`).
* The absolute energies (`U_MA`, `U_MS`, etc.) and the resulting geometric energy fractions (`P_MA`, `P_MS`, etc.) for each region.

## The Physics Model
The calculations in this toolkit distinguish between the *simulated energy fraction* ($P_i$) and the *actual interface participation ratio* ($p_i$). 

Following the models established by Martinis/Wenner and Calusine et al., the code applies geometric scaling based on whether the electric field is perpendicular ($\perp$) or parallel ($||$) to the interface:
* **Perpendicular (MA, MS):** $p_{i, \perp} = P_i \cdot \frac{t_i}{t_{nom}} \cdot \frac{\epsilon_{nom}}{\epsilon_i}$
* **Parallel (SA):** $p_{i, ||} = P_i \cdot \frac{t_i}{t_{nom}} \cdot \frac{\epsilon_i}{\epsilon_{nom}}$

The total TLS loss is then computed as:
$$\frac{1}{Q_{TLS}} = p_{MA}\tan\delta_{MA} + p_{MS}\tan\delta_{MS} + p_{SA}\tan\delta_{SA} + p_{Si}\tan\delta_{Si}$$

## Usage
1. Open `2D_cross_section.mph` and run the parametric sweep over your desired geometries.
2. Export the volume integrals to a `.csv` file matching the format of `Example_simulation.csv`.
3. Run `python Participation_Ratio_Calculations.py`.
4. Load the `.csv` file and select your independent variable (e.g., Gap in $\mu m$).
5. Input your specific material parameters (thicknesses, $\epsilon_r$, and $\tan \delta$) to analyze real-time loss contributions.

## References
* **Surface Loss Simulations:** Wenner, J., et al. *Applied Physics Letters* 99.11 (2011): 113513. [DOI: 10.1063/1.3637047](https://pubs.aip.org/aip/apl/article-abstract/99/11/113513/923377)
* **Trenched SCPW Interface Mitigation:** Calusine, G., et al. *Applied Physics Letters* 112.6 (2018): 062601. [DOI: 10.1063/1.5006888](https://pubs.aip.org/aip/apl/article/112/6/062601/35936)