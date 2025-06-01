import os
import click
import logging
import csv
from dotenv import dotenv_values
from arango import ArangoClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

config = dotenv_values(".env") 

def _get_db():
    try:
        db_url = config["ARANGO_DB_URL"]
        db_name = config["ARANGO_DB_NAME"]
        db_username = config["ARANGO_DB_USERNAME"]
        db_password = config["ARANGO_DB_PASSWORD"]

        client = ArangoClient(hosts=db_url)
        db = client.db(db_name, db_username, db_password)
        logger.info(f"Connected to ArangoDB: {db_name}@{db_url}")
        return db
    except Exception as e:
        logger.error("Failed to connect to ArangoDB", exc_info=True)
        raise e

def _yield_hotspot_pubkeys(db, batch_size:int=100, max_batches=None):
    offset = 0
    batch_count = 0
    while True:
        if max_batches is not None and batch_count >= max_batches:
            break

        query = '''
        FOR hs IN hotspots
            SORT hs._key
            LIMIT @offset, @count
            RETURN hs._key
        '''

        bind_vars = {"offset": offset, "count": batch_size}
        cursor = db.aql.execute(query, bind_vars=bind_vars)
        results = list(cursor)
        logging.info(f"Downloaded {len(results)} hotspot pubkeys (batch size: {batch_size}, max batches: {max_batches}).")
        if not results:
            break
        yield results
        offset += batch_size
        batch_count += 1


output_dir=config["HS_BATCH_DIR"]

@click.command()
@click.option("--batch-size", default=100, help="Number of keys per CSV file.")
@click.option("--max-batches", default=None, type=int, help="Maximum number of batches to save.")
def save_hotspot_inventory(batch_size, max_batches):
    db = _get_db()
    os.makedirs(output_dir, exist_ok=True)

    for batch_idx, pubkey_batch in enumerate(_yield_hotspot_pubkeys(db, batch_size, max_batches)):
        filename = os.path.join(output_dir, f"batch_{batch_idx:03d}.csv")
        with open(filename, mode='w', newline='') as f:
            writer = csv.writer(f)
            for pubkey in pubkey_batch:
                writer.writerow([pubkey])
        logging.info(f"Wrote pubkey batch to: {filename}.")

if __name__ == "__main__":
    save_hotspot_inventory()
