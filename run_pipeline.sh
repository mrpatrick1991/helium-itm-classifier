python modules/fetch_hotspot_inventory.py --batch-size 100
ls hotspots/batch_*.csv | sort -V | parallel -j 6 ./scripts/run_worker.sh {}
./scripts/merge_outputs.sh