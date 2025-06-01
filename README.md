# helium-itm-classifier

Detect spoofed connections on the Helium IOT network using the ITM radio propagation model and https://github.com/JayKickliter/geoprop-py.

# About

This project implements a batch-processing job which evaluates links between transmitters (beaconers) and receivers (witnesses) on the Helium IoT (internet of things) network. Hotspots on the network are rewarded by issuing HNT tokens based on the number of successful beaconer-witness pairs. Some hotspots are asserted in incorrect locations, or forward radio packets over the internet to receive rewards without providing useful coverage to the network. The ITM model is used to estimate the expected signal loss between a beaconer and witness and compare to the measured RSSI (received signal strength indication). Pairs of beaconers and witnesses which consistently outperform the expected loss due to terrain elevation and distance are flagged.

# Requirements

* Connection to Helium ArangoDB ETL (see the documentation here for how to obtain this: https://github.com/heliumiotgrants/helium-iot-grants/tree/main/milestones/docs)
* Rust (https://www.rust-lang.org/tools/install)
* Python > 3.8
* GNU parallel
* A UNIX-like operating system (Mac and Liunux are tested.)

# Installation

1) Forward port 8529 from the ArangoDB ETL server by adding the following to your `.ssh/config`:
   
  ```Host sever_name
	   HostName  server_ip_address
	   User your_username
	   LocalForward 8529 localhost:8529
```

2) Create a virtual environment and install the package requirements:

   ```python -m venv .venv
      source .venv/bin/activate
      pip install -r requirements.txt```   
3) Install Rust: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
4) Obtain the 3-arcsecond NASA SRTM terrain tiles following the instructions here: https://github.com/heliumiotgrants/helium-iot-grants/tree/main/milestones/docs
5) Install GNU Parallel () using: `brew install parallel` or the equivalent for your operating system. 
6) Compile `geoprop-py` using: ```cd geoprop-py && maturin build```
7) Install the compiled binary using `pip install geoprop-py/target/wheels/geoprop-0.1.0-cp313-cp313-macosx_11_0_arm64.whl`. Replace the name of the `.whl` file with the one built automatically for your platform.
8) Make the pipeline scripts executable: `chmod +x scripts/ *.sh`
9) Copy the `.env.template` file to `.env`: `cp .env.template .env`, make any desired configuration changes.

# Running

The pipeline is run using `./run_pipeline.sh`. Batches of hotspot pubkeys are downloaded from the ArangoDB instance and stored in `hotspots.` Beaconer-witnesss pairs for hotspot pubkey are downloaded from ArangoDB and the reported average RSSI is compared to the expected loss based on the ITM model and asserted locations, antenna gains, and elevations. Hotspots which outperform the model by a significant margin (configurable by setting  `THRESHOLD_DB` in `.env`) are flagged and written to a csv of beaconer, witness pubkeys in `itm_classifier_output.csv`. 

# Data Interpretation and Operating Principles

Radio signals weaken as they propagate through space. This signal loss, also known as path loss, varies predictably based on the distance between transmitter and receiver and the terrain.

One widely used model for predicting this signal loss is the Irregular Terrain Model (ITM) — [see ITM overview](https://its.ntia.gov/software/itm). ITM is a standard in the telecommunications industry for modeling radio propagation. Accurate predictions with ITM require a reliable digital elevation model (DEM). In this project, we use the NASA SRTM dataset ([SRTM on Earthdata](https://www.earthdata.nasa.gov/data/instruments/srtm)), which provides near-global terrain elevation data at a resolution of 90 meters per pixel.

Our implementation uses the open-source library [geoprop-py](https://github.com/JayKickliter/geoprop-py), which itself is based on the original ITM reference implementation: [NTIA ITM GitHub](https://github.com/NTIA/itm).

## How the Classifier Works

This classifier compares:
- The predicted signal loss (from ITM, based on terrain and distance), and
- The reported RSSI (Received Signal Strength Indicator) from real-world transmissions.

Because terrain and distance impose a hard lower bound on how much signal loss is physically possible, the comparison allows us to flag transmissions that appear too good to be true, by  significantly outperforming the ITM prediction. This is effective because obstacles not included in the DEM (such as windows, trees, or buildings) degrade the signal below the minimum set by the ITM model. The key assumption is that since packet-replay attackers (see: https://github.com/heliumiotgrants/helium-iot-grants/blob/main/milestones/docs/attacks.md) do not know the location of the transmitting hotspots, they must make a guess as to the signal strength to report. This guess cannot take into account the terrain, but must also be above the sensitivity threshold for the radio receivers.

## Outputs

Each flagged beaconer-witness pair is recorded in a csv file for inclusion in the community denylist run by Nova Labs. Additionally, a PDF "report card" is generated for the worst pair for each hotspot. The report cards show the terrain profile between the transmitter and receiver, as well as the model loss between them. The following example shows two hotspots with significant terrian obstructions:

<img width="1398" alt="image" src="https://github.com/user-attachments/assets/b8249492-333e-4a53-8d86-ff9165bcbd87" />

In this example, the reported RSSI (approximately -130 dBm) is well above both the value predicted by the model for this link (-230 dBm) as well as the best-case sensitivity limit for the radio receiver (approximately -140 dBm for LoRa concentrators). Based on the asserted locations, this link cannot physically occur. 

## Sample Data

A complete run for the time period between April 21 and May 5th 2025 produced the following list of flagged beaconer->witness pairs and report cards:

https://drive.google.com/file/d/1nzr3HBq5-cm2yZaNsFmlID3eeNqhmDgM/view?usp=sharing

https://drive.google.com/file/d/1fUn3X8WbWuNowPatlAmT3x-y67cV4bqn/view?usp=sharing


