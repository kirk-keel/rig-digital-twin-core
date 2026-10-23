# Rig Digital Twin Core - Governing Physics Formulations

This document details the governing petroleum engineering equations, boundary conditions, and mathematical algorithms implemented in the deterministic physics calculation engine.

---

## 1. Herschel-Bulkley Non-Newtonian Rheology (API RP 13D)

The Herschel-Bulkley (Yield-Power-Law) constitutive equation relates shear stress $\tau$ to shear rate $\dot{\gamma}$:

$$\tau = \tau_0 + K \dot{\gamma}^n \quad (\text{for } \tau > \tau_0)$$

Where:
- $\tau_0$ = Yield stress ($\text{lbf}/100\text{ ft}^2$)
- $K$ = Consistency index ($\text{lbf}\cdot\text{s}^n/100\text{ ft}^2$)
- $n$ = Flow behavior index (dimensionless, $n < 1$ represents shear-thinning behavior)

### API RP 13D Parameter Regression
Using standard 6-speed Fann 35 rotational viscometer dial readings ($\theta_{600}, \theta_{300}, \theta_{200}, \theta_{100}, \theta_6, \theta_3$):
$$\tau_0 = 2\theta_3 - \theta_6$$
$$n = \frac{\log_{10}[(\theta_{600} - \tau_0)/(\theta_{300} - \tau_0)]}{\log_{10}(1022 / 511)} = 3.322 \log_{10}\left(\frac{\theta_{600} - \tau_0}{\theta_{300} - \tau_0}\right)$$
$$K = \frac{\theta_{300} - \tau_0}{511^n}$$

---

## 2. Annular and Pipe Hydraulics

### Pipe & Annular Shear Rate and Effective Viscosity
For non-Newtonian flow in pipes ($d_i$) and annular conduits ($d_2 - d_1$):

$$\dot{\gamma}_{\text{pipe}} = \left(\frac{3n + 1}{4n}\right) \frac{8 v}{d_i}$$
$$\dot{\gamma}_{\text{annulus}} = \left(\frac{2n + 1}{3n}\right) \frac{12 v}{d_2 - d_1}$$

Effective viscosity $\mu_{\text{eff}}$ in centipoise (cP):
$$\mu_{\text{eff}} = 100 \cdot K \cdot \dot{\gamma}^{n-1} + \frac{100 \cdot \tau_0}{\dot{\gamma}}$$

### Generalized Reynolds Number ($N_{\text{Re}}$)
$$N_{\text{Re}} = \frac{928 \cdot \rho \cdot v \cdot d_{\text{hyd}}}{\mu_{\text{eff}}}$$

### Fanning Friction Factor ($f$)
- **Laminar Flow** ($N_{\text{Re}} < 2100$):
  $$f = \frac{16}{N_{\text{Re}}}$$
- **Turbulent Flow** ($N_{\text{Re}} \ge 2100$, Colebrook-White / Dodge-Metzner approximation):
  $$f = \frac{a}{N_{\text{Re}}^b} \quad \text{where } a = \frac{\log_{10}(n) + 3.93}{50}, \quad b = \frac{1.75 - \log_{10}(n)}{7}$$

### Frictional Pressure Drop
$$\Delta P_f = \frac{2 \cdot f \cdot \rho \cdot v^2 \cdot \Delta L}{25.8 \cdot d_{\text{hyd}}}$$

---

## 3. Bit Nozzle Jet Hydraulics

For a drill bit equipped with $N$ standard nozzles of diameter $d_i$ in 32nds of an inch:

$$\text{TFA} = \frac{\pi}{4 \times 32^2} \sum_{i=1}^N d_i^2 = \sum_{i=1}^N \frac{d_i^2}{1303.8} \quad [\text{in}^2]$$

Bit nozzle exit velocity ($v_{\text{bit}}$):
$$v_{\text{bit}} = \frac{Q}{3.117 \cdot \text{TFA}} \quad [\text{ft/s}]$$

Bit nozzle pressure drop ($\Delta P_{\text{bit}}$) assuming discharge coefficient $C_d \approx 0.95$:
$$\Delta P_{\text{bit}} = \frac{\rho \cdot Q^2}{10858 \cdot C_d^2 \cdot \text{TFA}^2} \quad [\text{psi}]$$

Hydraulic Jet Impact Force:
$$F_{\text{impact}} = 0.0173 \cdot C_d \cdot Q \cdot \sqrt{\rho \cdot \Delta P_{\text{bit}}} \quad [\text{lbf}]$$

---

## 4. Burkhardt Dynamic Surge and Swab Kinematics

