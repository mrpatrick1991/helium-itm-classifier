#!/bin/bash

INPUT=$1
BASENAME=$(basename "$INPUT" .csv)
OUTPUT=outputs/${BASENAME}_output.csv
python modules/classifier_worker.py "$INPUT" "$OUTPUT"
