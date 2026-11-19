"""
ISO 24817:2017 Composite Repair Design Calculator
Non-through-wall (Type A) defects in pipes and pipe fittings

Author:  Sina Rastegar

Scope
- Minimum repair thickness for pressure, axial, shear, torsion and bending
  loads by three methods: substrate allowable stress (Formulae 1, 2),
  substrate load sharing limited by laminate strain (Formulae 5, 6) and
  laminate strain alone (Formulae 8, 9)
- Allowable laminate strain with temperature and thermal-expansion effects
  (Tables 7, 9 and Formula 10)
- Thickness increase for bends, tees, flanges and reducers (Formula 32) and
  the pressure limit of a tee (Formula 33)
- External pressure / vacuum and soil loads (Formulae 30, 31)
- Axial extent: overlap, taper and total length (Formulae 18-20), and the
  lap-shear overlap check (Formula 21)
- Interfacial stress of repairs applied under pressure (Formula 29)
- Minimum resin Tg / HDT (Tables 5, 6), reported only

Not included
- Type B (through-wall) defects
- Limited axial extent (Formulae 22-24): if the length available on site is
  less than overlap + taper, treat it as a special design case. The
  thickness is then multiplied by (l_over / l_available)^(2/3), with l_over
  of at least 25 mm and a factor of at most 2.5
- Cyclic loading (7.5.9.2): above 7 000 load cycles the allowable strains
  must be de-rated by a factor f_c (Formula 25); not calculated here
- Environmental compatibility (7.5.2) and impact resistance (7.5.9.1):
  confirm with the resin supplier's data and tests
  
Notes
- ts: minimum remaining wall used in design; for active corrosion use the
  value predicted at the end of the design life
- ps: MAWP from a defect assessment if available; otherwise estimated as
  2 ts sigma_s / (D - ts), a conservative uniform-wall estimate
- Checked against ISO 24817:2017 Annex K, worked example 1 (bottom of
  file)

Units: mm, MPa, N, N.mm, mm/mm (strain), degC
"""

from dataclasses import dataclass, asdict, replace
from math import pi, sqrt, isfinite

# Table 11: repair thickness increase factors, f_th,stress
COMPONENT_FACTORS = {
    "straight_pipe": 1.0,
    "bend": 1.2,
    "tee": 2.0,
    "flange": 1.1,
    "reducer": 1.1,
}
from typing import Optional


@dataclass
class RepairInputs:
    # Design route:
    # stress / substrate_strain / laminate_strain
    design_route: str

    # Pipe and substrate
    D: float
    t: float
    ts: float
    Es: float
    allowable_stress: float

    # Repair laminate
    Ec: float
    Ea: float
    nu: float

    # Short-term lap shear strength of the repair [MPa]
    tau: float

    # Pressure
    p: float
    p_live: float

    # MAWP of the substrate [MPa]: from a defect assessment, or None to
    # calculate it as 2 ts sigma_s / (D - ts) (Annex K, Step 7)
    ps: Optional[float] = None

    # Applied loads
    Fsh: float = 0.0
    Mto: float = 0.0
    Fax: float = 0.0
    Max: float = 0.0

    # Piping component (Table 11); Db is the branch diameter of a tee
    component: str = "straight_pipe"
    Db: Optional[float] = None

    # Defect geometry
    defect_type: str = "circular"
    defect_diameter: Optional[float] = 10.0
    defect_length: Optional[float] = None

    # Axial loads and taper
    axial_loads_present: bool = False

    # Table 9 / Formula (10)
    repair_class: Optional[int] = None
    lifetime: Optional[float] = None

    # Temperatures [degC]: design, installation and upper temperature
    # limit of the repair system (Table 6)
    T_design: Optional[float] = None
    T_install: Optional[float] = None
    T_m: Optional[float] = None

    # Live repair, Formula (29): pressure and temperature after repair
    p_after: Optional[float] = None
    T_after: Optional[float] = None

    # Thermal expansion coefficients [mm/mm/degC]
    alpha_s: Optional[float] = None
    alpha_c: Optional[float] = None
    alpha_a: Optional[float] = None

    # Short-term laminate strain to failure
    short_term_strain_failure: Optional[float] = None

    # External loads, Formulae (30) and (31) (all optional)
    p_e: Optional[float] = None  # external or vacuum pressure [MPa]
    burial_depth: Optional[float] = None  # h, to centreline [mm]
    gamma_soil: Optional[float] = None  # soil specific weight [MPa/mm]


# ----- 1. INPUT VALIDATION -----


