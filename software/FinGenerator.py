import numpy as np
import matplotlib.pyplot as plt
from scipy.integrate import quad

# ==========================================
# 1. PHYSICAL PARAMETERS (Enter required dimensions here)
# ==========================================
L_chassis = 192.0        # mm (Length of the straight linear mechanism)
R_pivot = 8.0            # mm (Rigid offset from pivot axis to start of membrane)
H_membrane = 87.38       # mm (Length of the flexible fin membrane)
R_outer = R_pivot + H_membrane # mm (Total distance from pivot to outer edge)

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
print(f"Straightened Chassis Base: {L_chassis:.2f} mm")
print(f"Inner Edge Material Length (at R={R_pivot}mm): {L_inner_flat:.2f} mm")
print(f"Outer Edge Material Length (at R={R_outer}mm): {L_outer_flat:.2f} mm")
print(f"Required Radial Width: {H_membrane:.2f} mm")
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
