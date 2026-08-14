import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import quad

# ==========================================
# 1. PHYSICAL PARAMETERS (Enter required dimensions here)
# ==========================================
L_chassis = 198.0        # mm (Length of the straight linear mechanism) [OLD: 192.0]
R_pivot = 17.0           # mm (Rigid offset from pivot axis to start of membrane) [OLD: 8.0]

R_Outer = 76.2/2         # mm (Outer diameter of the T200 Propeller) [OLD: 25.0]
R_hub = 40/2             # mm (Hub diameter of the T200 Propeller) [OLD: 8.0]
A_t200_sweep = np.pi * (R_Outer**2 - R_hub**2)  # mm^2 (Cross-sectional area of the fin membrane at the pivot)
theta_fin_sweep = 50.0   # degrees (Max sweep angle of the fin membrane) [OLD: 50.0]
R_outer = np.sqrt((A_t200_sweep / (np.pi * theta_fin_sweep/360)) + R_pivot**2)   # mm (Length of the flexible fin membrane) [OLD: 87.38]

H_membrane = R_outer - R_pivot # mm (Radial width of the flexible fin membrane) [OLD: 79.38]

# Sweep angle parameters for the undulating fin motion
theta_max_deg = 25.0     # degrees (Max sweep angle per side)
theta_max = np.radians(theta_max_deg)
num_waves = 1.0          # Number of full sine waves along the chassis length

# ==========================================
# 2. CALCULATE EXACT FLAT MATERIAL LENGTHS FOR FIN MEMBRANE
# ==========================================
# Derivative of the angle function: d(theta)/dx - Calculates how fast the fin twists along the length of the fin edge
def d_theta_dx(x):
    k = 2 * np.pi * num_waves / L_chassis
    return theta_max * k * np.cos(k * x)

# Arc length integral function: sqrt(1 + (r * d_theta/dx)^2)
def calc_material_length(radius):
    # integrand(x) - Using pythagoras via tiny triangles to calculate distances along the edge of the Fin Wave
    def integrand(x):
        return np.sqrt(1 + (radius * d_theta_dx(x))**2)
    length, _ = quad(integrand, 0, L_chassis)
    return length

L_inner_flat = calc_material_length(R_pivot)
L_outer_flat = calc_material_length(R_outer)

print("--- 2D FLAT PATTERN DIMENSIONS ---")
print(f"Straightened Chassis Base: {L_chassis:.4f} mm")
print(f"Inner Edge Material Length (at R={R_pivot}mm): {L_inner_flat:.4f} mm")
print(f"Outer Edge Material Length (at R={R_outer}mm): {L_outer_flat:.4f} mm")
print(f"Outer Radial Width: {R_outer:.4f} mm")
print(f"Actual Fin Radial Width: {H_membrane:.4f} mm")
print("----------------------------------\n")

# 1. Correct the Fin Width (Fixing the bug)
W_fin = R_outer - R_pivot 

# 2. Calculate the Flat Pattern Angle (in radians)
alpha_rad = (L_outer_flat - L_inner_flat) / W_fin

# 3. Convert Angle to Degrees for Fusion 360
alpha_deg = np.degrees(alpha_rad)

# 4. Calculate the True 2D Flat Inner Radius
R_flat_inner = L_inner_flat / alpha_rad

print(f"--- FUSION 360 CAD PARAMETERS ---")
print(f"Fin Radial Width: {W_fin:.4f} mm")
print(f"Sketch Sweep Angle: {alpha_deg:.4f} deg")
print(f"Sketch Inner Radius: {R_flat_inner:.4f} mm")
print("----------------------------------\n")

# ==========================================
# 3. 3D VISUALIZATION OF BUCKLED FIN
# ==========================================
# Create a grid of points (x along chassis, r along fin ray)
x_vals = np.linspace(0, L_chassis, 100)
r_vals = np.linspace(R_pivot, R_outer, 30)
X, R = np.meshgrid(x_vals, r_vals)

# Calculate the pivot angle for every position x
k = 2 * np.pi * num_waves / L_chassis
Theta = theta_max * np.sin(k * X)

# Map (x, r) coordinates into 3D Space (X, Y, Z)
# X is the longitudinal axis (the robot chassis)
# Y is the lateral deflection (side-to-side sweeping motion)
# Z is the vertical drop (distance downward from the pivot axis)
Y = R * np.sin(Theta)
Z = -R * np.cos(Theta) # Negative so the fin hangs downward

# Create the 3D plot
fig = plt.figure(figsize=(12, 8))
ax = fig.add_subplot(111, projection='3d')

# Plot the flexible fin membrane surface
surf = ax.plot_surface(X, Y, Z, cmap='viridis', edgecolor='none', alpha=0.9)

# Draw the straight chassis line (Pivot Axis)
ax.plot([0, L_chassis], [0, 0], [0, 0], color='red', linewidth=3, label='Pivot Axis (Mechanism)')

# Formatting for an engineering schematic
ax.set_title('3D Kinematic Envelope: Undulating Fin\n(Membrane starts 8mm from Pivot Axis)', fontsize=14)
ax.set_xlabel('Chassis Length X (mm)')
ax.set_ylabel('Lateral Deflection Y (mm)')
ax.set_zlabel('Depth Z (mm)')

# Ensure axes are scaled equally so the fin doesn't look stretched
ax.set_box_aspect((L_chassis, np.max(Y)-np.min(Y), np.max(Z)-np.min(Z)))

plt.legend()
plt.tight_layout()
plt.show()