def validate_inputs(x):
    if x.design_route not in ("stress", "substrate_strain", "laminate_strain"):
        raise ValueError(
            "design_route must be stress, substrate_strain "
            "or laminate_strain."
        )

    positive = {
        "D": x.D,
        "t": x.t,
        "ts": x.ts,
        "Es": x.Es,
        "allowable_stress": x.allowable_stress,
        "Ec": x.Ec,
        "Ea": x.Ea,
        "tau": x.tau,
    }

    for name, value in positive.items():
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")

    non_negative = {
        "p": x.p,
        "p_live": x.p_live,
        "Fsh": x.Fsh,
        "Mto": x.Mto,
        "Fax": x.Fax,
        "Max": x.Max,
    }

    for name, value in non_negative.items():
        if not isfinite(value) or value < 0:
            raise ValueError(f"{name} must be non-negative and finite.")

    if x.ps is not None and (not isfinite(x.ps) or x.ps < 0):
        raise ValueError("ps must be non-negative and finite.")

    if not 0 <= x.nu < 0.5:
        raise ValueError("Poisson's ratio must satisfy 0 <= nu < 0.5.")

    if x.ts > x.t:
        raise ValueError(
            "Remaining thickness cannot exceed original thickness."
        )

    if x.D <= x.ts:
        raise ValueError("D must be greater than ts.")

    if x.ts < 1.0:
        raise ValueError(
            "ts must be at least 1 mm; a thinner remaining wall is a "
            "Type B defect, which this calculator does not cover."
        )

    if x.defect_type not in ("circular", "slot"):
        raise ValueError("defect_type must be circular or slot.")

    if x.defect_type == "circular":
        if x.defect_diameter is None or x.defect_diameter <= 0:
            raise ValueError("A positive defect_diameter is required.")

    if x.defect_type == "slot":
        if x.defect_length is None or x.defect_length <= 0:
            raise ValueError("A positive defect_length is required.")

    # Formula (10) strains are needed in all routes (Formula 21 check)
    required = {
        "repair_class": x.repair_class,
        "lifetime": x.lifetime,
        "T_design": x.T_design,
        "T_install": x.T_install,
        "T_m": x.T_m,
        "alpha_s": x.alpha_s,
        "alpha_c": x.alpha_c,
        "alpha_a": x.alpha_a,
        "short_term_strain_failure": x.short_term_strain_failure,
    }

    missing = [name for name, value in required.items() if value is None]

    if missing:
        raise ValueError(
            "Missing allowable-strain inputs: " + ", ".join(missing)
        )

    if x.repair_class not in (1, 2, 3):
        raise ValueError("Repair class must be 1, 2 or 3.")

    if x.lifetime <= 0:
        raise ValueError("Lifetime must be positive.")

    for name in ("T_design", "T_install", "T_m"):
        if not isfinite(getattr(x, name)):
            raise ValueError(f"{name} must be finite.")

    # Piping component: Table 11 and Formula (33)
    if x.component not in COMPONENT_FACTORS:
        raise ValueError(
            "component must be one of: " + ", ".join(COMPONENT_FACTORS) + "."
        )

    if x.component == "tee" and (
        x.Db is None or not isfinite(x.Db) or x.Db <= 0
    ):
        raise ValueError("Db (branch diameter) is required for a tee.")

    # External loads: inputs for Formulae (30) and (31)
    if x.p_e is not None and (not isfinite(x.p_e) or x.p_e < 0):
        raise ValueError("p_e must be non-negative and finite.")

    if (x.burial_depth is None) != (x.gamma_soil is None):
        raise ValueError("burial_depth and gamma_soil must be given together.")

    if x.burial_depth is not None:
        if not isfinite(x.burial_depth) or x.burial_depth <= 0:
            raise ValueError("burial_depth must be positive and finite.")
        if not isfinite(x.gamma_soil) or x.gamma_soil < 0:
            raise ValueError("gamma_soil must be non-negative and finite.")

    # Live repair: inputs for Formula (29)
    if x.p_live > 0:
        if x.p_after is None:
            raise ValueError("p_after is required when p_live > 0.")
        if not isfinite(x.p_after) or x.p_after < 0:
            raise ValueError("p_after must be non-negative and finite.")
        if x.p_after < x.p_live and (
            x.T_after is None or not isfinite(x.T_after)
        ):
            raise ValueError(
                "T_after is required for the interfacial stress check when p_after < p_live."
            )

    if x.short_term_strain_failure <= 0.01:
        raise ValueError(
            "The allowable strains (Table 9) apply only when the short-term "
            "strain to failure is greater than 0.01; otherwise performance "
            "test data is needed, which this calculator does not cover."
        )


# ----- 2. EQUIVALENT PRESSURE AND AXIAL LOAD (FORMULAE 3, 4) -----


