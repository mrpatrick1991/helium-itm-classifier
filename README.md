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
4) Compile `geoprop-py` using: ```cd geoprop-py && maturin build```
5) Install the compiled binary using `pip install geoprop-py/target/wheels/geoprop-0.1.0-cp313-cp313-macosx_11_0_arm64.whl`. Replace the name of the `.whl` file with the one built automatically for your platform.
6) Make the pipeline scripts executable: `chmod +x scripts/ *.sh`
7) Copy the `.env.template` file to `.env`: `cp .env.template .env`, make any desired configuration changes.
8) 

