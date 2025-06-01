from arango import ArangoClient
import numpy as np
import polars as pl
from typing import List, Dict
import logging
import time
import h3
import logging
import polars as pl
from geoprop import Tiles, Itm, Profile, Point

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def _validate_model_parameters(
    tx_loc: Point,
    rx_loc: Point,
    profile: Profile,
    freq_hz: float,
    signal_hist: Dict[int, int],
):
    """
    Validates input parameters for the ITM model.

    This function performs sanity checks and model constraints on the provided transmitter and 
    receiver locations, terrain profile, operating frequency, and observed signal histogram.

    Parameters
    ----------
    tx_loc : Point
        The location of the transmitter, including latitude, longitude, and antenna height in meters.
    rx_loc : Point
        The location of the receiver, including latitude, longitude, and antenna height in meters.
    profile : Profile
        Terrain profile between transmitter and receiver, containing distances and elevations.
    freq_hz : float
        Carrier frequency in Hz. Must be within the expected LoRaWAN range of 400–1000 MHz.
    signal_hist : Dict[int, int]
        Histogram of observed RSSI values. Keys are 10x RSSI values (e.g., -850 for -85 dBm),
        and values are occurrence counts.

    Raises
    ------
    ValueError
        If any input value is invalid or outside model-compatible ranges.
    """

    # Validate coordinates
    for label, loc in [("tx", tx_loc), ("rx", rx_loc)]:
        if not (-90 <= loc.lat <= 90):
            raise ValueError(f"Invalid latitude for {label}: {loc.lat}")
        if not (-180 <= loc.lon <= 180):
            raise ValueError(f"Invalid longitude for {label}: {loc.lon}")
        if loc.alt < 0 or loc.alt > 50: # ITM model will not compute for values larger than this, or negative
            raise ValueError(f"Invalid asserted height for {label}: {loc.alt}")
        
    # Check the terrain profile between transmitter and receiver.
    if profile is None:
        raise ValueError("Terrain profile generation failed")
    if len(profile.distances()) < 2:
        raise ValueError("Terrain profile is too short")

    # Check that the frequency falls within the expected range for LoRaWAN signals (400 to 1000 MHz).
    if (freq_hz >= 1000e6 or freq_hz <= 400e6):
        raise ValueError(f"Frequency out of expected range: {freq_hz}")

    # Check there is there data in the signal histogram
    if not isinstance(signal_hist, dict) or len(signal_hist) == 0:
        raise ValueError("Invalid or empty signal histogram")

def _fetch_edge_data(
    db: ArangoClient.db,
    witness_pubkeys: List[str],
    beaconer_pubkeys: List[str] = [],
    limit: int = 10
) -> pl.DataFrame:
    """
    Fetches asserted link data between beaconers (transmitters) and witnesses (receivers) from ArangoDB.

    This function queries the `witnesses` edge collection in ArangoDB to retrieve link assertions
    between specified beaconer and witness hotspots. It returns key parameters needed for 
    propagation modeling and residual analysis, including positions, antenna heights, gains, 
    frequencies, and observed RSSI histograms.

    Parameters
    ----------
    db : ArangoClient.db
        An active ArangoDB database client instance.
    witness_pubkeys : List[str]
        A list of hotspot public keys representing the receiving nodes (witnesses).
    beaconer_pubkeys : List[str], optional
        A list of hotspot public keys representing the transmitting nodes (beaconers).
        If omitted, all beaconers linked to the specified witnesses are returned.
    limit : int, optional
        Maximum number of beaconer links to return per witness (default is 10).

    Returns
    -------
    pl.DataFrame
        A Polars DataFrame containing fields:
        - `beaconer`: Document ID of the transmitting hotspot
        - `witness`: Document ID of the receiving hotspot
        - `asserted_pair`: Dictionary of asserted link properties, including coordinates,
          elevation, gain, frequency, and RSSI histogram

        Returns an empty DataFrame if no valid data is found.
"""
    witness_doc_ids = [f"hotspots/{pubkey}" for pubkey in witness_pubkeys]
    beaconer_doc_ids = [f"hotspots/{pubkey}" for pubkey in beaconer_pubkeys]
    
    aql_query = """
        FOR witness_doc_id IN @witness_doc_ids
        LET matches = (
            FOR wc IN witnesses
                FILTER wc._to == witness_doc_id
                """ + (
                    "FILTER wc._from IN @beaconer_doc_ids" if beaconer_doc_ids else ""
                ) + """
                SORT wc._to DESC
                LIMIT @max_witnesses
                RETURN {
                    beaconer: wc._from,
                    witness: wc._to,
                    asserted_pair: LAST(wc["asserted_pairs"])
                }
        )
        FOR item IN matches
            RETURN item
    """

    logger.info(f"Downloading ArangoDB data for {len(witness_pubkeys) + len(beaconer_pubkeys)} hotspot pubkeys.")

    bind_vars = {
        "witness_doc_ids": witness_doc_ids,
        "max_witnesses": limit
    }
    if beaconer_doc_ids:
        bind_vars["beaconer_doc_ids"] = beaconer_doc_ids

    query_start_time = time.perf_counter()
    cursor = db.aql.execute(aql_query, bind_vars=bind_vars)
    query_end_time = time.perf_counter()
    query_results = list(cursor)
    logger.info(
        f"Arango query returned {len(query_results)} rows of beaconer->witness data in {query_end_time - query_start_time:.3f} seconds."
    )

    return(pl.from_dicts(query_results) if len(query_results) else pl.DataFrame())

