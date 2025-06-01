import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec

def generate_pdf_report(
    file_path: str,
    beaconer_pubkey: str,
    witness_pubkey: str,
    terrain_profile_elevations,
    terrain_profile_distances,
    tx_antenna_height_m: float,
    rx_antenna_height_m: float,
    frequency_hz: float,
    itm_loss_profile,
    tx_power_dBm: float,
    tx_gain_dB: float,
    rx_gain_dB: float,
    measured_rssi: float,
    std_dev: float,
    samples: int,
):
    print("LP: ")
    print(itm_loss_profile)
    # landscape 8.5x11 page with a top title, 2 plots, and a table
    fig = plt.figure(figsize=(11, 8.5))
    fig.subplots_adjust(top=0.85, bottom=0.2, left=0.07, right=0.97, hspace=0.5)

    gs = GridSpec(2, 2, height_ratios=[3, 1])
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    table_ax = fig.add_subplot(gs[1, :])
    table_ax.axis('off')  # no axes for the metadata table

    distances_km = np.array(terrain_profile_distances) / 1e3
    elevations = np.array(terrain_profile_elevations)

    # Line of Sight
    line = np.linspace(
        elevations[0] + tx_antenna_height_m,
        elevations[-1] + rx_antenna_height_m,
        len(distances_km)
    )

    # Fresnel zone
    c = 2.998e8
    wavelength = c / frequency_hz
    D = terrain_profile_distances[-1]
    d1 = np.array(terrain_profile_distances)
    d2 = D - d1
    fresnel_radius = np.sqrt((wavelength * d1 * d2) / D)
    upper = line + fresnel_radius
    lower = line - fresnel_radius

    # Terrain profile
    ax1.plot(distances_km, elevations, label="Terrain Elevation")
    ax1.plot(distances_km, line, linestyle='--', label="Line of Sight")
    ax1.fill_between(distances_km, lower, upper, alpha=0.3, color='gray', label="1st Fresnel Zone")
    ax1.set_xlabel("Distance (km)")
    ax1.set_ylabel("Elevation (m)")
    ax1.set_title("Terrain Profile")
    ax1.legend()
    ax1.grid(True)

    # ITM loss profile
    dx = np.array(terrain_profile_distances[1:]) / 1e3
    loss_profile = -1.0 * np.array(itm_loss_profile)
    erssi = tx_power_dBm + tx_gain_dB + rx_gain_dB - itm_loss_profile[-1]

    ax2.plot(dx, loss_profile, label="ITM Loss Profile")
    ax2.axhline(-138, linestyle="--", color="green", label="Concentrator Sensitivity")
    ax2.errorbar(
        dx[-1],
        measured_rssi,
        yerr=2.0 * std_dev,
        fmt='x',
        color='red',
        ecolor='black',
        elinewidth=2,
        capsize=5,
        label="Measured RSSI (2σ)"
    )
    ax2.set_xlabel("Distance (km)")
    ax2.set_ylabel("RSSI (dBm)")
    ax2.set_title("ITM Loss vs Measured RSSI")
    ax2.legend()
    ax2.grid(True)

    # Top-level title
    fig.suptitle(
        f"ITM Classification Report\nBeaconer: {beaconer_pubkey}\nWitness: {witness_pubkey}",
        fontsize=14,
        y=0.97
    )

    # Metadata table
    table_data = [
        ["Tx Power (dBm)", tx_power_dBm],
        ["Tx Gain (dB)", tx_gain_dB],
        ["Rx Gain (dB)", rx_gain_dB],
        ["Freq (MHz)", round(frequency_hz / 1e6, 2)],
        ["Distance (km)", round(D / 1000.0, 3)],
        ["Measured RSSI (dBm)", round(measured_rssi, 1)],
        ["Std Dev (dB)", round(std_dev, 2)],
        ["ITM Model Loss (dB)", round(itm_loss_profile[-1], 2)],
        ["Estimated RSSI (dBm)", round(erssi, 1)],
        ["Residual (dB)", round(erssi - measured_rssi, 2)],
        ["Samples", samples],
    ]

    table_ax.table(
        cellText=table_data,
        colLabels=["Metric", "Value"],
        loc="center",
        cellLoc="center",
        colWidths=[0.3, 0.15]
    )

    with PdfPages(file_path) as pdf:
        pdf.savefig(fig)
        plt.close(fig)
        
    plt.close("all")
