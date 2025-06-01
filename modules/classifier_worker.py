import os
import click
import logging
import polars as pl
import csv as pycsv
import itm_classifier
from dotenv import dotenv_values
from arango import ArangoClient
from geoprop import Tiles, Itm, Climate
from report_card import generate_pdf_report

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

config = dotenv_values(".env")

try:
    db_url = config["ARANGO_DB_URL"]
    db_name = config["ARANGO_DB_NAME"]
    db_username = config["ARANGO_DB_USERNAME"]
    db_password = config["ARANGO_DB_PASSWORD"]

    client = ArangoClient(hosts=db_url)
    db = client.db(db_name, db_username, db_password)
    logger.info(f"Connected to ArangoDB: {db_name}@{db_url}")

except Exception as e:
    logger.error(f"Failed to connect to ArangoDB: {e}")
    raise click.Abort()

try:
    tiles = Tiles(config["SRTM_TILE_DIR"])
    itm = Itm(tiles, climate=Climate.ContinentalTemperate)
except Exception as e:
    logger.error(f"Failed to load SRTM tile directory and initialize ITM module: {e}")
    raise click.Abort()

try:
    min_distance_km = float(config.get("MIN_DISTANCE_KM", 1.0))
    threshold_db = float(config.get("THRESHOLD_DB", -30.0))
    h3_search_radius = int(config.get("H3_SEARCH_RADIUS", 1))
    min_samples = int(config.get("MIN_SAMPLES", 10))
    max_beaconers = int(config.get("MAX_BEACONERS", 250))
    batch_size = int(config.get("BATCH_SIZE", 1000))
    n_workers = int(config.get("N_WORKERS", 4))
    report_card_dir = config.get("REPORT_CARD_DIR", "report_cards")
    include_edge_metadata = os.getenv("INCLUDE_EDGE_METADATA", "False") == "True"

except Exception as e:
    logger.error(f"Failed to parse configuration values: {e}")
    raise click.Abort()


@click.command()
@click.argument("input_csv", type=click.Path(exists=True))
@click.argument("output_csv", type=click.Path())
def worker(input_csv, output_csv):
    """
    CLI worker to compute ITM residuals from a list of beaconer pubkeys in INPUT_CSV.
    Saves output as CSV defined in OUTPUT_CSV from .env.
    """

    logger.info(f"Reading witness pubkeys from {input_csv}...")

    try:
        with open(input_csv, newline="") as f:
            reader = pycsv.reader(f)
            witness_pubkeys = [
                row[0].strip() for row in reader if row and row[0].strip()
            ]
    except Exception as e:
        logger.error(f"Failed to read input CSV: {e}")
        raise click.Abort()

    logger.info(f"Running ITM classifier on {len(witness_pubkeys)} hotspots...")

    try:
        df = itm_classifier.compute_residuals(
            db=db,
            itm_model=itm,
            tiles=tiles,
            witness_pubkeys=witness_pubkeys,
            beaconer_pubkeys=[],
            max_witnesses=max_beaconers,
            min_samples=min_samples,
            min_distance_km=min_distance_km,
            threshold_db=threshold_db,
            h3_search_radius=h3_search_radius,
        )
    except Exception as e:
        logger.error(f"Failed to compute residuals: {e}")
        raise click.Abort()

    if df.shape[0] == 0:
        logger.warning("No valid links found. Nothing to write.")
        return

    logger.info(
        f"Writing {df.shape[0]} flagged beaconer->witness pairs to {output_csv}..."
    )
    try:
        df.filter(pl.col("edge_flag") == True).select(
            ["beaconer_pubkey", "witness_pubkey"]
        ).write_csv(output_csv)
    except Exception as e:
        logger.error(f"Failed to write output CSV: {e}")
        raise click.Abort()

    worst_edges = (
        df.filter(pl.col("edge_flag") == True)
        .sort("residual")
        .group_by("witness_pubkey")
        .first()
    )
    logger.info(
        f"Starting report card generation for {len(worst_edges)} beaconer -> witness pairs."
    )

    for row in worst_edges.iter_rows(named=True):
        witness = row["witness_pubkey"].strip("hotspots/")
        beaconer = row["beaconer_pubkey"].strip("hotspots/")
        logger.info(f"creating report card for {beaconer} -> {witness}.")

        itm_profile_result = itm_classifier.compute_residuals(
            db,
            itm,
            tiles,
            witness_pubkeys=[witness],
            beaconer_pubkeys=[beaconer],
            max_witnesses=1,
            min_samples=min_samples,
            min_distance_km=min_distance_km,
            threshold_db=threshold_db,
            h3_search_radius=h3_search_radius,
            compute_loss_profile=True,
        )
        if not len(itm_profile_result):
            logger.warning(
                f"No ITM loss profile available for {beaconer} -> {witness}."
            )
            continue

        logger.debug("Loss profile: " + str(itm_profile_result["itm_loss_profile"]))
        report_card_file = os.path.join(report_card_dir, f"{witness}.pdf")

        generate_pdf_report(
            file_path=report_card_file,
            beaconer_pubkey=itm_profile_result["beaconer_pubkey"][0],
            witness_pubkey=itm_profile_result["witness_pubkey"][0],
            terrain_profile_elevations=itm_profile_result["terrain_profile_elevations"][
                0
            ],
            terrain_profile_distances=itm_profile_result["terrain_profile_distances"][
                0
            ],
            tx_antenna_height_m=float(itm_profile_result["tx_antenna_height_m"][0]),
            rx_antenna_height_m=float(itm_profile_result["rx_antenna_height_m"][0]),
            frequency_hz=int(itm_profile_result["frequency_hz"][0]),
            itm_loss_profile=itm_profile_result["itm_loss_profile"][0],
            tx_power_dBm=float(itm_profile_result["transmit_power_dBm"][0]),
            tx_gain_dB=float(itm_profile_result["tx_antenna_gain_dB"][0]),
            rx_gain_dB=float(itm_profile_result["rx_antenna_gain_dB"][0]),
            measured_rssi=float(itm_profile_result["measured_rssi"][0]),
            std_dev=float(itm_profile_result["std_dev"][0]),
            samples=int(itm_profile_result["samples"][0]),
        )

        logger.info(f"report card written: {report_card_file}")

    logger.info("Finished report card generation for batch.")


if __name__ == "__main__":
    worker()