def calculate_equivalent_loads(x):
    # Formula (3)
    q = x.Fsh + 2.0 * x.Mto / x.D

    p_transition = 4.0 * q / (pi * x.D**2)

    if x.p >= p_transition:
        if x.p == 0:
            p_eq = 0.0
        else:
            p_eq = x.p * (1.0 + 16.0 / (pi * x.D**2 * x.p) ** 2 * q**2)

        branch = "upper branch (Formula 3)"

    else:
        p_eq = x.p + p_transition
        branch = "lower branch (Formula 3)"

    # Formula (4)
    F_eq = (
        pi / 4.0 * x.p * x.D**2
        + sqrt(x.Fax**2 + 4.0 * x.Fsh**2)
        + 4.0 / x.D * sqrt(x.Max**2 + x.Mto**2)
    )

    return {
        "q": q,
        "p_eq": p_eq,
        "F_eq": F_eq,
        "transition_pressure": p_transition,
        "branch": branch,
    }


# ----- 3. STRESS-LIMITED THICKNESS (FORMULAE 1, 2) -----


def calculate_stress_thickness(x, loads):
    p_eq = loads["p_eq"]
    F_eq = loads["F_eq"]

    # Formula (1): circumferential
    t_hoop_raw = (
        x.D
        * x.Es
        / (2.0 * x.allowable_stress * x.Ec)
        * (p_eq + 2.0 * x.nu * F_eq / (pi * x.D**2) - x.ps)
    )

    # Formula (2): axial
    t_axial_raw = (
        x.D
        * x.Es
        / (2.0 * x.allowable_stress * x.Ea)
        * (2.0 * F_eq / (pi * x.D**2) - x.nu * (x.Ea / x.Ec) * p_eq - x.ps)
    )

    t_hoop = max(0.0, t_hoop_raw)
    t_axial = max(0.0, t_axial_raw)

    return {
        "t_hoop_raw": t_hoop_raw,
        "t_axial_raw": t_axial_raw,
        "t_hoop": t_hoop,
        "t_axial": t_axial,
        "t_design": max(t_hoop, t_axial),
        "route": "Stress route: substrate allowable stress (Formulae 1, 2)",
    }


# ----- 4. ALLOWABLE STRAINS (TABLES 7, 9; FORMULA 10) -----


def calculate_allowable_strains(x):
    class_data = {
        1: (0.004214, 0.01135),
        2: (0.003634, 0.00813),
        3: (0.003061, 0.0044),
    }

    coefficient, exponent = class_data[x.repair_class]

    epsilon_c0 = coefficient * 10 ** (-exponent * x.lifetime)

    ratio = x.Ea / x.Ec

    if ratio > 0.5 + 1e-12:
        epsilon_a0 = epsilon_c0
        table_branch = "Ea > 0.5 Ec"

    else:
        if x.repair_class == 1:
            epsilon_a0 = 0.002768 * 10 ** (-0.0221 * x.lifetime)
        else:
            epsilon_a0 = 0.001

        table_branch = "Ea <= 0.5 Ec"

    # Table 5: the upper temperature limit must not be below Td
    if x.T_m < x.T_design:
        raise ValueError(
            f"Tm = {x.T_m:.1f} degC is below the design temperature "
            f"Td = {x.T_design:.1f} degC (Table 5)."
        )

    # Table 7: temperature de-rating factor
    margin = x.T_m - x.T_design
    f_T1 = 0.0000625 * margin**2 + 0.00125 * margin + 0.7

    # Temperature difference between design and installation
    delta_T = x.T_design - x.T_install

    # Formula (10): the thermally induced strain is taken as an absolute
    # value, so it always reduces the allowable strain.
    thermal_c = abs(delta_T * (x.alpha_s - x.alpha_c))

    thermal_a = abs(delta_T * (x.alpha_s - x.alpha_a))

    epsilon_c = f_T1 * epsilon_c0 - thermal_c

    epsilon_a = f_T1 * epsilon_a0 - thermal_a

    if epsilon_a <= 0 or (x.design_route != "stress" and epsilon_c <= 0):
        raise ValueError(
            "Thermal correction produces a non-positive allowable strain."
        )

    return {
        "f_T1": f_T1,
        "delta_T": delta_T,
        "epsilon_c0": epsilon_c0,
        "epsilon_a0": epsilon_a0,
        "thermal_correction_c": thermal_c,
        "thermal_correction_a": thermal_a,
        "epsilon_c": epsilon_c,
        "epsilon_a": epsilon_a,
        "table_branch": table_branch,
    }


# ----- 5. STRAIN-LIMITED HOOP THICKNESS, NUMERICAL SOLUTION (FORMULA 5) -----


