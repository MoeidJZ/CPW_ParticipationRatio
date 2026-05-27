import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D


# ─────────────────────────────────────────────────────────────────────────────
#  Tooltip helper
# ─────────────────────────────────────────────────────────────────────────────
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tip_window:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, background="#ffffe0", relief="solid",
                 borderwidth=1, font=("Consolas", 9)).pack()

    def hide(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


# ─────────────────────────────────────────────────────────────────────────────
#  Main application
# ─────────────────────────────────────────────────────────────────────────────
class TLSAnalysisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TLS Analysis – Superconducting Resonators")
        self.root.geometry("1280x840")

        # Data storage
        self.df = None
        # ── x-axis variable (chosen by user after file load) ──────────────
        # xvar_col   : column name in the CSV
        # xvar_values: numpy array of values (already converted to display unit)
        # xvar_label : axis label string, e.g. "gap (μm)" or "angle (°)"
        self.xvar_col    = None
        self.xvar_values = None
        self.xvar_label  = None
        # keep gap_values as an alias so the rest of the code stays readable
        self.gap_values  = None   # points to xvar_values after selection
        self.P_MA = self.P_MS = self.P_SA = self.P_Si = None
        # Sub-region capital-P (U_sub / U_total) for sidewall fraction plots
        self.P_MA_SW  = None   # (MA Res SW + MA GP SW) / U_total
        self.P_MA_top = None   # (MA GP_top + MA Res-top) / U_total
        self.P_SA_SW  = None   # (SA GP-SW + SA Res SW) / U_total
        self.P_SA_gap = None   # SA Gap / U_total
        self.has_subregion_data = False
        self.params = {}
        self.current_participation_fig = None
        self.current_qtls_data = None
        self.current_sw_fig = None

        # ── main container ──────────────────────────────────────────────────
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.create_file_selection()

    # =========================================================================
    #  FILE SELECTION
    # =========================================================================
    def create_file_selection(self):
        for w in self.main_frame.winfo_children():
            w.destroy()

        ttk.Label(self.main_frame,
                  text="Superconducting Resonator TLS Analysis",
                  font=("Arial", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=20)

        ttk.Button(self.main_frame, text="Browse CSV File",
                   command=self.browse_file, width=30
                   ).grid(row=1, column=0, columnspan=2, pady=10)

        self.file_label = ttk.Label(self.main_frame,
                                    text="No file selected", foreground="gray")
        self.file_label.grid(row=2, column=0, columnspan=2, pady=5)

        # ── Formula reference button always visible ─────────────────────────
        ttk.Button(self.main_frame, text="📐  View Formulas",
                   command=self.show_formula_window
                   ).grid(row=3, column=0, columnspan=2, pady=10)

    def browse_file(self):
        fn = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not fn:
            return
        try:
            self.df = pd.read_csv(fn)
            required = ["U_MA", "U_MS", "U_SA", "U_Si", "U_total"]
            missing = [c for c in required if c not in self.df.columns]
            if missing:
                messagebox.showerror("Error",
                                     f"Missing columns: {', '.join(missing)}")
                return
            self.file_label.config(
                text=f"Loaded: {fn.split('/')[-1]}", foreground="green")
            # Ask user to choose x-axis variable before drawing anything
            self.open_xvar_dialog()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file: {e}")

    # =========================================================================
    #  X-AXIS VARIABLE SELECTION DIALOG
    # =========================================================================
    # Allowed variable types and their unit options.
    # COMSOL exports length in metres by default; angles in radians.
    # The user picks the physical type first, then the display unit.
    # A conversion factor is applied so stored values are already in display unit.

    _XVAR_TYPES = {
        "Length"  : {
            "nm": 1e0,   # CSV already in display unit
            "μm": 1e0,   # CSV already in display unit
        },
        "Angle"   : {
            "rad": 1.0,
            "deg": 180.0 / np.pi,
        },
        "Epsilon_r (dimensionless)": {
            "(none)": 1.0,
        },
    }

    def open_xvar_dialog(self):
        """
        Modal-style Toplevel that lets the user pick:
          • which CSV column is the x-axis
          • what physical type it is (Length / Angle / Epsilon_r)
          • which display unit to use
        On confirm it calls _confirm_xvar() which sets self.xvar_* and
        proceeds to calculate_participation_ratios / show_participation_plots.
        """
        # candidate columns: numeric, non-energy columns
        energy_cols = {"U_MA", "U_MS", "U_SA", "U_Si", "U_total",
                       "P_MA", "P_MS", "P_SA", "P_si",
                       "MA GP_top", "MA Res-top", "MA Res SW", "MA GP SW",
                       "MS GP", "MS res",
                       "SA GP-SW", "SA Gap", "SA Res SW",
                       "P_MA_sidewall"}
        numeric_cols = [c for c in self.df.columns
                        if pd.api.types.is_numeric_dtype(self.df[c])
                        and c not in energy_cols
                        and not c.startswith("Unnamed")]
        if not numeric_cols:
            messagebox.showerror("Error",
                "No suitable numeric column found to use as x-axis.\n"
                "The CSV must contain at least one non-energy numeric column.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Select X-Axis Variable")
        dlg.geometry("420x320")
        dlg.resizable(False, False)
        dlg.grab_set()   # modal

        ttk.Label(dlg, text="X-Axis Variable Setup",
                  font=("Arial", 13, "bold")).pack(pady=(14, 6))

        frm = ttk.Frame(dlg, padding="12 4")
        frm.pack(fill=tk.X)

        # ── column picker ────────────────────────────────────────────────
        ttk.Label(frm, text="CSV column:").grid(
            row=0, column=0, sticky=tk.W, padx=6, pady=4)
        col_var = tk.StringVar(value=numeric_cols[0])
        col_cb  = ttk.Combobox(frm, textvariable=col_var,
                               values=numeric_cols, state="readonly", width=22)
        col_cb.grid(row=0, column=1, padx=6, pady=4)

        # ── physical type ────────────────────────────────────────────────
        ttk.Label(frm, text="Physical type:").grid(
            row=1, column=0, sticky=tk.W, padx=6, pady=4)
        type_var = tk.StringVar(value="Length")
        type_cb  = ttk.Combobox(frm, textvariable=type_var,
                                values=list(self._XVAR_TYPES.keys()),
                                state="readonly", width=22)
        type_cb.grid(row=1, column=1, padx=6, pady=4)

        # ── unit ─────────────────────────────────────────────────────────
        ttk.Label(frm, text="Display unit:").grid(
            row=2, column=0, sticky=tk.W, padx=6, pady=4)
        unit_var = tk.StringVar(value="μm")
        unit_cb  = ttk.Combobox(frm, textvariable=unit_var,
                                state="readonly", width=22)
        unit_cb.grid(row=2, column=1, padx=6, pady=4)

        def _detect_type(col_name):
            """Guess physical type from column name keywords."""
            low = col_name.lower()
            if any(k in low for k in ("angle", "rad", "deg", "phi", "theta")):
                return "Angle"
            if any(k in low for k in ("epsilon", "eps", "permittiv")):
                return "Epsilon_r (dimensionless)"
            return "Length"

        # ── preview label (defined before callbacks that reference it) ───
        preview_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=preview_var,
                  font=("Consolas", 9), foreground="#444"
                  ).grid(row=3, column=0, columnspan=2, pady=6)

        def _update_preview(*_):
            col  = col_var.get()
            typ  = type_var.get()
            unit = unit_var.get()
            if col in self.df.columns and unit in self._XVAR_TYPES.get(typ, {}):
                factor = self._XVAR_TYPES[typ][unit]
                vals   = self.df[col].values * factor
                preview_var.set(
                    f"Preview — first 5 values in {unit}:  "
                    + "  ".join(f"{v:.4g}" for v in vals[:5]))

        def _update_units(*_):
            units = list(self._XVAR_TYPES[type_var.get()].keys())
            unit_cb["values"] = units
            unit_var.set(units[0])

        def _on_col_change(*_):
            """Auto-detect type from column name, refresh units and preview."""
            type_var.set(_detect_type(col_var.get()))
            _update_units()
            _update_preview()

        # bindings — each widget triggers only its natural handler
        col_cb.bind( "<<ComboboxSelected>>", _on_col_change)
        type_cb.bind("<<ComboboxSelected>>", lambda e: (_update_units(), _update_preview()))
        unit_cb.bind("<<ComboboxSelected>>", _update_preview)

        # initialise for the first column in the list
        _on_col_change()

        # ── buttons ──────────────────────────────────────────────────────
        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=12)
        ttk.Button(btn_row, text="✔  Confirm",
                   command=lambda: self._confirm_xvar(
                       dlg, col_var.get(), type_var.get(), unit_var.get())
                   ).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="✘  Cancel",
                   command=dlg.destroy).pack(side=tk.LEFT, padx=8)

    def _confirm_xvar(self, dlg, col, typ, unit):
        factor = self._XVAR_TYPES[typ][unit]
        raw    = self.df[col].values
        self.xvar_col    = col
        self.xvar_values = raw * factor
        # Label: "gap (μm)"  /  "angle (°)"  /  "εᵣ"
        if unit == "(none)":
            self.xvar_label = col
        else:
            self.xvar_label = f"{col} ({unit})"
        self.gap_values = self.xvar_values   # alias used throughout
        dlg.destroy()
        self.calculate_participation_ratios()
        self.show_participation_plots()


    def calculate_participation_ratios(self):
        # xvar_values / gap_values already set by _confirm_xvar
        U_tot = self.df["U_total"].values

        # ── Total capital-P per interface ────────────────────────────────
        self.P_MA = self.df["U_MA"].values / U_tot
        self.P_MS = self.df["U_MS"].values / U_tot
        self.P_SA = self.df["U_SA"].values / U_tot
        self.P_Si = self.df["U_Si"].values / U_tot

        # ── Sub-region capital-P (sidewall vs top/flat) ───────────────────
        cols = self.df.columns.tolist()
        ma_sw_cols  = [c for c in ["MA Res SW", "MA GP SW"]   if c in cols]
        ma_top_cols = [c for c in ["MA GP_top", "MA Res-top"] if c in cols]
        sa_sw_cols  = [c for c in ["SA GP-SW",  "SA Res SW"]  if c in cols]
        sa_gap_cols = [c for c in ["SA Gap"]                  if c in cols]

        self.has_subregion_data = bool(ma_sw_cols or sa_sw_cols)
        if self.has_subregion_data:
            self.P_MA_SW  = (self.df[ma_sw_cols].sum(axis=1).values  / U_tot
                             if ma_sw_cols  else np.zeros_like(U_tot))
            self.P_MA_top = (self.df[ma_top_cols].sum(axis=1).values / U_tot
                             if ma_top_cols else self.P_MA - self.P_MA_SW)
            self.P_SA_SW  = (self.df[sa_sw_cols].sum(axis=1).values  / U_tot
                             if sa_sw_cols  else np.zeros_like(U_tot))
            self.P_SA_gap = (self.df[sa_gap_cols].sum(axis=1).values / U_tot
                             if sa_gap_cols else self.P_SA - self.P_SA_SW)

    def show_participation_plots(self):
        for w in self.main_frame.winfo_children():
            w.destroy()

        self.main_frame.columnconfigure(0, weight=2)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(0, weight=1)

        plot_frame = ttk.Frame(self.main_frame)
        plot_frame.grid(row=0, column=0, sticky="nsew", padx=5)

        param_frame = ttk.Frame(self.main_frame)
        param_frame.grid(row=0, column=1, sticky="nsew", padx=5)

        # ── figure ──────────────────────────────────────────────────────────
        fig = Figure(figsize=(8, 6))
        self.current_participation_fig = fig

        ax1 = fig.add_subplot(111)
        ax1.set_yscale("log")
        ax1.plot(self.gap_values, self.P_MA, "o-", label="P_MA",
                 lw=2, ms=6, color="C0")
        ax1.plot(self.gap_values, self.P_MS, "s-", label="P_MS",
                 lw=2, ms=6, color="C1")
        ax1.plot(self.gap_values, self.P_SA, "^-", label="P_SA",
                 lw=2, ms=6, color="C2")
        ax1.set_xlabel(self.xvar_label, fontsize=12)
        ax1.set_ylabel("Participation Ratio – MA, MS, SA", fontsize=12)
        ax1.grid(True, alpha=0.3)

        ax2 = ax1.twinx()
        ax2.plot(self.gap_values, self.P_Si, "d-", label="P_Si",
                 lw=2, ms=6, color="C3")
        ax2.set_ylabel("Participation Ratio – Si", fontsize=12, color="C3")
        ax2.tick_params(axis="y", labelcolor="C3")

        lines1, lbl1 = ax1.get_legend_handles_labels()
        lines2, lbl2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, lbl1 + lbl2, fontsize=10, loc="best")
        ax1.set_title(f"Participation Ratios vs {self.xvar_label}",
                      fontsize=14, fontweight="bold")
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=plot_frame)
        canvas.draw()

        # ── interactive toolbar (zoom / pan / hover) ─────────────────────
        toolbar = NavigationToolbar2Tk(canvas, plot_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── coordinate display ───────────────────────────────────────────
        coord_var = tk.StringVar(value="Hover over the plot to see values")
        ttk.Label(plot_frame, textvariable=coord_var,
                  font=("Consolas", 9), foreground="#555"
                  ).pack(anchor="w", padx=4)

        def on_move(event):
            if event.inaxes is ax1:
                coord_var.set(f"{self.xvar_label} = {event.xdata:.4g}  |  "
                              f"P = {event.ydata:.4e}")
            elif event.inaxes is ax2:
                coord_var.set(f"{self.xvar_label} = {event.xdata:.4g}  |  "
                              f"P_Si = {event.ydata:.4e}")
            else:
                coord_var.set("")

        fig.canvas.mpl_connect("motion_notify_event", on_move)

        # ── save buttons ─────────────────────────────────────────────────
        btn_row = ttk.Frame(plot_frame)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="💾  Save Data (CSV)",
                   command=self.save_participation_data).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="🖼  Save Plot",
                   command=self.save_participation_plot).pack(side=tk.LEFT, padx=4)

        # ── right panel ──────────────────────────────────────────────────
        self.create_parameter_inputs(param_frame)

    # =========================================================================
    #  PARAMETER INPUT PANEL
    # =========================================================================
    def create_parameter_inputs(self, parent):
        canvas = tk.Canvas(parent)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        sf = ttk.Frame(canvas)
        sf.bind("<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)

        # bind mouse-wheel
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        row = 0

        def section(text):
            nonlocal row
            ttk.Separator(sf, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="ew", pady=8)
            row += 1
            ttk.Label(sf, text=text,
                      font=("Arial", 11, "bold")).grid(
                row=row, column=0, columnspan=2, pady=(2, 6))
            row += 1

        def field(label, default, attr):
            nonlocal row
            ttk.Label(sf, text=label).grid(
                row=row, column=0, sticky=tk.W, padx=6)
            e = ttk.Entry(sf, width=16)
            e.insert(0, default)
            e.grid(row=row, column=1, padx=6, pady=2)
            setattr(self, attr, e)
            row += 1

        ttk.Label(sf, text="Loss Parameters",
                  font=("Arial", 14, "bold")).grid(
            row=row, column=0, columnspan=2, pady=10)
        row += 1

        section("Normalization Parameters")
        field("ε_nom:", "10", "epsilon_nom_entry")
        field("t_nom (nm):", "10", "t_nom_entry")

        section("MA Interface (Metal-Air)")
        field("ε_MA:", "10", "epsilon_MA_entry")
        field("t_MA (nm):", "2", "t_MA_entry")
        field("tan(δ_MA):", "4e-3", "tand_MA_entry")

        section("MS Interface (Metal-Substrate)")
        field("ε_MS:", "3.9", "epsilon_MS_entry")
        field("t_MS (nm):", "5", "t_MS_entry")
        field("tan(δ_MS):", "7e-4", "tand_MS_entry")

        section("SA Interface (Substrate-Air)")
        field("ε_SA:", "3.9", "epsilon_SA_entry")
        field("t_SA (nm):", "2", "t_SA_entry")
        field("tan(δ_SA):", "7e-4", "tand_SA_entry")

        section("Silicon (Bulk)")
        field("tan(δ_Si):", "1.2e-7", "tand_Si_entry")

        ttk.Separator(sf, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1

        btn = ttk.Frame(sf)
        btn.grid(row=row, column=0, columnspan=2, pady=10)
        ttk.Button(btn, text="Calculate QTLS",
                   command=self.calculate_qtls).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="Parameter Sweep",
                   command=self.open_sweep_window).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="📐 Formulas",
                   command=self.show_formula_window).pack(side=tk.LEFT, padx=4)

        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # =========================================================================
    #  PARAMETERS
    # =========================================================================
    def get_parameters(self):
        try:
            self.params = {
                "epsilon_nom": float(self.epsilon_nom_entry.get()),
                "t_nom":       float(self.t_nom_entry.get()) * 1e-9,
                "epsilon_MA":  float(self.epsilon_MA_entry.get()),
                "t_MA":        float(self.t_MA_entry.get()) * 1e-9,
                "tand_MA":     float(self.tand_MA_entry.get()),
                "epsilon_MS":  float(self.epsilon_MS_entry.get()),
                "t_MS":        float(self.t_MS_entry.get()) * 1e-9,
                "tand_MS":     float(self.tand_MS_entry.get()),
                "epsilon_SA":  float(self.epsilon_SA_entry.get()),
                "t_SA":        float(self.t_SA_entry.get()) * 1e-9,
                "tand_SA":     float(self.tand_SA_entry.get()),
                "tand_Si":     float(self.tand_Si_entry.get()),
            }
            return True
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid parameter: {e}")
            return False

    # =========================================================================
    #  QTLS CALCULATION
    # =========================================================================
    def _calc_scaling(self, p):
        """
        Geometric scaling factors that convert simulated P_i (computed with
        nominal t_nom and ε_nom) into the *physical* small participation
        ratio p_i for the real interface material.  No tan(δ) included.

            ⊥ interfaces (MA, MS):  scale = (t_i / t_nom) · (ε_nom / ε_i)
            ∥ interface  (SA)    :  scale = (t_i / t_nom) · (ε_i / ε_nom)
            bulk Si              :  scale = 1
        """
        scale_MA = (p["t_MA"] / p["t_nom"]) * (p["epsilon_nom"] / p["epsilon_MA"])
        scale_MS = (p["t_MS"] / p["t_nom"]) * (p["epsilon_nom"] / p["epsilon_MS"])
        scale_SA = (p["t_SA"] / p["t_nom"]) * (p["epsilon_SA"] / p["epsilon_nom"])
        scale_Si = 1.0
        return scale_MA, scale_MS, scale_SA, scale_Si

    def _calc_x_values(self, p):
        """
        Effective loss factors x_i = scale_i · tan(δ_i).
        Used in Q_TLS via Loss_i = P_i · x_i = p_i · tan(δ_i).
        """
        s_MA, s_MS, s_SA, _ = self._calc_scaling(p)
        x_MA = s_MA * p["tand_MA"]
        x_MS = s_MS * p["tand_MS"]
        x_SA = s_SA * p["tand_SA"]
        x_Si = p["tand_Si"]
        return x_MA, x_MS, x_SA, x_Si

    def calculate_qtls(self):
        if not self.get_parameters():
            return
        x_MA, x_MS, x_SA, x_Si      = self._calc_x_values(self.params)
        s_MA, s_MS, s_SA, s_Si      = self._calc_scaling(self.params)

        # ── Small p_i: physical participation ratio (NO tan δ) ──────────
        # p_i_⊥ = P_i · (t_i/t_nom)·(ε_nom/ε_i)
        # p_i_∥ = P_i · (t_i/t_nom)·(ε_i/ε_nom)
        # p_Si  = P_Si
        p_MA = self.P_MA * s_MA
        p_MS = self.P_MS * s_MS
        p_SA = self.P_SA * s_SA
        p_Si = self.P_Si * s_Si

        # ── Loss contributions (WITH tan δ): Loss_i = p_i · tan(δ_i) ────
        Loss_MA = p_MA * self.params["tand_MA"]
        Loss_MS = p_MS * self.params["tand_MS"]
        Loss_SA = p_SA * self.params["tand_SA"]
        Loss_Si = p_Si * self.params["tand_Si"]
        QTLS = 1.0 / (Loss_MA + Loss_MS + Loss_SA + Loss_Si)

        # ── Sub-region small p_i (NO tan δ) and sub-region losses ───────
        if self.has_subregion_data:
            p_MA_SW  = self.P_MA_SW  * s_MA
            p_MA_top = self.P_MA_top * s_MA
            p_SA_SW  = self.P_SA_SW  * s_SA
            p_SA_gap = self.P_SA_gap * s_SA
            Loss_MA_SW  = p_MA_SW  * self.params["tand_MA"]
            Loss_MA_top = p_MA_top * self.params["tand_MA"]
            Loss_SA_SW  = p_SA_SW  * self.params["tand_SA"]
            Loss_SA_gap = p_SA_gap * self.params["tand_SA"]
        else:
            p_MA_SW = p_MA_top = p_SA_SW = p_SA_gap = None
            Loss_MA_SW = Loss_MA_top = Loss_SA_SW = Loss_SA_gap = None

        self.show_qtls_results(QTLS,
                               p_MA, p_MS, p_SA, p_Si,
                               Loss_MA, Loss_MS, Loss_SA, Loss_Si,
                               x_MA, x_MS, x_SA, x_Si,
                               p_MA_SW, p_MA_top, p_SA_SW, p_SA_gap,
                               Loss_MA_SW, Loss_MA_top, Loss_SA_SW, Loss_SA_gap)

    # =========================================================================
    #  QTLS RESULTS WINDOW
    # =========================================================================
    def show_qtls_results(self, QTLS,
                          p_MA, p_MS, p_SA, p_Si,
                          Loss_MA, Loss_MS, Loss_SA, Loss_Si,
                          x_MA, x_MS, x_SA, x_Si,
                          p_MA_SW=None, p_MA_top=None,
                          p_SA_SW=None, p_SA_gap=None,
                          Loss_MA_SW=None, Loss_MA_top=None,
                          Loss_SA_SW=None, Loss_SA_gap=None):
        self.current_qtls_data = dict(
            gap=self.gap_values, QTLS=QTLS,
            # Capital P (purely geometric, from FEM with nominal t_nom, ε_nom)
            P_MA=self.P_MA, P_MS=self.P_MS, P_SA=self.P_SA, P_Si=self.P_Si,
            # Small p_i (physical participation ratio — NO tan δ)
            p_MA=p_MA, p_MS=p_MS, p_SA=p_SA, p_Si=p_Si,
            # Loss contributions (= p_i · tan δ_i)
            Loss_MA=Loss_MA, Loss_MS=Loss_MS, Loss_SA=Loss_SA, Loss_Si=Loss_Si,
            # Sub-region small p_i (no tan δ) and losses
            p_MA_SW=p_MA_SW, p_MA_top=p_MA_top,
            p_SA_SW=p_SA_SW, p_SA_gap=p_SA_gap,
            Loss_MA_SW=Loss_MA_SW, Loss_MA_top=Loss_MA_top,
            Loss_SA_SW=Loss_SA_SW, Loss_SA_gap=Loss_SA_gap,
            # Loss factors x_i (= scale_i · tan δ_i)
            x_MA=x_MA, x_MS=x_MS, x_SA=x_SA, x_Si=x_Si)

        win = tk.Toplevel(self.root)
        win.title("QTLS Results")
        win.geometry("1050x820")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        # ── TOP TOOLBAR ─────────────────────────────────────────────────────
        tb = ttk.Frame(win, padding="6 4")
        tb.grid(row=0, column=0, sticky="ew")
        ttk.Button(tb, text="💾  Export QTLS Data (CSV)",
                   command=self.save_qtls_data).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="🖼  Save Figure",
                   command=lambda: self._save_fig(fig)).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="📐  Formulas",
                   command=self.show_formula_window).pack(side=tk.LEFT, padx=4)
        if self.has_subregion_data:
            ttk.Button(tb, text="📊  Sidewall p_i Fraction",
                       command=self.open_sidewall_fraction_window
                       ).pack(side=tk.LEFT, padx=4)

        coord_var = tk.StringVar(value="Hover over a plot to see values")
        ttk.Label(tb, textvariable=coord_var,
                  font=("Consolas", 9), foreground="#555"
                  ).pack(side=tk.RIGHT, padx=8)

        # ── FIGURE ──────────────────────────────────────────────────────────
        plot_host = ttk.Frame(win)
        plot_host.grid(row=1, column=0, sticky="nsew")
        plot_host.columnconfigure(0, weight=1)
        plot_host.rowconfigure(0, weight=1)

        fig = Figure(figsize=(10, 8))
        Total_Loss = Loss_MA + Loss_MS + Loss_SA + Loss_Si

        # ── (1) Q_TLS ────────────────────────────────────────────────────
        ax1 = fig.add_subplot(2, 2, 1)
        ax1.semilogy(self.gap_values, QTLS, "o-", lw=2, ms=8)
        ax1.set_xlabel(self.xvar_label, fontsize=11)
        ax1.set_ylabel("Q_TLS", fontsize=11)
        ax1.set_title(f"Quality Factor vs {self.xvar_label}",
                      fontsize=12, fontweight="bold")
        ax1.grid(True, alpha=0.3)

        # ── (2) Small p_i (physical participation, NO tan δ) ─────────────
        ax2 = fig.add_subplot(2, 2, 2)
        ax2.semilogy(self.gap_values, p_MA, "o-", label="p_MA", lw=2, ms=6)
        ax2.semilogy(self.gap_values, p_MS, "s-", label="p_MS", lw=2, ms=6)
        ax2.semilogy(self.gap_values, p_SA, "^-", label="p_SA", lw=2, ms=6)
        ax2.semilogy(self.gap_values, p_Si, "d-", label="p_Si", lw=2, ms=6)
        ax2.set_xlabel(self.xvar_label, fontsize=11)
        ax2.set_ylabel("p_i  (physical participation, no tan δ)", fontsize=11)
        ax2.set_title(f"Small p_i = P_i · scale_i  vs {self.xvar_label}",
                      fontsize=12, fontweight="bold")
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)

        # ── (3) Loss contributions (with tan δ) ──────────────────────────
        ax3 = fig.add_subplot(2, 2, 3)
        ax3.semilogy(self.gap_values, Loss_MA, "o-", label="Loss_MA", lw=2, ms=6)
        ax3.semilogy(self.gap_values, Loss_MS, "s-", label="Loss_MS", lw=2, ms=6)
        ax3.semilogy(self.gap_values, Loss_SA, "^-", label="Loss_SA", lw=2, ms=6)
        ax3.semilogy(self.gap_values, Loss_Si, "d-", label="Loss_Si", lw=2, ms=6)
        ax3.set_xlabel(self.xvar_label, fontsize=11)
        ax3.set_ylabel("Loss_i = p_i · tan(δ_i)", fontsize=11)
        ax3.set_title(f"Loss contributions  vs {self.xvar_label}",
                      fontsize=12, fontweight="bold")
        ax3.legend(fontsize=9)
        ax3.grid(True, alpha=0.3)

        # ── (4) Summary panel ────────────────────────────────────────────
        ax4 = fig.add_subplot(2, 2, 4)
        ax4.axis("off")
        summary = (
            f"QTLS Statistics\n"
            f"{'─'*40}\n"
            f"Min  Q_TLS : {QTLS.min():.3e}\n"
            f"Max  Q_TLS : {QTLS.max():.3e}\n"
            f"Mean Q_TLS : {QTLS.mean():.3e}\n\n"
            f"Loss factors  x_i = scale_i · tan(δ_i)\n"
            f"{'─'*40}\n"
            f"x_MA : {x_MA:.4e}   (⊥)\n"
            f"x_MS : {x_MS:.4e}   (⊥)\n"
            f"x_SA : {x_SA:.4e}   (∥)\n"
            f"x_Si : {x_Si:.4e}\n\n"
            f"{self.xvar_label} range:\n"
            f"  {self.gap_values.min():.4g} – {self.gap_values.max():.4g}\n"
            f"Points : {len(self.gap_values)}"
        )
        ax4.text(0.05, 0.5, summary, fontsize=10, va="center",
                 family="monospace",
                 bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.35))

        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=plot_host)
        canvas.draw()
        NavigationToolbar2Tk(canvas, plot_host).update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── interactive hover ────────────────────────────────────────────
        axes_list = [ax1, ax2, ax3]

        def on_move(event):
            for ax in axes_list:
                if event.inaxes is ax:
                    coord_var.set(
                        f"{self.xvar_label} = {event.xdata:.4g}  │  "
                        f"Y = {event.ydata:.4e}")
                    return
            coord_var.set("")

        fig.canvas.mpl_connect("motion_notify_event", on_move)

    # =========================================================================
    #  PARAMETER SWEEP WINDOW
    # =========================================================================
    def open_sweep_window(self):
        if not self.get_parameters():
            return

        win = tk.Toplevel(self.root)
        win.title("Parameter Sweep")
        win.geometry("560x620")
        win.resizable(False, False)

        ttk.Label(win, text="Parameter Sweep Configuration",
                  font=("Arial", 14, "bold")).pack(pady=10)

        # ── interface selection ──────────────────────────────────────────
        if_frame = ttk.LabelFrame(win, text="Select Interface to Sweep", padding=10)
        if_frame.pack(fill=tk.X, padx=20, pady=6)
        self.sweep_interface = tk.StringVar(value="MS")
        for text, val in [("MS (Metal-Substrate)", "MS"),
                          ("MA (Metal-Air)",       "MA"),
                          ("SA (Substrate-Air)",   "SA")]:
            ttk.Radiobutton(if_frame, text=text,
                            variable=self.sweep_interface,
                            value=val).pack(anchor=tk.W)

        # ── sweep mode ──────────────────────────────────────────────────
        mode_frame = ttk.LabelFrame(win, text="Sweep Mode", padding=10)
        mode_frame.pack(fill=tk.X, padx=20, pady=6)
        self.sweep_mode = tk.StringVar(value="linspace")

        ttk.Radiobutton(mode_frame, text="Linspace (min / max / N)",
                        variable=self.sweep_mode, value="linspace",
                        command=lambda: self._toggle_sweep_mode(
                            eps_lin, eps_custom, t_lin, t_custom)
                        ).pack(anchor=tk.W)
        ttk.Radiobutton(mode_frame, text="Custom values (comma-separated)",
                        variable=self.sweep_mode, value="custom",
                        command=lambda: self._toggle_sweep_mode(
                            eps_lin, eps_custom, t_lin, t_custom)
                        ).pack(anchor=tk.W)

        # ── epsilon range ────────────────────────────────────────────────
        eps_frame = ttk.LabelFrame(win, text="Epsilon (ε) Range", padding=8)
        eps_frame.pack(fill=tk.X, padx=20, pady=4)

        eps_lin = ttk.Frame(eps_frame)
        eps_lin.pack(fill=tk.X)
        for col, (lbl, attr, default) in enumerate([
            ("Min:", "eps_min_entry", "1"),
            ("Max:", "eps_max_entry", "10"),
            ("N:",   "eps_pts_entry", "50"),
        ]):
            ttk.Label(eps_lin, text=lbl).grid(row=0, column=col*2, sticky=tk.W, padx=4)
            e = ttk.Entry(eps_lin, width=8)
            e.insert(0, default)
            e.grid(row=0, column=col*2+1, padx=2)
            setattr(self, attr, e)

        eps_custom = ttk.Frame(eps_frame)
        ttk.Label(eps_custom, text="ε values:").pack(side=tk.LEFT, padx=4)
        self.eps_custom_entry = ttk.Entry(eps_custom, width=35)
        self.eps_custom_entry.insert(0, "1, 2, 4, 6, 8, 10")
        self.eps_custom_entry.pack(side=tk.LEFT, padx=4)
        ToolTip(self.eps_custom_entry, "Enter ε values separated by commas")

        # ── thickness range ──────────────────────────────────────────────
        t_frame = ttk.LabelFrame(win, text="Thickness (nm) Range", padding=8)
        t_frame.pack(fill=tk.X, padx=20, pady=4)

        t_lin = ttk.Frame(t_frame)
        t_lin.pack(fill=tk.X)
        for col, (lbl, attr, default) in enumerate([
            ("Min:", "t_min_entry",  "0.1"),
            ("Max:", "t_max_entry",  "10"),
            ("N:",   "t_pts_entry",  "50"),
        ]):
            ttk.Label(t_lin, text=lbl).grid(row=0, column=col*2, sticky=tk.W, padx=4)
            e = ttk.Entry(t_lin, width=8)
            e.insert(0, default)
            e.grid(row=0, column=col*2+1, padx=2)
            setattr(self, attr, e)

        t_custom = ttk.Frame(t_frame)
        ttk.Label(t_custom, text="t (nm):").pack(side=tk.LEFT, padx=4)
        self.t_custom_entry = ttk.Entry(t_custom, width=35)
        self.t_custom_entry.insert(0, "0.5, 1, 2, 3, 5, 7, 10")
        self.t_custom_entry.pack(side=tk.LEFT, padx=4)
        ToolTip(self.t_custom_entry, "Enter thickness values (nm) separated by commas")

        # initial visibility
        self._toggle_sweep_mode(eps_lin, eps_custom, t_lin, t_custom)

        # keep references so _toggle can use them
        self._eps_lin = eps_lin
        self._eps_custom = eps_custom
        self._t_lin = t_lin
        self._t_custom = t_custom

        # ── x-axis value selection (pick which row's P values to use) ────
        gap_frame = ttk.LabelFrame(win,
            text=f"Select {self.xvar_label} value (fixes geometry row for sweep)",
            padding=8)
        gap_frame.pack(fill=tk.X, padx=20, pady=4)
        mid = str(self.gap_values[len(self.gap_values) // 2])
        self.gap_var = tk.StringVar(value=mid)
        ttk.Label(gap_frame, text=f"{self.xvar_label}:").pack(side=tk.LEFT, padx=4)
        ttk.Combobox(gap_frame, textvariable=self.gap_var,
                     values=[str(g) for g in self.gap_values],
                     width=18).pack(side=tk.LEFT, padx=4)

        # ── run ──────────────────────────────────────────────────────────
        ttk.Button(win, text="▶  Run Sweep",
                   command=lambda: self.run_parameter_sweep(win)
                   ).pack(pady=16)

    def _toggle_sweep_mode(self, eps_lin, eps_custom, t_lin, t_custom):
        if self.sweep_mode.get() == "linspace":
            eps_lin.pack(fill=tk.X)
            eps_custom.pack_forget()
            t_lin.pack(fill=tk.X)
            t_custom.pack_forget()
        else:
            eps_lin.pack_forget()
            eps_custom.pack(fill=tk.X)
            t_lin.pack_forget()
            t_custom.pack(fill=tk.X)

    # =========================================================================
    #  RUN SWEEP
    # =========================================================================
    def run_parameter_sweep(self, parent_window):
        try:
            interface = self.sweep_interface.get()
            gap_val   = float(self.gap_var.get())
            gap_idx   = int(np.argmin(np.abs(self.gap_values - gap_val)))

            # ── build sweep vectors ──────────────────────────────────────
            if self.sweep_mode.get() == "linspace":
                eps_vec = np.linspace(float(self.eps_min_entry.get()),
                                      float(self.eps_max_entry.get()),
                                      int(self.eps_pts_entry.get()))
                t_vec   = np.linspace(float(self.t_min_entry.get()) * 1e-9,
                                      float(self.t_max_entry.get()) * 1e-9,
                                      int(self.t_pts_entry.get()))
            else:
                eps_vec = np.array([float(v.strip())
                                    for v in self.eps_custom_entry.get().split(",")
                                    if v.strip()])
                t_vec   = np.array([float(v.strip()) * 1e-9
                                    for v in self.t_custom_entry.get().split(",")
                                    if v.strip()])

            if len(eps_vec) < 2 or len(t_vec) < 2:
                messagebox.showerror("Error",
                                     "Need at least 2 points for each sweep axis.")
                return

            T, EPS = np.meshgrid(t_vec, eps_vec)

            P_MA = self.P_MA[gap_idx]
            P_MS = self.P_MS[gap_idx]
            P_SA = self.P_SA[gap_idx]
            P_Si = self.P_Si[gap_idx]
            p    = self.params

            if interface == "MS":
                x_MA = (p["t_MA"]/p["t_nom"]) / (p["epsilon_MA"]/p["epsilon_nom"]) * p["tand_MA"]
                x_SA = (p["t_SA"]/p["t_nom"]) * (p["epsilon_SA"]/p["epsilon_nom"]) * p["tand_SA"]
                Loss_fixed = P_MA*x_MA + P_SA*x_SA + P_Si*p["tand_Si"]
                x_grid = (T/p["t_nom"]) / (EPS/p["epsilon_nom"]) * p["tand_MS"]
                Loss_swept = P_MS * x_grid
                xlabel, ylabel, title_suffix = "t_MS (nm)", "ε_MS", "MS"
                eps_fixed, t_fixed = p["epsilon_MS"], p["t_MS"]

            elif interface == "MA":
                x_MS = (p["t_MS"]/p["t_nom"]) / (p["epsilon_MS"]/p["epsilon_nom"]) * p["tand_MS"]
                x_SA = (p["t_SA"]/p["t_nom"]) * (p["epsilon_SA"]/p["epsilon_nom"]) * p["tand_SA"]
                Loss_fixed = P_MS*x_MS + P_SA*x_SA + P_Si*p["tand_Si"]
                x_grid = (T/p["t_nom"]) / (EPS/p["epsilon_nom"]) * p["tand_MA"]
                Loss_swept = P_MA * x_grid
                xlabel, ylabel, title_suffix = "t_MA (nm)", "ε_MA", "MA"
                eps_fixed, t_fixed = p["epsilon_MA"], p["t_MA"]

            else:  # SA
                x_MA = (p["t_MA"]/p["t_nom"]) / (p["epsilon_MA"]/p["epsilon_nom"]) * p["tand_MA"]
                x_MS = (p["t_MS"]/p["t_nom"]) / (p["epsilon_MS"]/p["epsilon_nom"]) * p["tand_MS"]
                Loss_fixed = P_MA*x_MA + P_MS*x_MS + P_Si*p["tand_Si"]
                x_grid = (T/p["t_nom"]) * (EPS/p["epsilon_nom"]) * p["tand_SA"]
                Loss_swept = P_SA * x_grid
                xlabel, ylabel, title_suffix = "t_SA (nm)", "ε_SA", "SA"
                eps_fixed, t_fixed = p["epsilon_SA"], p["t_SA"]

            QTLS_grid = 1.0 / (Loss_fixed + Loss_swept)

            self.show_sweep_results(QTLS_grid, T, EPS, t_vec, eps_vec,
                                    xlabel, ylabel, title_suffix, gap_val,
                                    eps_fixed, t_fixed)

        except Exception as e:
            messagebox.showerror("Error", f"Sweep calculation failed: {e}")

    # =========================================================================
    #  SWEEP RESULTS WINDOW
    # =========================================================================
    def show_sweep_results(self, QTLS_grid, T, EPS, t_vec, eps_vec,
                           xlabel, ylabel, title_suffix, gap_val,
                           eps_fixed, t_fixed):
        win = tk.Toplevel(self.root)
        win.title(f"Parameter Sweep – {title_suffix} Interface")
        win.geometry("1400x940")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        log_QTLS = np.log10(QTLS_grid)

        # ── TOP TOOLBAR ─────────────────────────────────────────────────────
        tb = ttk.Frame(win, padding="6 4")
        tb.grid(row=0, column=0, sticky="ew")

        def export_sweep():
            fn = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")],
                title="Save Sweep Results")
            if not fn:
                return
            try:
                rows = []
                for i, eps in enumerate(eps_vec):
                    for j, t in enumerate(t_vec):
                        rows.append({
                            "eps": eps,
                            "t_nm": t * 1e9,
                            "QTLS": QTLS_grid[i, j],
                            "log10_QTLS": log_QTLS[i, j],
                        })
                pd.DataFrame(rows).to_csv(fn, index=False)
                messagebox.showinfo("Success", f"Sweep data saved to:\n{fn}")
            except Exception as e:
                messagebox.showerror("Error", f"Save failed: {e}")

        ttk.Button(tb, text="💾  Export Sweep Data (CSV)",
                   command=export_sweep).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="🖼  Save Figure",
                   command=lambda: self._save_fig(fig)).pack(side=tk.LEFT, padx=4)
        ttk.Button(tb, text="📐  Formulas",
                   command=self.show_formula_window).pack(side=tk.LEFT, padx=4)

        coord_var = tk.StringVar(value="Hover over a plot to see values")
        ttk.Label(tb, textvariable=coord_var,
                  font=("Consolas", 9), foreground="#555"
                  ).pack(side=tk.RIGHT, padx=8)

        # ── FIGURE ──────────────────────────────────────────────────────────
        plot_host = ttk.Frame(win)
        plot_host.grid(row=1, column=0, sticky="nsew")
        plot_host.columnconfigure(0, weight=1)
        plot_host.rowconfigure(0, weight=1)

        fig = Figure(figsize=(14, 9))

        eps_idx = int(np.argmin(np.abs(eps_vec - eps_fixed)))
        t_idx   = int(np.argmin(np.abs(t_vec   - t_fixed)))

        ax1 = fig.add_subplot(2, 2, 1)
        ax1.semilogy(t_vec * 1e9, QTLS_grid[eps_idx, :], "b-", lw=2)
        ax1.set_xlabel(xlabel, fontsize=11)
        ax1.set_ylabel("Q_TLS", fontsize=11)
        ax1.set_title(f"Q_TLS vs Thickness  |  ε={eps_fixed:.2f}  |  "
                      f"{self.xvar_label}={gap_val:.4g}",
                      fontsize=11, fontweight="bold")
        ax1.grid(True, alpha=0.3)

        ax2 = fig.add_subplot(2, 2, 2)
        ax2.semilogy(eps_vec, QTLS_grid[:, t_idx], "r-", lw=2)
        ax2.set_xlabel(ylabel, fontsize=11)
        ax2.set_ylabel("Q_TLS", fontsize=11)
        ax2.set_title(f"Q_TLS vs Epsilon  |  t={t_fixed*1e9:.2f} nm  |  "
                      f"{self.xvar_label}={gap_val:.4g}",
                      fontsize=11, fontweight="bold")
        ax2.grid(True, alpha=0.3)

        ax3 = fig.add_subplot(2, 2, 3)
        im = ax3.imshow(log_QTLS, aspect="auto", origin="lower",
                        extent=[t_vec[0]*1e9, t_vec[-1]*1e9,
                                eps_vec[0],    eps_vec[-1]],
                        cmap="turbo")
        cl = np.arange(np.floor(log_QTLS.min()), np.ceil(log_QTLS.max()), 0.5)
        CS = ax3.contour(t_vec*1e9, eps_vec, log_QTLS,
                         levels=cl, colors="k", linewidths=0.9, alpha=0.6)
        ax3.clabel(CS, inline=True, fontsize=8, fmt="%0.1f")
        ax3.set_xlabel(xlabel, fontsize=11)
        ax3.set_ylabel(ylabel, fontsize=11)
        ax3.set_title(f"log₁₀(Q_TLS) Contour  |  "
                      f"{self.xvar_label}={gap_val:.4g}",
                      fontsize=11, fontweight="bold")
        fig.colorbar(im, ax=ax3, label="log₁₀(Q_TLS)")
        ax3.plot(t_fixed*1e9, eps_fixed, "wo", ms=10,
                 markeredgecolor="black", markeredgewidth=2, label="Current values")
        ax3.legend(fontsize=9)

        ax4 = fig.add_subplot(2, 2, 4, projection="3d")
        surf = ax4.plot_surface(T*1e9, EPS, log_QTLS,
                                cmap="turbo", alpha=0.9,
                                edgecolor="none", antialiased=True)
        ax4.set_xlabel(xlabel, fontsize=10)
        ax4.set_ylabel(ylabel, fontsize=10)
        ax4.set_zlabel("log₁₀(Q_TLS)", fontsize=10)
        ax4.set_title(f"3D Surface  |  {self.xvar_label}={gap_val:.4g}",
                      fontsize=11, fontweight="bold")
        fig.colorbar(surf, ax=ax4, shrink=0.5, aspect=5, label="log₁₀(Q_TLS)")
        ax4.view_init(elev=25, azim=45)

        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=plot_host)
        canvas.draw()
        NavigationToolbar2Tk(canvas, plot_host).update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── hover ────────────────────────────────────────────────────────
        def on_move(event):
            if event.inaxes is ax1:
                coord_var.set(f"t = {event.xdata:.3f} nm  │  Q_TLS = {10**event.ydata:.3e}"
                              if event.ydata else "")
            elif event.inaxes is ax2:
                coord_var.set(f"ε = {event.xdata:.3f}  │  Q_TLS = {10**event.ydata:.3e}"
                              if event.ydata else "")
            elif event.inaxes is ax3:
                coord_var.set(f"t = {event.xdata:.3f} nm  │  ε = {event.ydata:.3f}"
                              f"  │  log₁₀(Q_TLS) = {ax3.format_coord(event.xdata, event.ydata)[:5]}")
            else:
                coord_var.set("")

        fig.canvas.mpl_connect("motion_notify_event", on_move)

        # ── stats bar ────────────────────────────────────────────────────
        stats = ttk.Frame(win, padding="4 2")
        stats.grid(row=2, column=0, sticky="ew")
        ttk.Label(stats,
                  text=(f"Min Q_TLS: {QTLS_grid.min():.3e}   "
                        f"Max Q_TLS: {QTLS_grid.max():.3e}   "
                        f"Mean Q_TLS: {QTLS_grid.mean():.3e}   "
                        f"Interface: {title_suffix}   "
                        f"{self.xvar_label}: {gap_val:.4g}"),
                  font=("Consolas", 9)).pack()

    # =========================================================================
    #  FORMULA REFERENCE WINDOW
    # =========================================================================
    def show_formula_window(self):
        win = tk.Toplevel(self.root)
        win.title("TLS Loss Formula Reference")
        win.geometry("740x700")
        win.resizable(True, True)

        # scrollable text area
        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        sb = ttk.Scrollbar(frame, orient="vertical")
        text = tk.Text(frame, font=("Consolas", 11), wrap=tk.WORD,
                       yscrollcommand=sb.set, padx=10, pady=10,
                       background="#1e1e2e", foreground="#cdd6f4",
                       insertbackground="white")
        sb.config(command=text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # tag styles
        text.tag_configure("title",    font=("Consolas", 14, "bold"), foreground="#cba6f7")
        text.tag_configure("heading",  font=("Consolas", 12, "bold"), foreground="#89b4fa")
        text.tag_configure("formula",  font=("Consolas", 11),         foreground="#a6e3a1")
        text.tag_configure("note",     font=("Consolas", 10),         foreground="#fab387")
        text.tag_configure("body",     font=("Consolas", 11),         foreground="#cdd6f4")
        text.tag_configure("sep",      font=("Consolas", 11),         foreground="#585b70")

        def add(t, tag="body"):
            text.insert(tk.END, t + "\n", tag)

        add("TLS Loss Model — Formula Reference", "title")
        add("=" * 62, "sep")
        add("")

        add("OVERVIEW — three distinct quantities", "heading")
        add("")
        add("  P_i   — capital P, geometric participation ratio from FEM", "body")
        add("          (computed with NOMINAL t_nom and ε_nom)", "body")
        add("  p_i   — small p, PHYSICAL participation ratio for the real", "body")
        add("          interface material.  No tan(δ).", "body")
        add("  Loss_i — fractional loss contribution = p_i · tan(δ_i)", "body")
        add("")
        add("  Q_TLS = 1 / Σᵢ  Loss_i  =  1 / Σᵢ  p_i · tan(δ_i)", "formula")
        add("")
        add("─" * 62, "sep")
        add("")

        add("CAPITAL P (from COMSOL / FEM energy integrals)", "heading")
        add("")
        add("  Pᵢ = U_i / U_total", "formula")
        add("")
        add("  P_MA  =  U_MA  / U_total   (Metal-Air interface)", "body")
        add("  P_MS  =  U_MS  / U_total   (Metal-Substrate interface)", "body")
        add("  P_SA  =  U_SA  / U_total   (Substrate-Air interface)", "body")
        add("  P_Si  =  U_Si  / U_total   (Silicon bulk)", "body")
        add("")
        add("─" * 62, "sep")
        add("")

        add("SMALL p_i — physical participation, NO tan(δ)", "heading")
        add("")
        add("  Rescales P_i from simulation (t_nom, ε_nom) to the real", "body")
        add("  material's (t_i, ε_i):", "body")
        add("")
        add("  ┌─ PERPENDICULAR (⊥) interfaces: MA and MS ──────────────┐", "note")
        add("  │  E-field ⊥ interface  →  dielectric enters as 1/ε      │", "note")
        add("  └─────────────────────────────────────────────────────────┘", "note")
        add("")
        add("  p_MA  =  P_MA · (t_MA / t_nom) · (ε_nom / ε_MA)", "formula")
        add("  p_MS  =  P_MS · (t_MS / t_nom) · (ε_nom / ε_MS)", "formula")
        add("")
        add("  ┌─ PARALLEL (∥) interface: SA ───────────────────────────┐", "note")
        add("  │  E-field ∥ interface  →  dielectric enters as ε        │", "note")
        add("  └─────────────────────────────────────────────────────────┘", "note")
        add("")
        add("  p_SA  =  P_SA · (t_SA / t_nom) · (ε_SA / ε_nom)", "formula")
        add("")
        add("  ┌─ BULK Silicon — no rescaling ──────────────────────────┐", "note")
        add("  └─────────────────────────────────────────────────────────┘", "note")
        add("")
        add("  p_Si  =  P_Si", "formula")
        add("")
        add("─" * 62, "sep")
        add("")

        add("LOSS CONTRIBUTIONS  Loss_i = p_i · tan(δ_i)", "heading")
        add("")
        add("  Loss_MA = p_MA · tan(δ_MA)", "formula")
        add("  Loss_MS = p_MS · tan(δ_MS)", "formula")
        add("  Loss_SA = p_SA · tan(δ_SA)", "formula")
        add("  Loss_Si = p_Si · tan(δ_Si)", "formula")
        add("")
        add("  Equivalently, Loss_i = P_i · x_i  where", "body")
        add("    x_i  =  (scaling factor)_i · tan(δ_i)", "body")
        add("  is the 'effective loss factor' from Calusine et al.", "body")
        add("")
        add("─" * 62, "sep")
        add("")

        add("FULL Q_TLS EXPRESSION", "heading")
        add("")
        add("  Q_TLS = 1 / (Loss_MA + Loss_MS + Loss_SA + Loss_Si)", "formula")
        add("")
        add("─" * 62, "sep")
        add("")

        add("SUB-REGION SMALL p_i (sidewall vs top/flat)", "heading")
        add("Same rescaling applies to sub-region capital-P:", "body")
        add("")
        add("  p_MA_SW  = P_MA_SW  · scale_MA      (no tan δ)", "formula")
        add("  p_MA_top = P_MA_top · scale_MA", "formula")
        add("  p_SA_SW  = P_SA_SW  · scale_SA", "formula")
        add("  p_SA_gap = P_SA_gap · scale_SA", "formula")
        add("")
        add("Fraction is purely geometric (scale_i cancels):", "body")
        add("  p_i_SW / p_i  =  P_i_SW / P_i", "formula")
        add("")
        add("─" * 62, "sep")
        add("")

        add("PARAMETER SWEEP", "heading")
        add("Sweep over (t, ε) of one interface; others held at nominal:", "body")
        add("")
        add("  Loss_fixed = Σⱼ≠ᵢ  Loss_j(nominal)", "formula")
        add("  Loss_swept(t, ε) = P_i · x_i(t, ε)", "formula")
        add("  Q_TLS(t, ε) = 1 / (Loss_fixed + Loss_swept)", "formula")
        add("")
        add("─" * 62, "sep")
        add("")
        add("REFERENCES", "heading")
        add("  [1] Calusine et al., Appl. Phys. Lett. 112, 062601 (2018)", "body")
        add("      Supplementary Eqs. S1, S3, S4, S5", "body")
        add("  [2] Wenner et al., Appl. Phys. Lett. 99, 113513 (2011)", "body")
        add("")

        text.config(state=tk.DISABLED)

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    # =========================================================================
    #  SIDEWALL p_i FRACTION WINDOW
    # =========================================================================
    def open_sidewall_fraction_window(self):
        d = self.current_qtls_data
        if d is None or d.get("p_MA_SW") is None:
            messagebox.showwarning("Warning",
                "Run 'Calculate QTLS' first and ensure sub-region\n"
                "energy columns are present in the CSV.")
            return

        win = tk.Toplevel(self.root)
        win.title("Sidewall p_i Fraction Analysis")
        win.geometry("1200x860")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        ctrl = ttk.Frame(win, padding="6 4")
        ctrl.grid(row=0, column=0, sticky="ew")

        ttk.Label(ctrl, text="Interface:").pack(side=tk.LEFT, padx=(4, 2))
        self._sw_iface_var = tk.StringVar(value="Both")
        ttk.Combobox(ctrl, textvariable=self._sw_iface_var,
                     values=["MA", "SA", "Both"],
                     state="readonly", width=8).pack(side=tk.LEFT, padx=4)

        ttk.Label(ctrl, text="Plot type:").pack(side=tk.LEFT, padx=(12, 2))
        self._sw_plot_var = tk.StringVar(value="Both")
        ttk.Combobox(ctrl, textvariable=self._sw_plot_var,
                     values=["Bar", "Line", "Both"],
                     state="readonly", width=8).pack(side=tk.LEFT, padx=4)

        ttk.Label(ctrl, text="Y-axis:").pack(side=tk.LEFT, padx=(12, 2))
        self._sw_yaxis_var = tk.StringVar(value="Fraction")
        ttk.Combobox(ctrl, textvariable=self._sw_yaxis_var,
                     values=["Fraction  (p_i_SW / p_i)",
                             "Absolute  (p_i)"],
                     state="readonly", width=22).pack(side=tk.LEFT, padx=4)

        plot_host = ttk.Frame(win)
        plot_host.grid(row=1, column=0, sticky="nsew")
        plot_host.columnconfigure(0, weight=1)
        plot_host.rowconfigure(0, weight=1)

        self._sw_coord_var = tk.StringVar(value="Hover to inspect values")
        ttk.Label(ctrl, textvariable=self._sw_coord_var,
                  font=("Consolas", 9), foreground="#555"
                  ).pack(side=tk.RIGHT, padx=8)

        ttk.Button(ctrl, text="▶  Update",
                   command=lambda: self._draw_sw_plots(plot_host, d)
                   ).pack(side=tk.LEFT, padx=8)

        def export_sw():
            fn = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")],
                title="Save Sidewall p_i Fraction Data")
            if not fn:
                return
            try:
                xcol = self.xvar_label.replace(" ", "_").replace("(","").replace(")","")
                pd.DataFrame({
                    xcol:           d["gap"],
                    # Physical small p_i (no tan δ)
                    "p_MA":         d["p_MA"],
                    "p_MA_SW":      d["p_MA_SW"],
                    "p_MA_top":     d["p_MA_top"],
                    "p_MA_SW_frac": d["p_MA_SW"] / d["p_MA"],
                    "p_SA":         d["p_SA"],
                    "p_SA_SW":      d["p_SA_SW"],
                    "p_SA_gap":     d["p_SA_gap"],
                    "p_SA_SW_frac": d["p_SA_SW"] / d["p_SA"],
                    # Loss contributions (with tan δ)
                    "Loss_MA":      d["Loss_MA"],
                    "Loss_MA_SW":   d["Loss_MA_SW"],
                    "Loss_MA_top":  d["Loss_MA_top"],
                    "Loss_SA":      d["Loss_SA"],
                    "Loss_SA_SW":   d["Loss_SA_SW"],
                    "Loss_SA_gap":  d["Loss_SA_gap"],
                }).to_csv(fn, index=False)
                messagebox.showinfo("Success", f"Data saved to:\n{fn}")
            except Exception as e:
                messagebox.showerror("Error", f"Save failed: {e}")

        ttk.Button(ctrl, text="💾  Export CSV",
                   command=export_sw).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🖼  Save Figure",
                   command=lambda: self._save_fig(self.current_sw_fig)
                   ).pack(side=tk.LEFT, padx=4)

        info = ttk.Frame(win, padding="4 2")
        info.grid(row=2, column=0, sticky="ew")
        ttk.Label(info,
                  text=("p_i = P_i · x_i   │   "
                        "p_MA_SW = P_MA_SW · x_MA   (P_MA_SW = U[MA Res SW + MA GP SW] / U_total)\n"
                        "p_SA_SW = P_SA_SW · x_SA   (P_SA_SW = U[SA GP-SW + SA Res SW] / U_total)   │   "
                        "Fraction = p_i_SW / p_i  =  P_i_SW / P_i  (x_i cancels)"),
                  font=("Consolas", 9), foreground="#555").pack()

        self._draw_sw_plots(plot_host, d)

    def _draw_sw_plots(self, plot_host, d):
        for w in plot_host.winfo_children():
            w.destroy()

        iface    = self._sw_iface_var.get()
        ptype    = self._sw_plot_var.get()
        y_mode   = self._sw_yaxis_var.get()
        use_frac = y_mode.startswith("Fraction")

        show_MA  = iface in ("MA", "Both")
        show_SA  = iface in ("SA", "Both")
        show_bar = ptype in ("Bar",  "Both")
        show_lin = ptype in ("Line", "Both")

        n_cols = (1 if show_MA else 0) + (1 if show_SA else 0)
        n_rows = (1 if show_bar else 0) + (1 if show_lin else 0)
        if n_cols == 0 or n_rows == 0:
            return

        fig = Figure(figsize=(6.2 * n_cols, 4.6 * n_rows))
        self.current_sw_fig = fig

        xvals  = d["gap"]
        x_pos  = np.arange(len(xvals))
        xlbls  = [f"{v:.4g}" for v in xvals]
        axes_hover = []
        plot_idx = 1
        C_SW  = "#2196F3"
        C_OTH = "#FF9800"

        def _y(p_sub, p_tot):
            return np.where(p_tot > 0, p_sub / p_tot, 0.0) if use_frac else p_sub

        def _ylabel(mat):
            return (f"p_{mat}_SW / p_{mat}" if use_frac
                    else f"p_{mat}  (loss contribution)")

        for row_type in (["Bar"] if show_bar else []) + (["Line"] if show_lin else []):
            for mat in (["MA"] if show_MA else []) + (["SA"] if show_SA else []):
                ax = fig.add_subplot(n_rows, n_cols, plot_idx)
                plot_idx += 1

                if mat == "MA":
                    p_tot = d["p_MA"]; p_sw = d["p_MA_SW"]; p_oth = d["p_MA_top"]
                    lbl_sw, lbl_oth = "SW (Res SW + GP SW)", "Top (GP_top + Res-top)"
                else:
                    p_tot = d["p_SA"]; p_sw = d["p_SA_SW"]; p_oth = d["p_SA_gap"]
                    lbl_sw, lbl_oth = "SW (GP-SW + Res SW)", "Gap/Flat (SA Gap)"

                y_sw  = _y(p_sw,  p_tot)
                y_oth = _y(p_oth, p_tot)

                if row_type == "Bar":
                    w = 0.35
                    ax.bar(x_pos - w/2, y_sw,  w, label=lbl_sw,
                           color=C_SW,  edgecolor="k", linewidth=0.6)
                    ax.bar(x_pos + w/2, y_oth, w, label=lbl_oth,
                           color=C_OTH, edgecolor="k", linewidth=0.6)
                    ax.set_xticks(x_pos)
                    ax.set_xticklabels(xlbls, rotation=45, ha="right", fontsize=9)
                    if use_frac:
                        ax.set_ylim(0, 1.05)
                        ax.axhline(0.5, color="gray", ls="--", lw=0.8, alpha=0.5)
                    else:
                        ax.set_yscale("log")
                    axes_hover.append((ax, "bar", xvals))
                else:
                    ax.plot(xvals, y_sw,  "o-", lw=2, ms=6,
                            label=lbl_sw,  color=C_SW)
                    ax.plot(xvals, y_oth, "s-", lw=2, ms=6,
                            label=lbl_oth, color=C_OTH)
                    if use_frac:
                        ax.plot(xvals, y_sw + y_oth, "d--", lw=1.2, ms=4,
                                label="Sum (check≈1)", color="gray", alpha=0.6)
                        ax.set_ylim(0, 1.05)
                    else:
                        ax.semilogy(xvals, p_tot, "k--", lw=1.2,
                                    label=f"p_{mat} total", alpha=0.7)
                        ax.set_yscale("log")
                    axes_hover.append((ax, "line", xvals))

                ax.set_xlabel(self.xvar_label, fontsize=11)
                ax.set_ylabel(_ylabel(mat), fontsize=10)
                ax.set_title(
                    f"p_{mat}: Sidewall vs {'Top' if mat == 'MA' else 'Gap'}  "
                    f"[{'Fraction' if use_frac else 'Absolute'}]  —  {row_type}",
                    fontsize=11, fontweight="bold")
                ax.legend(fontsize=8, loc="best")
                ax.grid(True, alpha=0.3)

        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=plot_host)
        canvas.draw()
        NavigationToolbar2Tk(canvas, plot_host).update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        coord_var = self._sw_coord_var

        def on_move(event):
            for (ax, kind, xv) in axes_hover:
                if event.inaxes is ax and event.xdata is not None:
                    if kind == "bar":
                        idx = int(np.clip(np.round(event.xdata), 0, len(xv) - 1))
                        coord_var.set(
                            f"{self.xvar_label} = {xv[idx]:.4g}  │  "
                            f"Y = {event.ydata:.4e}")
                    else:
                        coord_var.set(
                            f"{self.xvar_label} = {event.xdata:.4g}  │  "
                            f"Y = {event.ydata:.4e}")
                    return
            coord_var.set("")

        fig.canvas.mpl_connect("motion_notify_event", on_move)

    # =========================================================================
    #  SAVE HELPERS
    # =========================================================================
    def _save_fig(self, fig):
        fn = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"),
                       ("SVG", "*.svg"), ("All", "*.*")],
            title="Save Figure")
        if fn:
            try:
                fig.savefig(fn, dpi=300, bbox_inches="tight")
                messagebox.showinfo("Success", f"Figure saved to:\n{fn}")
            except Exception as e:
                messagebox.showerror("Error", f"Save failed: {e}")

    def save_participation_data(self):
        if self.gap_values is None:
            messagebox.showwarning("Warning", "No data to save!")
            return
        fn = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
            title="Save Participation Ratios")
        if fn:
            try:
                # Use xvar_label as the column name (safe for CSV: replace spaces/parens)
                xcol = self.xvar_label.replace(" ", "_").replace("(", "").replace(")", "")
                pd.DataFrame({
                    xcol:   self.gap_values,
                    "P_MA": self.P_MA, "P_MS": self.P_MS,
                    "P_SA": self.P_SA, "P_Si": self.P_Si,
                }).to_csv(fn, index=False)
                messagebox.showinfo("Success", f"Data saved to:\n{fn}")
            except Exception as e:
                messagebox.showerror("Error", f"Save failed: {e}")

    def save_participation_plot(self):
        if self.current_participation_fig is None:
            messagebox.showwarning("Warning", "No plot to save!")
            return
        self._save_fig(self.current_participation_fig)

    def save_qtls_data(self):
        if self.current_qtls_data is None:
            messagebox.showwarning("Warning", "No QTLS data to save!")
            return
        fn = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
            title="Save QTLS Results")
        if fn:
            try:
                d = self.current_qtls_data
                xcol = self.xvar_label.replace(" ", "_").replace("(", "").replace(")", "")
                out = {
                    xcol:      d["gap"],
                    "QTLS":    d["QTLS"],
                    # Capital P (geometric, from FEM)
                    "P_MA":    d["P_MA"],  "P_MS":   d["P_MS"],
                    "P_SA":    d["P_SA"],  "P_Si":   d["P_Si"],
                    # Small p_i (physical participation, NO tan δ)
                    "p_MA":    d["p_MA"],  "p_MS":   d["p_MS"],
                    "p_SA":    d["p_SA"],  "p_Si":   d["p_Si"],
                    # Loss contributions (= p_i · tan δ_i)
                    "Loss_MA": d["Loss_MA"], "Loss_MS": d["Loss_MS"],
                    "Loss_SA": d["Loss_SA"], "Loss_Si": d["Loss_Si"],
                    # Loss factors x_i = scale_i · tan δ_i
                    "x_MA":    d["x_MA"],  "x_MS":   d["x_MS"],
                    "x_SA":    d["x_SA"],  "x_Si":   d["x_Si"],
                }
                # Sub-region p_i and losses (only when sidewall columns present)
                if d.get("p_MA_SW") is not None:
                    out["p_MA_SW"]       = d["p_MA_SW"]
                    out["p_MA_top"]      = d["p_MA_top"]
                    out["p_MA_SW_frac"]  = d["p_MA_SW"] / d["p_MA"]
                    out["p_SA_SW"]       = d["p_SA_SW"]
                    out["p_SA_gap"]      = d["p_SA_gap"]
                    out["p_SA_SW_frac"]  = d["p_SA_SW"] / d["p_SA"]
                    out["Loss_MA_SW"]    = d["Loss_MA_SW"]
                    out["Loss_MA_top"]   = d["Loss_MA_top"]
                    out["Loss_SA_SW"]    = d["Loss_SA_SW"]
                    out["Loss_SA_gap"]   = d["Loss_SA_gap"]
                pd.DataFrame(out).to_csv(fn, index=False)
                messagebox.showinfo("Success", f"QTLS data saved to:\n{fn}")
            except Exception as e:
                messagebox.showerror("Error", f"Save failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = TLSAnalysisGUI(root)
    root.mainloop()