When tripping pipe at axial velocity $v_p$ through mud, fluid clings to the pipe surface with clinging factor $K_c \in [0.35, 0.48]$:

$$v_{\text{fluid, eff}} = v_p \cdot \left[ \frac{\sigma^2}{\sigma^2 - 1} - K_c \right]$$

Where the diameter ratio is $\sigma = d_{\text{hole}} / d_{\text{pipe, od}}$.
The induced surge (+) or swab (-) pressure drop is computed from the effective annular velocity perturbation:

$$\Delta P_{\text{surge/swab}} = \frac{2 \cdot f \cdot \rho \cdot v_{\text{fluid, eff}}^2 \cdot \Delta L}{25.8 \cdot (d_{\text{hole}} - d_{\text{pipe, od}})}$$

---

## 5. 3D Johancsik Soft-String Torque & Drag

Resolving pipe axial tension $T(s)$ and dogleg severity $\beta$:

$$\Delta T = w_{\text{buoy}} \cdot \Delta L \cdot \cos\bar{\theta} \pm \mu_f \cdot N$$
$$\Delta \text{Torque} = \mu_f \cdot N \cdot \left(\frac{r_{\text{tooljoint}}}{12}\right)$$

Where contact normal force $N$ is:
$$N = \sqrt{ (T \cdot \Delta\phi \cdot \sin\bar{\theta})^2 + (T \cdot \Delta\theta + w_{\text{buoy}} \cdot \Delta L \cdot \sin\bar{\theta})^2 }$$

### Dawson-Paslay Sinusoidal Buckling Threshold:
$$F_{\text{crit, sin}} = 2 \sqrt{\frac{E \cdot I \cdot w_{\text{buoy}} \cdot \sin\bar{\theta}}{r_{\text{clearance}}}}$$

### Lubinski Helical Buckling Threshold:
$$F_{\text{crit, hel}} = 2 \cdot \sqrt{2} \cdot F_{\text{crit, sin}} \approx 2.83 \cdot \sqrt{\frac{E \cdot I \cdot w_{\text{buoy}} \cdot \sin\bar{\theta}}{r_{\text{clearance}}}}$$

---

## 6. Hydraulic Transient Waterhammer (Joukowsky Equation)

For an acoustic wave propagating through drill fluid at speed of sound $c \approx 4200\text{ ft/s}$:

$$\Delta P_{\text{surge, psi}} = \frac{\rho\,[\text{ppg}] \cdot c\,[\text{ft/s}] \cdot \Delta v\,[\text{ft/s}]}{619.34}$$

*(The constant $619.34$ is derived rigorously from SI units: $1\text{ ppg} = 119.826\text{ kg/m}^3$, $1\text{ ft/s} = 0.3048\text{ m/s}$, $1\text{ psi} = 6894.76\text{ Pa}$)*.

---

## 7. Dynamic Eaton Pore Pressure Prediction

Using corrected $d$-exponent ($d_{xc}$) normalized against the Normal Compaction Trendline ($d_{xcn}$):

$$P_p = \text{OBG} - (\text{OBG} - P_{pn}) \left( \frac{d_{xc}}{d_{xcn}} \right)^{1.2}$$

Where:
- $\text{OBG}$ = Overburden gradient (typically $18.5 - 19.2\text{ ppg}$)
- $P_{pn}$ = Normal pore pressure gradient ($8.65\text{ ppg}$ in Gulf of Mexico)
- $d_{xc} = \frac{\log_{10}(ROP / (60 \cdot RPM))}{\log_{10}(12 \cdot WOB / (10^6 \cdot d_{\text{bit}}))} \cdot \left(\frac{\rho_{\text{normal}}}{\rho_{\text{mud}}}\right)$

---

## 8. IADC / API-59 Well Control Kill Sheet Formulas

When a kick occurs and the well is shut in:
- **Kill Mud Weight**:
  $$\text{KMW} = \rho_{\text{curr}} + \frac{\text{SIDPP}}{0.052 \cdot \text{TVD}}$$
- **Initial Circulating Pressure**:
  $$\text{ICP} = \text{SCRP} + \text{SIDPP}$$
- **Final Circulating Pressure**:
  $$\text{FCP} = \text{SCRP} \cdot \left(\frac{\text{KMW}}{\rho_{\text{curr}}}\right)$$
- **Maximum Allowable Annular Surface Pressure**:
  $$\text{MAASP} = 0.052 \cdot (\text{LOT}_{\text{ppg}} - \rho_{\text{curr}}) \cdot \text{TVD}_{\text{shoe}}$$