def solve_formula_5(x, loads, epsilon_c):
    """
    Formula (5):
    epsilon_c =
        1/(Ec*t) * (peq*D/2 + nu*Feq/(pi*D))
        - ps*D/(2Ect)
        - plive*D/[2*(Ec*t + Es*ts)]

    Rearranged as:
    A/t - B/(Ec*t + Es*ts) - epsilon_c = 0
    """

    p_eq = loads["p_eq"]
    F_eq = loads["F_eq"]

    A = (p_eq * x.D / 2.0 + x.nu * F_eq / (pi * x.D) - x.ps * x.D / 2.0) / x.Ec

    B = x.p_live * x.D / 2.0

    if A <= 0:
        return {"thickness": 0.0, "iterations": 0, "equation_residual": None}

    def equation(t_value):
        return A / t_value - B / (x.Ec * t_value + x.Es * x.ts) - epsilon_c

    low = 1e-12
    high = max(x.D / 100.0, 1.0)

    # Find upper bracket
    for _ in range(200):
        if equation(high) <= 0:
            break

        high *= 2.0

    else:
        raise ValueError(
            "Could not bracket a positive solution of the strain-limited "
            "hoop thickness equation (Formula 5)."
        )

    # Bisection
    iterations = 0

    for iterations in range(1, 201):
        mid = 0.5 * (low + high)
        value = equation(mid)

        if abs(value) < 1e-12:
            break

        if value > 0:
            low = mid
        else:
            high = mid

    thickness = 0.5 * (low + high)

    return {
        "thickness": thickness,
        "iterations": iterations,
        "equation_residual": equation(thickness),
    }


# ----- 6. STRAIN-LIMITED THICKNESS (FORMULAE 5, 6, 8, 9) -----


def calculate_strain_thickness(x, loads, strains):
    p_eq = loads["p_eq"]
    F_eq = loads["F_eq"]

    epsilon_c = strains["epsilon_c"]
    epsilon_a = strains["epsilon_a"]

    if x.design_route == "substrate_strain":
        # Formula (5)
        formula5 = solve_formula_5(x, loads, epsilon_c)

        t_hoop_raw = formula5["thickness"]

        # Formula (6)
        t_axial_raw = (
            1.0
            / epsilon_a
            * (F_eq / (pi * x.D * x.Ea) - p_eq * x.D * x.nu / (2.0 * x.Ec))
        )

        route = (
            "Substrate strain route: load sharing with the substrate "
            "(Formulae 5, 6)"
        )

    else:
        # Formula (8)
        t_hoop_raw = (
            1.0
            / epsilon_c
            * (p_eq * x.D / (2.0 * x.Ec) + F_eq * x.nu / (pi * x.D * x.Ec))
        )

        # Formula (9)
        t_axial_raw = (
            1.0
            / epsilon_a
            * (F_eq / (pi * x.D * x.Ea) - p_eq * x.D * x.nu / (2.0 * x.Ec))
        )

        formula5 = None

        route = "Laminate strain route: substrate ignored (Formulae 8, 9)"

    t_hoop = max(0.0, t_hoop_raw)
    t_axial = max(0.0, t_axial_raw)

    return {
        "t_hoop_raw": t_hoop_raw,
        "t_axial_raw": t_axial_raw,
        "t_hoop": t_hoop,
        "t_axial": t_axial,
        "t_design": max(t_hoop, t_axial),
        "formula_5_solution": formula5,
        "route": route,
    }


# ----- 7. D/12 VALIDITY CHECK -----


def check_thickness_limit(x, thickness):
    t_design = thickness["t_design"]
    limit = x.D / 12.0

    passed = t_design < limit

    return {"limit": limit, "t_design": t_design, "passed": passed}


# ----- 8. AXIAL EXTENT: OVERLAP AND TAPER (FORMULAE 18-20) -----


def calculate_overlap(x):
    """
    Formulae (18) and (19). For tees the larger dimension of the
    component is used (7.5.13.1).
    """
    diameter = max(x.D, x.Db) if x.component == "tee" else x.D

    geometry_term = sqrt(diameter * x.t)

    if x.defect_type == "slot":
        defect_length = x.defect_length
        lover_raw = 2.0 * geometry_term
        formula = "slot: 2 sqrt(D t) (Formula 18)"

    else:
        defect_length = x.defect_diameter
        circular_limit = 0.5 * geometry_term

        if x.defect_diameter < circular_limit:
            lover_raw = 4.0 * x.defect_diameter
            formula = "circular, small defect: 4 d (Formula 19)"

        else:
            lover_raw = 2.0 * geometry_term
            formula = "circular, large defect: 2 sqrt(D t) (Formula 18)"

    return {
        "defect_type": x.defect_type,
        "formula": formula,
        "defect_axial_length": defect_length,
        "lover_raw": lover_raw,
        # Standard requires the larger of 50 mm or lover
        "lover": max(50.0, lover_raw),
    }


def add_taper(x, overlap, t_final):
    """Taper (5:1) and total repair length (Formula 20)."""
    ltaper = 5.0 * t_final if x.axial_loads_present else 0.0

    total_length = (
        2.0 * overlap["lover"] + overlap["defect_axial_length"] + 2.0 * ltaper
    )

    return {
        **overlap,
        "ltaper_each_end": ltaper,
        "total_repair_length": total_length,
    }


# ----- 9. LAP-SHEAR OVERLAP CHECK (FORMULA 21) -----