def compute_residuals(
    db: ArangoClient.db,
    itm_model: Itm,
    tiles: Tiles,
    witness_pubkeys: List[str],
    beaconer_pubkeys: List[str] = [],
    max_witnesses: int = 10,
    min_samples: int = 10,
    min_distance_km: float = 3.0,
    threshold_db: float = -15.0,
    h3_search_radius: int = 3,
    compute_loss_profile: bool = False
) -> pl.DataFrame:
    """
    Computes ITM residuals between asserted beaconer-witness hotspot links.

    For each asserted link, this function calculates the path loss using the ITM model,
    then compares it to the measured average loss inferred from the RSSI histogram and 
    device parameters. If the residual is below a given threshold, and the data meets
    statistical and geographic requirements, the link is flagged as an "edge" and returned.

    Parameters
    ----------
    db : ArangoClient.db
        A connected ArangoDB database instance.
    itm_model : Itm
        An initialized ITM path loss model instance.
    tiles : Tiles
        Terrain tile handler used for elevation and profile calculations.
    witness_pubkeys : List[str]
        Public keys for receiving hotspots (witnesses).
    beaconer_pubkeys : List[str], optional
        Public keys for transmitting hotspots (beaconers). If empty, all linked transmitters are considered.
    max_witnesses : int, optional
        Maximum number of witness edges to evaluate per witness (default is 10).
    min_samples : int, optional
        Minimum number of RSSI samples required for statistical validity (default is 10).
    min_distance_km : float, optional
        Minimum distance between transmitter and receiver in kilometers to consider a valid link (default is 3.0).
    threshold_db : float, optional
        Threshold residual in dB below which a link is considered to outperform the model (default is -15.0).
    h3_search_radius : int, optional
        Radius in H3 cells (resolution 8) to search around asserted location for best terrain elevation (default is 3).

    Returns
    -------
    pl.DataFrame
        A Polars DataFrame where each row represents a link with computed parameters:
        - Beaconer/witness metadata
        - ITM loss and measured RSSI loss
        - Residual
        - Edge flag
        - Terrain profile details

        An empty DataFrame is returned if no links meet the criteria.
    """


    logger.info(f"Computing ITM model residuals for {len(witness_pubkeys)} hotspot pubkeys.")

    results = []
    edge_data = _fetch_edge_data(db,witness_pubkeys,beaconer_pubkeys,limit=max_witnesses)
    for row in edge_data.rows(named=True): # evaluate each row, which is a beaconer -> witness pair with asserted location and measured signal data.
        edge_flag = False # True if a given TX/RX pair outperforms the ITM model by the provided threshold across the specified number of samples.

        beaconer_pubkey = row["beaconer"].strip("hotspots/")
        witness_pubkey = row["witness"].strip("hotspots/")
        tx_rx_pair = row["asserted_pair"]

        # Null result (edge not flagged) for hotspot pairs without asserted locations
        if not tx_rx_pair:
            logger.info(
                f"""No asserted coordinates for beaconer-witness pair {beaconer_pubkey}->{witness_pubkey}."""
            )
            continue # evaluate the next beaconer -> witness pair. 
    
        # clamp the asserted antenna heights to values which are compatible with the ITM model. 
        beaconer_antenna_height = min(max(tx_rx_pair["beaconer_elevation"], 1.0), 50.0)
        witness_antenna_height = min(max(tx_rx_pair["witness_elevation"], 1.0), 50.0)

        # owners may place hotspots anywhere within approximately 1 res 8 h3 of the asserted location, 
        # assume the highest spot within this radius is the actual location for each beaconer and witness.

        beaconer_h3 = h3.latlng_to_cell(*list(reversed(tx_rx_pair["beaconer_geo_loc"])), res=8)
        witness_h3 = h3.latlng_to_cell(*list(reversed(tx_rx_pair["witness_geo_loc"])), res=8)

        beaconer_neighborhood = [Point(*coords, beaconer_antenna_height) for coords in [h3.cell_to_latlng(cell) for cell in h3.grid_ring(beaconer_h3, h3_search_radius)]]
        witness_neighborhood = [Point(*coords, witness_antenna_height) for coords in [h3.cell_to_latlng(cell) for cell in h3.grid_ring(witness_h3, h3_search_radius)]]

        tx_loc = max(beaconer_neighborhood, key=tiles.elevation)
        rx_loc = max(witness_neighborhood, key=tiles.elevation)

        freq_hz = tx_rx_pair["beaconer_freq"]    # transmitter frequency in Hz

        signal_hist = {
            int(k): (v if isinstance(v, (int, float)) and v is not None else 0)
            for k, v in tx_rx_pair["signal_hist"].items()
        }

        # compute mean and standard deviation of the RSSI histogram
        bins = np.array([k / 10.0 for k in signal_hist.keys()]) # bins are stored in x10 dBm units, normalize
        counts = np.array(list(signal_hist.values()))

        profile = tiles.profile(tx_loc, rx_loc)  # terrain profile in meters

        try:
            _validate_model_parameters(tx_loc, rx_loc, profile, freq_hz, signal_hist)
        except ValueError as e:
            logger.info(
                f"""Invalid assertion data for beaconer / witness pair {beaconer_pubkey}->{witness_pubkey},
                        exception was: {str(e)}"""
            )
            continue

        if np.sum(counts) == 0:
            logger.warning(f"All signal histogram weights are zero for pair {beaconer_pubkey}->{witness_pubkey}. Skipping.")
            continue

        rssi_mean = np.average(bins, weights=counts)
        rssi_variance = np.average((bins - rssi_mean) ** 2, weights=counts)
        rssi_std_dev = np.sqrt(rssi_variance)

        # if selected, compute the loss as a function of distance between the beaconer and witness.
        # this is computationally expensive so is skipped during edge classification.
        if (compute_loss_profile):
            try:
                logging.info(f"""computing ITM loss profile for {beaconer_pubkey}->{witness_pubkey}""")
                itm_loss_profile = [dB for dB in itm_model.path(profile, freq_hz)]
                itm_loss = itm_loss_profile[-1]
            except ValueError as e:
                logger.warning(f"""Error computing ITM loss profile for {beaconer_pubkey}->{witness_pubkey}, skipping. Error was {str(e)}""")
                continue
        else:
            try:
                itm_loss = itm_model.p2p(profile, freq_hz)  
                itm_loss_profile = None
            except ValueError as e:
                logger.warning(f"""Error computing ITM point to point loss for {beaconer_pubkey}->{witness_pubkey}, skipping. Error was {str(e)}""")
                continue

        measured_loss = -1.0 * (
            rssi_mean
            - tx_rx_pair["beaconer_gain"] / 10.0
            - tx_rx_pair["beaconer_tx_power"]
            - tx_rx_pair["witness_gain"] / 10.0
        )  # measured average loss in dB

        residual = float(
            measured_loss - itm_loss
        )  # mean difference between ITM model in dB

        if (sum(counts) >= min_samples and residual < threshold_db and profile.distances()[-1]/1e3 > min_distance_km):
            logger.info("edge flagged.")
            edge_flag = True

            results.append(
            {
                "beaconer_pubkey": beaconer_pubkey,
                "witness_pubkey": witness_pubkey,
                "transmit_power_dBm": tx_rx_pair["beaconer_tx_power"],
                "frequency_hz": freq_hz,
                "measured_rssi": rssi_mean,
                "measured_loss": float(measured_loss),
                "samples": sum(counts),
                "std_dev": float(rssi_std_dev),
                "itm_loss": itm_loss,
                "itm_loss_profile": itm_loss_profile,
                "residual": residual,
                "distance_km": profile.distances()[-1] / 1e3,  # convert meters to kilometers,
                "terrain_profile_distances": profile.distances(),
                "terrain_profile_elevations": profile.elevation(),
                "tx_antenna_height_m": tx_loc.alt,
                "rx_antenna_height_m": rx_loc.alt,
                "tx_antenna_gain_dB": tx_rx_pair["beaconer_gain"] / 10.0,
                "rx_antenna_gain_dB": tx_rx_pair["witness_gain"] / 10.0,
                "edge_flag": edge_flag
            }
        )

        logger.info(
            f"""Model residual for pair {beaconer_pubkey} -> {witness_pubkey}: {residual} dB ({len(counts)} samples, var: {rssi_variance})"""
        )

    return(pl.from_dicts(results) if len(results) else pl.DataFrame())