#!/usr/bin/env python3
"""
Prepare the Building Height dataset for EnerMaps.

Note that the  files must be downloaded from Copernicus (requires log-in)
and extracted in the data/31 directory.
This script expects that the original zip file from Copernicus is extracted
in multiple zip files.

@author: giuseppeperonato
"""

import argparse
import glob
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys

import geopandas as gpd
import pandas as pd
import utilities
from osgeo import gdal, osr
from pyproj import CRS
from shapely.geometry import box

N_FILES = 38
ISRASTER = True
logging.basicConfig(level=logging.INFO)

DB_URL = utilities.DB_URL
SRS = CRS.from_string("EPSG:3035")


def getExtentBox(ds):
    """Return shapely box of corner coordinates from a gdal Dataset."""
    xmin, xpixel, _, ymax, _, ypixel = ds.GetGeoTransform()
    width, height = ds.RasterXSize, ds.RasterYSize
    xmax = xmin + width * xpixel
    ymin = ymax + height * ypixel

    return box(xmin, ymin, xmax, ymax)


def convertZip(directory: str):
    """Convert files downloaded from Copernicus."""
    zipfiles = glob.glob(os.path.join(directory, "*.zip"))
    if zipfiles:
        logging.info("Extracting zip files")
        for zipfile in zipfiles:
            extract_dir = os.path.join(
                os.path.dirname(zipfile),
                pathlib.Path(zipfile).stem,  # use the name of file without extension
            )
            extracted = utilities.extractZip(zipfile, extract_dir)
            tif_files = [x for x in extracted if x.endswith("tif")]

            if not tif_files:
                logging.warning("no tiff file found in zipfile")
                continue

            source_file = tif_files[0]
            logging.info(source_file)

            dest_file = extract_dir + ".tif"
            subprocess.run(
                [
                    "gdal_translate",
                    source_file,
                    dest_file,
                    "-a_srs",
                    SRS.to_string(),
                    "-of",
                    "GTIFF",
                    "--config",
                    "GDAL_PAM_ENABLED NO",
                    "-co COMPRESS=DEFLATE -co BIGTIFF=YES",
                ],
                shell=False,
            )

            # Remove temporary files
            shutil.rmtree(extract_dir)
            os.remove(zipfile)
    else:
        logging.info("There are no zip files to extract")


def get(directory):
    """Prepare df and gdf from rasters."""
    files_list = glob.glob(os.path.join(directory, "*.tif"))
    fids = []
    extents = []
    for file in files_list:
        logging.info(file)
        src_ds = gdal.Open(file)
        prj = src_ds.GetProjection()
        srs = osr.SpatialReference(wkt=prj)
        source_srs = CRS.from_epsg(srs.GetAttrValue("authority", 1))

        if source_srs != SRS:
            logging.error("Input files must be in {}".format(SRS.to_string()))

        extentBox = getExtentBox(src_ds)
        fids.append(os.path.basename(file))
        extents.append(extentBox)

    enermaps_data = utilities.ENERMAPS_DF
    enermaps_data["fid"] = fids

    spatial = gpd.GeoDataFrame(geometry=extents, crs=SRS.to_string(),)
    spatial["fid"] = fids

    return enermaps_data, spatial


if __name__ == "__main__":
    datasets = pd.read_csv("datasets.csv", index_col=[0])
    ds_ids = datasets[datasets["di_script"] == os.path.basename(sys.argv[0])].index
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Import dataset")
        parser.add_argument("--force", action="store_const", const=True, default=False)
        parser.add_argument(
            "--select_ds_ids", action="extend", nargs="+", type=int, default=[]
        )
        args = parser.parse_args()
        isForced = args.force
        if len(args.select_ds_ids) > 0:
            ds_ids = args.select_ds_ids
    else:
        isForced = False

    for ds_id in ds_ids:
        directory = "./data/{}".format(ds_id)

        if os.path.isdir(directory) and len(os.listdir(directory)) == N_FILES:
            # Dezip
            convertZip(directory)

            data, spatial = get(directory)

            # Remove existing dataset
            if utilities.datasetExists(ds_id, DB_URL) and not isForced:
                raise FileExistsError("Use --force to replace the existing dataset.")
            elif utilities.datasetExists(ds_id, DB_URL) and isForced:
                utilities.removeDataset(ds_id, DB_URL)
                logging.info("Removed existing dataset")
            else:
                pass

            # Create dataset table
            metadata = datasets.loc[ds_id].fillna("").to_dict()
            metadata = json.dumps(metadata)
            dataset = pd.DataFrame([{"ds_id": ds_id, "metadata": metadata}])
            utilities.toPostgreSQL(
                dataset, DB_URL, schema="datasets",
            )

            # Create data table
            data["ds_id"] = ds_id
            utilities.toPostgreSQL(
                data, DB_URL, schema="data",
            )
            # Create spatial table
            spatial["ds_id"] = ds_id
            utilities.toPostGIS(
                spatial, DB_URL, schema="spatial",
            )
        else:
            logging.error(
                "The %s directory must exist and contain %s files from Copernicus.",
                directory,
                N_FILES,
            )