def check_formula_21(x, t_axial_design, strains, extent):
    """
    ISO 24817:2017 Formula (21).

    Formula (21) uses the minimum repair laminate thickness for
    axial applied loads. In this calculator this is thickness["t_axial"],
    not the overall maximum design thickness.
    """
    epsilon_a = strains["epsilon_a"]
    required_overlap = 3.0 * x.Ea * epsilon_a * t_axial_design / x.tau
    actual_overlap = extent["lover"]
    passed = actual_overlap > required_overlap
    return {
        "t_axial_design": t_axial_design,
        "required_overlap": required_overlap,
        "actual_overlap": actual_overlap,
        "tau": x.tau,
        "epsilon_a": epsilon_a,
        "passed": passed,
    }


# ----- 10. LIVE-REPAIR INTERFACIAL STRESS (FORMULA 29) -----


def check_interfacial_stress(x, t_design):
    """
    ISO 24817:2017 Formula (29), 7.5.9.3 (live repairs).

    Applies when the pressure after repair is lower than the pressure
    during application (p_after < p_live). The interface tensile stress q
    must be less than the short-term lap shear strength divided by 3.
    T_live, the temperature when the repair is applied, is T_install.
    """
    if x.p_live <= 0:
        return {
            "applicable": False,
            "reason": "p_live = 0 (not a live repair)",
        }

    if x.p_after >= x.p_live:
        return {"applicable": False, "reason": "p_after >= p_live"}

    stiffness_ratio = (x.Es * x.ts) / (x.Es * x.ts + x.Ec * t_design)

    pressure_term = (x.p_live - x.p_after) * (1.0 - stiffness_ratio)

    thermal_term = (
        (x.alpha_c - x.alpha_s)
        * (x.T_install - x.T_after)
        * 2.0
        * x.Ec
        * t_design
        / x.D
    )

    q = pressure_term - thermal_term
    limit = x.tau / 3.0

    return {
        "applicable": True,
        "p_live": x.p_live,
        "p_after": x.p_after,
        "T_live": x.T_install,
        "T_after": x.T_after,
        "t_design": t_design,
        "pressure_term": pressure_term,
        "thermal_term": thermal_term,
        "q": q,
        "limit": limit,
        "passed": q < limit,
    }


# ----- 11. PIPING COMPONENTS (FORMULAE 32, 33) -----


def calculate_component_thickness(x, t_straight):
    """Component thickness: t_straight_pipe * f_th,stress (Formula 32)."""
    factor = COMPONENT_FACTORS[x.component]

    return {
        "component": x.component,
        "f_th_stress": factor,
        "t_straight": t_straight,
        "t_component": t_straight * factor,
    }


def check_tee_pressure(x, strains, t_component):
    """Maximum design pressure for the repair of a tee (Formula 33)."""
    if x.component != "tee":
        return {"applicable": False, "reason": "component is not a tee"}

    p_allowable = (
        2.0 * x.Ec * strains["epsilon_c"] * t_component / (x.D + x.Db)
    )

    return {
        "applicable": True,
        "epsilon_c": strains["epsilon_c"],
        "t_component": t_component,
        "D": x.D,
        "Db": x.Db,
        "p": x.p,
        "p_allowable": p_allowable,
        "passed": x.p <= p_allowable,
    }


# ----- 12. EXTERNAL PRESSURE AND SOIL LOADS (FORMULAE 30, 31) -----


def calculate_external_loads(x, extent):
    """
    ISO 24817:2017 7.5.9.7.

    Formula (30): external pressure or vacuum, p_e.
    Formula (31): soil load on a buried repair.
    l = l_defect + 2 l_over.
    """
    has_pressure = x.p_e is not None and x.p_e > 0
    has_soil = x.burial_depth is not None

    if not (has_pressure or has_soil):
        return {
            "applicable": False,
            "t_pe": None,
            "t_soil": None,
            "t_required": 0.0,
        }

    result = {"applicable": True, "t_pe": None, "t_soil": None}

    if has_pressure:
        length = extent["defect_axial_length"] + 2.0 * extent["lover"]

        # Formula (30)
        result["length"] = length
        result["p_e"] = x.p_e
        result["t_pe"] = (
            2.0 * length * x.D**1.5 * x.p_e / (3.0 * sqrt(2.0) * x.Ec)
        ) ** 0.4

    if has_soil:
        centre = x.burial_depth + x.D / 2.0

        # Formula (31)
        p_soil = (
            4.0
            / (pi * x.D)
            * (x.D * centre - pi * x.D**2 / 8.0 + centre**2 / 3.0)
            * x.gamma_soil
        )

        result["p_soil"] = p_soil
        result["t_soil"] = x.D * (
            3.0 * (1.0 - x.nu**2) * p_soil / (2.0 * x.Ec)
        ) ** (1.0 / 3.0)

    result["t_required"] = max(
        t for t in (result["t_pe"], result["t_soil"]) if t is not None
    )

    return result


