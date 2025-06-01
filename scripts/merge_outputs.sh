#!/bin/bash

rm -f itm_classifier_output.csv

# Find first non-empty CSV to extract the header
HEADER_SOURCE=$(find outputs/ -name "*_output.csv" -size +1c | sort | head -n 1)

if [ -z "$HEADER_SOURCE" ]; then
  echo "No non-empty output files found."
  exit 1
fi

head -n 1 "$HEADER_SOURCE" > itm_classifier_output.csv
find outputs/ -name "*_output.csv" -size +1c | xargs -I{} tail -n +2 {} >> itm_classifier_output.csv

echo "Merged output written to itm_classifier_output.csv"