def determine_ps(x):
    """
    MAWP of the substrate, p_s.

    A value from a defect assessment (ASME B31G, API 579, BS 7910) is
    used when given. Otherwise p_s = 2 ts sigma_s / (D - ts), the uniform
    remaining-wall approximation of Annex K, Step 7 (conservative).
    """
    if x.ps is not None:
        return x.ps, "input (defect assessment)"

    ps = 2.0 * x.ts * x.allowable_stress / (x.D - x.ts)

    return ps, "calculated: 2 ts sigma_s / (D - ts)"


def calculate_repair(x):
    validate_inputs(x)

    ps_value, ps_source = determine_ps(x)

    x = replace(x, ps=ps_value)

    loads = calculate_equivalent_loads(x)

    strains = calculate_allowable_strains(x)

    if x.design_route == "stress":
        thickness = calculate_stress_thickness(x, loads)

    else:
        thickness = calculate_strain_thickness(x, loads, strains)

    # D/12 check
    thickness_check = check_thickness_limit(x, thickness)

    if not thickness_check["passed"]:
        raise ValueError(
            f"D/12 validity check FAILED: "
            f"t_design = {thickness['t_design']:.4f} mm, "
            f"D/12 = {thickness_check['limit']:.4f} mm. "
            f"The selected thickness is outside the "
            f"validity limit of the selected design equations."
        )

    # Overlap length (independent of the repair thickness)
    overlap = calculate_overlap(x)

    # Formula (32): piping component
    component = calculate_component_thickness(x, thickness["t_design"])

    # Formulae (30) and (31): external loads
    external = calculate_external_loads(x, overlap)

    # Design thickness: maximum of 7.5.4 / 7.5.5 (with Formula 32) and 7.5.9.7
    t_final = max(component["t_component"], external["t_required"])

    if external["t_required"] > component["t_component"]:
        if external["t_pe"] == external["t_required"]:
            governing = "External pressure (Formula 30)"
        else:
            governing = "Soil load (Formula 31)"
    elif component["f_th_stress"] > 1.0:
        governing = "Design loads x component factor (Formula 32)"
    else:
        governing = "Design loads (7.5.4 / 7.5.5)"

    # Repair length with the final thickness (taper)
    extent = add_taper(x, overlap, t_final)

    # Formula (21): axial thickness of the component (t_axial x f_th,stress)
    t_axial_component = thickness["t_axial"] * component["f_th_stress"]
    formula21 = check_formula_21(x, t_axial_component, strains, extent)

    # Formula (29)
    interfacial = check_interfacial_stress(x, t_final)

    # Formula (33)
    tee_check = check_tee_pressure(x, strains, t_final)

    return {
        "inputs": asdict(x),
        "mawp": {"ps": ps_value, "source": ps_source},
        "loads": loads,
        "thickness": thickness,
        "thickness_check": thickness_check,
        "allowable_strains": strains,
        "repair_extent": extent,
        "formula_21": formula21,
        "interfacial_stress": interfacial,
        "component": component,
        "external_loads": external,
        "tee_pressure": tee_check,
        "resin_requirement": required_resin_temperatures(x),
        "final_design": {"t_final": t_final, "governing": governing},
    }


# ----- 13. RESIN THERMAL REQUIREMENT (TABLES 5, 6) -----


def required_resin_temperatures(x):
    """
    Minimum Tg / HDT of the repair resin for Defect Type A.

    Table 5: Tg >= Td + 20 degC or HDT >= Td + 15 degC.
    Table 6 (selected class): Tm = Tg - 20 degC (Class 1 and 2) or
    HDT - 15 degC (Class 3).
    Reported only; the values are not used in the calculation.
    """
    if x.repair_class == 3:
        table_6 = ("HDT", x.T_m + 15.0)
    else:
        table_6 = ("Tg", x.T_m + 20.0)

    return {
        "T_design": x.T_design,
        "T_m": x.T_m,
        "table_5": {"Tg": x.T_design + 20.0, "HDT": x.T_design + 15.0},
        "repair_class": x.repair_class,
        "table_6": table_6,
    }


# ----- 14. REPORT -----


def _section(number, title):
    print(f"\n{number}. {title}")
    print("-" * 48)


def _verdict(passed):
    return "PASS" if passed else "FAIL"


def print_report(result):
    loads = result["loads"]
    thick = result["thickness"]
    limit = result["thickness_check"]
    strains = result["allowable_strains"]
    component = result["component"]
    external = result["external_loads"]
    final = result["final_design"]
    extent = result["repair_extent"]
    formula21 = result["formula_21"]
    interfacial = result["interfacial_stress"]
    tee = result["tee_pressure"]
    resin = result["resin_requirement"]
    inputs = result["inputs"]

    print("\n" + "=" * 68)
    print("COMPOSITE PIPE REPAIR CALCULATION REPORT")
    print("ISO 24817:2017 - Defect Type A")
    print("=" * 68)

    _section(1, "DESIGN ROUTE")
    print(thick["route"])
    print(f"MAWP (p_s): {result['mawp']['ps']:.2f} MPa")
    print(f"  source: {result['mawp']['source']}")

    _section(2, "EQUIVALENT LOADS")
    print(f"Equivalent pressure (p_eq): {loads['p_eq']:.1f} MPa")
    print(f"Equivalent axial load (F_eq): {loads['F_eq']:.1f} N")
    print(f"Equivalent shear/torsion term (q): {loads['q']:.1f}")
    print(f"Pressure branch: {loads['branch']}")

    _section(3, "REPAIR THICKNESS (STRAIGHT PIPE)")
    print(f"Hoop raw thickness: {thick['t_hoop_raw']:.1f} mm")
    print(f"Axial raw thickness: {thick['t_axial_raw']:.1f} mm")
    print(f"Hoop required thickness: {thick['t_hoop']:.1f} mm")
    print(f"Axial required thickness: {thick['t_axial']:.1f} mm")
    print(f"DESIGN THICKNESS (7.5.4 / 7.5.5): {thick['t_design']:.1f} mm")

    if thick["formula_5_solution"] is not None:
        solution = thick["formula_5_solution"]

        print("\nHoop thickness numerical solution (Formula 5):")
        print(f"Iterations: {solution['iterations']}")

        if solution["equation_residual"] is not None:
            print(f"Equation residual: {solution['equation_residual']:.3e}")

    _section(4, "D/12 VALIDITY CHECK")
    print(f"D/12 limit: {limit['limit']:.1f} mm")
    print(f"Design thickness: {limit['t_design']:.1f} mm")
    print("Result: " + _verdict(limit["passed"]))

    _section(5, "ALLOWABLE LAMINATE STRAINS")
    print(f"Design - installation temperature: {strains['delta_T']:.1f} degC")
    print(f"Design temperature Td: {inputs['T_design']:.1f} degC")
    print(f"Upper temperature limit Tm: {inputs['T_m']:.1f} degC")
    print(f"Temperature factor f_T1 (Table 7): {strains['f_T1']:.3f}")
    print(f"Table 9 branch: {strains['table_branch']}")
    print(f"epsilon_c0: {strains['epsilon_c0']:.6f}")
    print(f"epsilon_a0: {strains['epsilon_a0']:.6f}")
    print(
        "Thermal correction circumferential: "
        f"{strains['thermal_correction_c']:.6f}"
    )
    print(f"Thermal correction axial: {strains['thermal_correction_a']:.6f}")
    print(f"Allowable circumferential strain: {strains['epsilon_c']:.6f}")
    print(f"Allowable axial strain: {strains['epsilon_a']:.6f}")

    _section(6, "PIPING COMPONENT THICKNESS FACTOR (FORMULA 32)")
    print(f"Component: {component['component']}")
    print(f"f_th,stress (Table 11): {component['f_th_stress']:.2f}")
    print(f"Straight pipe thickness: {component['t_straight']:.1f} mm")
    print(f"Component thickness: {component['t_component']:.1f} mm")

    _section(7, "EXTERNAL PRESSURE AND SOIL LOADS (FORMULAE 30, 31)")
    if not external["applicable"]:
        print("Not applicable")
    else:
        if external["t_pe"] is not None:
            print(f"External pressure p_e: {external['p_e']:.3f} MPa")
            print(f"Repair length l: {external['length']:.1f} mm")
            print(
                f"External pressure thickness (Formula 30): "
                f"{external['t_pe']:.1f} mm"
            )
        if external["t_soil"] is not None:
            print(f"Soil pressure: {external['p_soil']:.4f} MPa")
            print(
                f"Soil load thickness (Formula 31): "
                f"{external['t_soil']:.1f} mm"
            )

    _section(8, "FINAL DESIGN THICKNESS")
    print(f"FINAL DESIGN THICKNESS: {final['t_final']:.1f} mm")
    print(f"Governing: {final['governing']}")

    _section(9, "AXIAL REPAIR EXTENT")
    print(f"Defect type: {extent['defect_type']}")
    print(f"Defect axial length: {extent['defect_axial_length']:.1f} mm")
    print(f"Overlap equation: {extent['formula']}")
    print(f"Calculated overlap: {extent['lover_raw']:.1f} mm")
    print(f"Applied overlap per end: {extent['lover']:.1f} mm")
    print(f"Taper length per end: {extent['ltaper_each_end']:.1f} mm")

    print("\nREPAIR LENGTH BREAKDOWN")
    print("-" * 48)
    print(f"Left overlap: {extent['lover']:.1f} mm")
    print(f"Defect length: {extent['defect_axial_length']:.1f} mm")
    print(f"Right overlap: {extent['lover']:.1f} mm")
    print(f"Left taper: {extent['ltaper_each_end']:.1f} mm")
    print(f"Right taper: {extent['ltaper_each_end']:.1f} mm")
    print("-" * 48)
    print(f"TOTAL REPAIR LENGTH: {extent['total_repair_length']:.1f} mm")

    _section(10, "LAP-SHEAR OVERLAP CHECK (FORMULA 21)")
    print(f"Lap shear strength (tau): {formula21['tau']:.2f} MPa")
    print(
        f"Axial thickness (x f_th,stress): {formula21['t_axial_design']:.1f} mm"
    )
    print(f"Allowable axial strain: {formula21['epsilon_a']:.6f}")
    print(f"Required overlap: {formula21['required_overlap']:.1f} mm")
    print(f"Available overlap: {formula21['actual_overlap']:.1f} mm")
    print(
        "Lap-shear overlap result (Formula 21): "
        + _verdict(formula21["passed"])
    )

    _section(11, "LIVE-REPAIR INTERFACIAL STRESS (FORMULA 29)")
    if not interfacial["applicable"]:
        print("Not required: " + interfacial["reason"])
    else:
        print(
            f"p_live / p_after: {interfacial['p_live']:.2f} / "
            f"{interfacial['p_after']:.2f} MPa"
        )
        print(
            f"T_live / T_after: {interfacial['T_live']:.1f} / "
            f"{interfacial['T_after']:.1f} degC"
        )
        print(f"Pressure term: {interfacial['pressure_term']:.3f} MPa")
        print(f"Thermal term: {interfacial['thermal_term']:.3f} MPa")
        print(f"Interface tensile stress (q): {interfacial['q']:.3f} MPa")
        print(f"Allowable (tau / 3): {interfacial['limit']:.3f} MPa")
        print(
            "Interfacial stress result (Formula 29): "
            + _verdict(interfacial["passed"])
        )

    _section(12, "TEE PRESSURE LIMIT (FORMULA 33)")
    if not tee["applicable"]:
        print("Not required: " + tee["reason"])
    else:
        print(f"Main / branch diameter: {tee['D']:.1f} / {tee['Db']:.1f} mm")
        print(f"Circumferential design strain: {tee['epsilon_c']:.6f}")
        print(f"Repair thickness: {tee['t_component']:.1f} mm")
        print(f"Design pressure: {tee['p']:.2f} MPa")
        print(f"Maximum allowable pressure: {tee['p_allowable']:.2f} MPa")
        print(
            "Tee pressure limit result (Formula 33): "
            + _verdict(tee["passed"])
        )

    _section(13, "RESIN THERMAL REQUIREMENT (ENGINEERING NOTE)")
    prop, value = resin["table_6"]
    print(f"Design temperature Td: {resin['T_design']:.1f} degC")
    print(
        f"Table 5 (Type A): Tg >= {resin['table_5']['Tg']:.1f} degC  or  "
        f"HDT >= {resin['table_5']['HDT']:.1f} degC"
    )
    print(
        f"Table 6 (Class {resin['repair_class']}, "
        f"Tm = {resin['T_m']:.1f} degC): {prop} >= {value:.1f} degC"
    )
    print("The resin used must have at least these values.")

    print("\n" + "=" * 68)


# ----- 15. EXAMPLE INPUTS -----

if __name__ == "__main__":
    # Validation case: ISO 24817:2017, Annex K, worked example 1 (Type A)
    # 406.4 mm pipeline, 80 % wall loss, Class 3, 10-year life.

    example = RepairInputs(
        # Formulae (5) and (6)
        design_route="substrate_strain",
        # Pipe and substrate
        D=406.4,
        t=12.7,
        ts=2.54,  # 20 % of the wall remains (80 % wall loss)
        Es=207000.0,  # no effect on the result since p_live = 0
        allowable_stress=161.66,
        # ps omitted: calculated as in Step 7 (2.03 MPa)
        # Laminate
        Ec=36000.0,
        Ea=36000.0,
        nu=0.27,
        # Pressure
        p=5.0,
        p_live=0.0,
        # Loads
        Fsh=0.0,
        Mto=0.0,
        Fax=0.0,
        Max=0.0,
        # Piping component (Table 11)
        component="straight_pipe",
        # Defect: 200 mm axial extent, overlap by Formula (18)
        defect_type="slot",
        defect_diameter=None,
        defect_length=200.0,
        # Taper (5:1)
        axial_loads_present=True,
        # Lap shear strength (Annex K: 15 MPa)
        tau=15.0,
        # Table 9 / Formula (10)
        repair_class=3,
        lifetime=10.0,
        T_design=60.0,
        T_install=20.0,
        T_m=60.0,  # Tm = Td in the standard example
        alpha_s=12e-6,
        alpha_c=-1e-6,
        alpha_a=-1e-6,
        short_term_strain_failure=0.02,
    )

    results = calculate_repair(example)

    print_report(results)
